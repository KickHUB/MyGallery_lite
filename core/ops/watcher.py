from __future__ import annotations
import os, time, shutil, threading, logging, errno, sqlite3, re
from pathlib import Path
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

from settings import SOURCE, DEST, DB_PATH, WD14_MODEL_PATH
from core.media.gallery_layout import get_media_root
from core.media.image_utils import organize_pngs
from core.tagging.tag_utils import extract_prompt_from_file
from core.db.search_utils import save_tags_to_db
from core.media.thumbs import build_thumbnail_cache
from core.media.video_index import upsert_video
from core.booru.booru_dict import ensure_booru_tables
from core.booru.booru_item_tags import replace_item_tags
from core.tagging.wd14_tagger import AUTO_WD14_SOURCE, auto_tag_rel_path, should_auto_tag_on_refresh

logger = logging.getLogger(__name__)


def _is_file_lock_error(exc: OSError) -> bool:
    """Return True if *exc* represents a temporary file lock/sharing violation."""

    winerr = getattr(exc, "winerror", None)
    if winerr in (32, 33):  # Windows sharing violation / lock
        return True
    err_no = getattr(exc, "errno", None)
    return err_no in {errno.EACCES, errno.EPERM, errno.EBUSY}

def _run_thread_with_timeout(target, timeout: float, *args, **kwargs):
    """Run target in a daemon thread and log if it exceeds *timeout* seconds."""

    def wrapper():
        try:
            target(*args, **kwargs)
        except Exception:
            logger.exception("Thread execution error in %s", getattr(target, '__name__', str(target)))

    t = threading.Thread(target=wrapper, daemon=True)
    t.start()

    def monitor():
        t.join(timeout)
        if t.is_alive():
            logger.warning("Thread %s timed out after %s seconds", getattr(target, '__name__', str(target)), timeout)

    threading.Thread(target=monitor, daemon=True).start()

VIDEO_EXTS = (".mp4", ".webm", ".mov", ".avi", ".mkv", ".gif")

def _safe_unique_path(base_dir: Path, filename: str) -> Path:
    target = base_dir / filename
    if not target.exists():
        return target
    stem, ext = os.path.splitext(filename)
    # Avoid cascading suffixes like _1_1_1 on repeated retries.
    stem = re.sub(r"_\d+$", "", stem)
    i = 1
    while True:
        cand = base_dir / f"{stem}_{i}{ext}"
        if not cand.exists():
            return cand
        i += 1


def _find_video_for_stems(stem_candidates: list[str]) -> Path | None:
    for cand_stem in stem_candidates:
        for ext in VIDEO_EXTS:
            cand = Path(SOURCE) / f"{cand_stem}{ext}"
            if cand.exists():
                return cand
    return None


def _prepare_video_targets(video_path: Path) -> tuple[Path, Path, str]:
    ctime = os.path.getctime(str(video_path))
    date_str = time.strftime("%Y-%m-%d", time.localtime(ctime))
    ts_name = time.strftime("%Y%m%d_%H%M%S", time.localtime(ctime))

    videos_dir = get_media_root(DEST, date_str, "videos", create=True)
    videos_folder = videos_dir.as_posix()

    audio_suffix = "-audio" if video_path.stem.lower().endswith("-audio") else ""
    video_ext = video_path.suffix.lower()
    new_video_name = f"{ts_name}(video){audio_suffix}{video_ext}"
    new_png_name = f"{ts_name}(video){audio_suffix}.png"

    target_dir = Path(videos_folder)
    dst_video = _safe_unique_path(target_dir, new_video_name)
    dst_png = _safe_unique_path(target_dir, new_png_name)
    return dst_video, dst_png, videos_folder


def handle_video_png(png_path: str, wait_seconds: int = 25) -> bool:
    try:
        src_png = Path(png_path)
        stem = src_png.stem
        if not stem.lower().startswith("video"):
            return False

        stem_candidates = [stem]
        if stem.lower().endswith("-audio"):
            base_stem = stem[:-6]
            if base_stem and base_stem != stem:
                stem_candidates.append(base_stem)
        else:
            stem_candidates.append(f"{stem}-audio")

        # wait for video
        video_path = None
        for _ in range(max(1, wait_seconds)):
            video_path = _find_video_for_stems(stem_candidates)
            if video_path:
                break
            time.sleep(1)
        if not video_path:
            logger.warning("⏳ 영상 대기 초과: %s* (PNG만 확인됨)", stem)
            return True


        if not _wait_for_file_stable(video_path, timeout=wait_seconds):
            logger.warning("Video not stable yet, delaying move: %s", video_path)
            return False

        dst_video, dst_png, videos_folder = _prepare_video_targets(video_path)
        target_dir = dst_video.parent

        move_success = False
        last_err: Exception | None = None
        missing_path: Path | None = None
        max_attempts = max(3, wait_seconds)
        for attempt in range(max_attempts):
            current_path = video_path
            try:
                shutil.move(str(video_path), str(dst_video))
                move_success = True
                break
            except FileNotFoundError as exc:
                last_err = exc
                missing_path = current_path
                video_path = _find_video_for_stems(stem_candidates)
                if video_path:
                    dst_video, dst_png, videos_folder = _prepare_video_targets(video_path)
                    target_dir = dst_video.parent
                    continue
                if attempt + 1 >= max_attempts:
                    break
                time.sleep(1.0)
                video_path = _find_video_for_stems(stem_candidates)
                if video_path:
                    dst_video, dst_png, videos_folder = _prepare_video_targets(video_path)
                    target_dir = dst_video.parent
                continue
            except (PermissionError, OSError) as exc:
                if not _is_file_lock_error(exc):
                    raise
                last_err = exc
                if dst_video.exists():
                    try:
                        dst_video.unlink()
                    except OSError:
                        pass
                if attempt + 1 >= max_attempts:
                    break
                time.sleep(1.0)
                dst_video = _safe_unique_path(target_dir, dst_video.name)

        if not move_success:
            if isinstance(last_err, FileNotFoundError):
                logger.warning("⚠️ 영상 파일을 찾지 못해 이동을 건너뜁니다: %s", missing_path or video_path)
                return True
            logger.warning("⚠️ 영상 이동 실패 (파일 사용 중): %s", video_path)
            if last_err:
                logger.debug("마지막 이동 오류: %s", last_err)
            print(f"[WARN] Video move failed (in use): {video_path.name}")
            return False

        shutil.move(str(src_png), str(dst_png))

        build_thumbnail_cache(str(dst_png))

        upsert_video(str(dst_video), str(dst_png))
        print(f"[INFO] Video cleanup done: {stem} -> {videos_folder} / {dst_video.name}, {dst_png.name}")
        return True
    except Exception:
        logger.exception("❌ 영상 정리 오류")
        return False




def _wait_for_file_stable(path: Path, timeout: int = 25, interval: float = 1.0, stable_checks: int = 3) -> bool:
    """파일 쓰기 완료(크기 안정화)까지 대기한다."""
    last_size = -1
    stable = 0
    checks = max(1, int(timeout / max(0.1, interval)))
    for _ in range(checks):
        try:
            size = path.stat().st_size
        except FileNotFoundError:
            time.sleep(interval)
            continue
        if size > 0 and size == last_size:
            stable += 1
            if stable >= stable_checks:
                return True
        else:
            stable = 0
            last_size = size
        time.sleep(interval)
    return False


def handle_video_only(video_path: str, wait_seconds: int = 25) -> bool:
    """PNG 페어 없이 영상 단독으로 들어온 경우 정리/인덱싱한다."""
    try:
        src_video = Path(video_path)
        if not src_video.exists() or not src_video.is_file():
            return False

        stem = src_video.stem
        if not stem.lower().startswith('video'):
            return False

        # 페어 PNG가 있으면 기존 루틴(handle_video_png)이 처리하도록 둔다.
        pair_png = src_video.with_suffix('.png')
        if pair_png.exists():
            return True

        # 짧게 페어 PNG 생성 가능성 대기
        for _ in range(5):
            if pair_png.exists():
                return True
            time.sleep(1.0)

        # 파일 쓰기 완료(크기 안정화) 대기
        _wait_for_file_stable(src_video, timeout=wait_seconds)

        dst_video, _dst_png, videos_folder = _prepare_video_targets(src_video)
        target_dir = dst_video.parent

        move_success = False
        last_err: Exception | None = None
        max_attempts = max(3, wait_seconds)
        for attempt in range(max_attempts):
            try:
                shutil.move(str(src_video), str(dst_video))
                move_success = True
                break
            except FileNotFoundError as exc:
                last_err = exc
                if attempt + 1 >= max_attempts:
                    break
                time.sleep(1.0)
            except (PermissionError, OSError) as exc:
                if not _is_file_lock_error(exc):
                    raise
                last_err = exc
                if attempt + 1 >= max_attempts:
                    break
                time.sleep(1.0)
                dst_video = _safe_unique_path(target_dir, dst_video.name)

        if not move_success:
            logger.warning('⚠️ 영상(단독) 이동 실패: %s (%s)', src_video, last_err)
            return False

        # 썸네일 캐시(영상 프레임) 생성
        build_thumbnail_cache(str(dst_video))

        # 메타 인덱싱(영상 자체의 comment/description에서 ComfyUI prompt/workflow 읽기)
        meta = extract_prompt_from_file(str(dst_video))
        upsert_video(str(dst_video), str(dst_video), meta)

        print(f"[INFO] Video cleanup done (video-only): {stem} -> {videos_folder} / {dst_video.name}")
        return True
    except Exception:
        logger.exception('❌ 영상(단독) 정리 오류')
        return False


def _process_video_only(video_path: str):
    try:
        time.sleep(2.0)
        handle_video_only(video_path, wait_seconds=25)
        # 영상 정리 후, PNG 정리 파이프라인도 한 번 태워서 누락이 없게 한다.
        _process_png_common()
    except Exception:
        logger.exception('❌ 영상(단독) 처리 스레드 오류')
def _auto_tag_items(items: list[dict]) -> None:
    if not items or not should_auto_tag_on_refresh():
        return

    if not WD14_MODEL_PATH or not Path(WD14_MODEL_PATH).exists():
        logger.info("WD14 모델 경로가 없어서 자동 태깅을 건너뜁니다.")
        return

    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    try:
        ensure_booru_tables(cur=cur, conn=conn)
        for item in items:
            rel_path = item.get("file")
            if not rel_path:
                continue
            try:
                tags, rating_code = auto_tag_rel_path(rel_path)
            except Exception as exc:
                logger.debug("WD14 자동 태깅 실패: %s (%s)", rel_path, exc)
                continue
            replace_item_tags("image", rel_path, tags, source=AUTO_WD14_SOURCE, conn=conn)
            if rating_code is None:
                cur.execute(
                    "DELETE FROM booru_item_rating WHERE media_type=? AND media_path=? AND source=?",
                    ("image", rel_path, AUTO_WD14_SOURCE),
                )
            else:
                cur.execute(
                    """
                    INSERT INTO booru_item_rating (media_type, media_path, rating, source)
                    VALUES (?, ?, ?, ?)
                    ON CONFLICT(media_type, media_path, source)
                    DO UPDATE SET rating=excluded.rating, updated_at=CURRENT_TIMESTAMP
                    """,
                    ("image", rel_path, rating_code, AUTO_WD14_SOURCE),
                )
        conn.commit()
    except Exception:
        conn.rollback()
        logger.exception("WD14 자동 태깅 중 오류 발생")
    finally:
        conn.close()

def _process_png_common(delay: float = 3.0):
    try:
        if delay > 0:
            time.sleep(delay)
        moved = organize_pngs(SOURCE, DEST, rename=True)

        for moved_png in moved:
            build_thumbnail_cache(moved_png)

        items = []
        for p in moved:
            it = extract_prompt_from_file(p)
            if it:
                items.append(it)
        if items:
            save_tags_to_db(items)
            _auto_tag_items(items)
            print(f"[INFO] DB save done (images: {len(items)})")
        else:
            print("[INFO] No images to index")
    except Exception:
        logger.exception("❌ 정리 중 오류")


def _process_video_png(png_path: str):
    try:
        time.sleep(2.0)
        ok = handle_video_png(png_path, wait_seconds=25)
        if not ok:
            time.sleep(5.0)
            handle_video_png(png_path, wait_seconds=25)
        # Draft 이동 등 후속 파일도 기존 인덱싱 파이프라인을 그대로 태운다.
        # organize_pngs(skip_video_meta=True) 덕분에 영상 메타 PNG는 중복 처리되지 않는다.
        _process_png_common()
    except Exception:
        logger.exception("❌ 영상 처리 스레드 오류")


def process_existing_on_startup() -> None:
    """Process PNG/video files that already exist in the SOURCE folder."""

    try:
        src_dir = Path(SOURCE)
        if not src_dir.is_dir():
            return

        pending_pngs = sorted(
            [p for p in src_dir.iterdir() if p.is_file() and p.suffix.lower() == ".png"],
            key=lambda p: p.stat().st_ctime,
        )
        pending_videos = sorted(
            [p for p in src_dir.iterdir() if p.is_file() and p.suffix.lower() in VIDEO_EXTS],
            key=lambda p: p.stat().st_ctime,
        )

        if not pending_pngs and not pending_videos:
            return

        print(
            f"[INFO] Startup cleanup begin (background): existing PNG {len(pending_pngs)}, existing videos {len(pending_videos)}"
        )

        # video+png (기존 루틴)
        video_candidates = [p for p in pending_pngs if p.name.lower().startswith("video")]
        processed_videos = 0
        for png in video_candidates:
            try:
                if handle_video_png(png.as_posix()):
                    processed_videos += 1
            except Exception:
                logger.exception("❌ 초기 영상 처리 실패: %s", png.name)

        # video only
        processed_video_only = 0
        for vid in pending_videos:
            if not vid.name.lower().startswith("video"):
                continue
            pair_png = vid.with_suffix('.png')
            if pair_png.exists():
                continue
            try:
                if handle_video_only(vid.as_posix()):
                    processed_video_only += 1
            except Exception:
                logger.exception("❌ 초기 영상(단독) 처리 실패: %s", vid.name)

        # 정리되지 않은 일반 PNG 처리 (delay 없이 즉시 실행)
        _process_png_common(delay=0.0)

        if processed_videos or processed_video_only:
            print(
                f"[INFO] Startup video cleanup done (background): paired {processed_videos}, video-only {processed_video_only} moved"
            )
        else:
            print("[INFO] No startup video cleanup targets (background)")
    except Exception:
        logger.exception("❌ 초기 PNG/영상 정리 중 오류")


class NewMediaHandler(FileSystemEventHandler):
    def on_created(self, event):
        if getattr(event, 'is_directory', False):
            return
        src = str(event.src_path)
        low = src.lower()

        if low.endswith('.png'):
            print(f"[INFO] New PNG detected: {os.path.basename(src)}")
            fname = os.path.basename(src).lower()
            if fname.startswith('video'):
                _run_thread_with_timeout(_process_video_png, 60, src)
            else:
                _run_thread_with_timeout(_process_png_common, 60)
            return

        if any(low.endswith(ext) for ext in VIDEO_EXTS):
            fname = os.path.basename(src).lower()
            if not fname.startswith('video'):
                return
            print(f"[INFO] New video detected: {os.path.basename(src)}")
            _run_thread_with_timeout(_process_video_only, 60, src)


def start_watchdog():
    source_path = (SOURCE or "").strip()
    if not source_path:
        logger.warning("watchdog 시작 생략: SOURCE가 설정되지 않았습니다.")
        print("[WARN] SOURCE is not set. watchdog will not start.")
        return

    src_dir = Path(source_path)
    if not src_dir.is_dir():
        logger.warning("watchdog 시작 생략: SOURCE 경로가 존재하지 않습니다. (%s)", source_path)
        print(f"[WARN] SOURCE path does not exist. watchdog will not start: {source_path}")
        return

    try:
        obs = Observer()
        obs.schedule(NewMediaHandler(), path=source_path, recursive=False)
        obs.start()
        print(f"[INFO] watchdog start: {source_path}")
        threading.Thread(target=obs.join, daemon=True).start()
    except Exception:
        logger.exception("watchdog 시작 실패")
        print("[WARN] watchdog failed to start. Check SOURCE path in settings.")

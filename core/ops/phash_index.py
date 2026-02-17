from __future__ import annotations

import logging
import os
import sqlite3
import tempfile
import time
from typing import Any, Dict

from PIL import Image, UnidentifiedImageError

from settings import DB_PATH
from core.db.search_utils import ensure_image_tables
from core.db.phash_relations import clear_phash_relations, clear_phash_groups
from core.media.video_index import ensure_videos_table
from core.media.thumbs import generate_thumbnail
from core.utils.path_utils import resolve_dest_path

HASH_ALGO = "phash"
HASH_SIZE = 8
DEFAULT_BATCH_SIZE = 200
ERROR_SAMPLE_LIMIT = 20
PROGRESS_EVERY = 25
VIDEO_EXTS = (".mp4", ".webm", ".mov", ".avi", ".mkv")

logger = logging.getLogger(__name__)


def _emit(message: str, log_cb=None) -> None:
    if log_cb:
        log_cb(message)
    else:
        logger.info(message)


def _format_error(exc: Exception) -> str:
    message = str(exc).strip()
    if message:
        return f"{type(exc).__name__}: {message}"
    return f"{type(exc).__name__}"


def _is_video_path(path: str) -> bool:
    return os.path.splitext(path)[1].lower() in VIDEO_EXTS


def _compute_phash_from_image(imagehash, path: str) -> str:
    with Image.open(path) as img:
        if getattr(img, "is_animated", False):
            try:
                img.seek(0)
            except EOFError:
                pass
        rgb = img.convert("RGB")
        return str(imagehash.phash(rgb, hash_size=HASH_SIZE))


def _compute_phash_from_video(imagehash, path: str) -> str:
    with tempfile.TemporaryDirectory(prefix="phash_") as tmpdir:
        frame_path = os.path.join(tmpdir, "frame.png")
        generate_thumbnail(path, frame_path)
        return _compute_phash_from_image(imagehash, frame_path)


def _compute_phash(imagehash, abs_path: str) -> str:
    if _is_video_path(abs_path):
        return _compute_phash_from_video(imagehash, abs_path)
    return _compute_phash_from_image(imagehash, abs_path)


def run_phash_index(
    *,
    include_images: bool = True,
    include_videos: bool = True,
    force: bool = False,
    limit: int = 0,
    batch_size: int = DEFAULT_BATCH_SIZE,
    progress_cb=None,
    log_cb=None,
    cancel_event=None,
) -> Dict[str, Any]:
    try:
        import imagehash  # type: ignore
    except Exception as exc:
        message = f"imagehash 모듈을 찾을 수 없습니다. ImageHash 설치 후 다시 시도하세요. ({exc})"
        _emit(message, log_cb)
        return {"status": "failed", "message": message, "error": message, "summary": {"sample_items": [message]}}

    if not include_images and not include_videos:
        message = "include_images/include_videos가 모두 꺼져 있어 작업을 중단합니다."
        _emit(message, log_cb)
        return {"status": "failed", "message": message, "error": message}

    ensure_image_tables()
    ensure_videos_table()

    limit = max(0, int(limit or 0))
    batch_size = max(1, int(batch_size or DEFAULT_BATCH_SIZE))

    summary: Dict[str, Any] = {
        "algo": HASH_ALGO,
        "hash_size": HASH_SIZE,
        "include_images": bool(include_images),
        "include_videos": bool(include_videos),
        "force": bool(force),
        "images": {},
        "videos": {},
        "sample_label": "pHash 요약",
        "sample_items": [],
    }
    error_samples: list[str] = []
    start = time.time()

    def update_progress(message: str) -> None:
        if not progress_cb:
            return
        total = total_targets or 0
        percent = 100 if total == 0 else (processed_total / total) * 100
        progress_cb(percent, message, summary)

    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        update_cur = conn.cursor()

        image_total_all = 0
        image_targets = 0
        video_total_all = 0
        video_targets = 0

        if include_images:
            cur.execute("SELECT COUNT(*) FROM images")
            image_total_all = int(cur.fetchone()[0] or 0)
            if force:
                image_targets = image_total_all
            else:
                cur.execute("SELECT COUNT(*) FROM images WHERE phash IS NULL OR phash = ''")
                image_targets = int(cur.fetchone()[0] or 0)
            if limit > 0:
                image_targets = min(image_targets, limit)

        if include_videos:
            cur.execute("SELECT COUNT(*) FROM videos")
            video_total_all = int(cur.fetchone()[0] or 0)
            if force:
                video_targets = video_total_all
            else:
                cur.execute("SELECT COUNT(*) FROM videos WHERE phash IS NULL OR phash = ''")
                video_targets = int(cur.fetchone()[0] or 0)
            if limit > 0:
                video_targets = min(video_targets, limit)

        total_targets = image_targets + video_targets
        processed_total = 0

        if include_images:
            _emit(f"이미지 pHash 계산 시작: 대상 {image_targets}건", log_cb)
            images_updated = images_missing = images_failed = 0
            images_skipped = max(0, image_total_all - image_targets) if not force else 0

            sql = "SELECT id, file FROM images"
            params: list[Any] = []
            if not force:
                sql += " WHERE phash IS NULL OR phash = ''"
            if limit > 0:
                sql += " LIMIT ?"
                params.append(limit)
            cur.execute(sql, params)

            pending = 0
            for row in cur:
                if cancel_event is not None and cancel_event.is_set():
                    _emit("이미지 pHash 계산이 취소되었습니다.", log_cb)
                    break
                rel_path = row["file"]
                abs_path = resolve_dest_path(rel_path)
                if not abs_path or not os.path.isfile(abs_path):
                    images_missing += 1
                    if len(error_samples) < ERROR_SAMPLE_LIMIT:
                        msg = f"missing: {rel_path}"
                        error_samples.append(msg)
                        _emit(f"이미지 파일 없음: {rel_path}", log_cb)
                else:
                    try:
                        phash = _compute_phash(imagehash, abs_path)
                        update_cur.execute("UPDATE images SET phash = ? WHERE id = ?", (phash, row["id"]))
                        images_updated += 1
                        pending += 1
                    except (UnidentifiedImageError, OSError, ValueError, RuntimeError) as exc:
                        images_failed += 1
                        if len(error_samples) < ERROR_SAMPLE_LIMIT:
                            msg = f"image_failed: {rel_path} ({_format_error(exc)})"
                            error_samples.append(msg)
                            _emit(f"이미지 pHash 실패: {rel_path} ({_format_error(exc)})", log_cb)
                    except Exception as exc:
                        images_failed += 1
                        if len(error_samples) < ERROR_SAMPLE_LIMIT:
                            msg = f"image_failed: {rel_path} ({_format_error(exc)})"
                            error_samples.append(msg)
                            _emit(f"이미지 pHash 실패: {rel_path} ({_format_error(exc)})", log_cb)

                processed_total += 1
                if pending >= batch_size:
                    conn.commit()
                    pending = 0
                if processed_total % PROGRESS_EVERY == 0:
                    update_progress("이미지 pHash 계산 중")

            if pending:
                conn.commit()

            summary["images"] = {
                "total": image_targets,
                "updated": images_updated,
                "missing": images_missing,
                "failed": images_failed,
                "skipped_existing": images_skipped,
            }

        if include_videos:
            _emit(f"영상 pHash 계산 시작: 대상 {video_targets}건", log_cb)
            videos_updated = videos_missing = videos_failed = 0
            videos_skipped = max(0, video_total_all - video_targets) if not force else 0

            sql = "SELECT id, rel_video, rel_thumb FROM videos"
            params = []
            if not force:
                sql += " WHERE phash IS NULL OR phash = ''"
            if limit > 0:
                sql += " LIMIT ?"
                params.append(limit)
            cur.execute(sql, params)

            pending = 0
            for row in cur:
                if cancel_event is not None and cancel_event.is_set():
                    _emit("영상 pHash 계산이 취소되었습니다.", log_cb)
                    break
                rel_source = row["rel_thumb"] or row["rel_video"] or ""
                if not rel_source:
                    videos_missing += 1
                    if len(error_samples) < ERROR_SAMPLE_LIMIT:
                        msg = f"missing: video_id={row['id']}"
                        error_samples.append(msg)
                        _emit(f"영상 소스 없음: id={row['id']}", log_cb)
                    processed_total += 1
                    continue
                abs_path = resolve_dest_path(rel_source)
                if not abs_path or not os.path.isfile(abs_path):
                    videos_missing += 1
                    if len(error_samples) < ERROR_SAMPLE_LIMIT:
                        msg = f"missing: {rel_source}"
                        error_samples.append(msg)
                        _emit(f"영상 파일 없음: {rel_source}", log_cb)
                else:
                    try:
                        phash = _compute_phash(imagehash, abs_path)
                        update_cur.execute("UPDATE videos SET phash = ? WHERE id = ?", (phash, row["id"]))
                        videos_updated += 1
                        pending += 1
                    except (UnidentifiedImageError, OSError, ValueError, RuntimeError) as exc:
                        videos_failed += 1
                        if len(error_samples) < ERROR_SAMPLE_LIMIT:
                            msg = f"video_failed: {rel_source} ({_format_error(exc)})"
                            error_samples.append(msg)
                            _emit(f"영상 pHash 실패: {rel_source} ({_format_error(exc)})", log_cb)
                    except Exception as exc:
                        videos_failed += 1
                        if len(error_samples) < ERROR_SAMPLE_LIMIT:
                            msg = f"video_failed: {rel_source} ({_format_error(exc)})"
                            error_samples.append(msg)
                            _emit(f"영상 pHash 실패: {rel_source} ({_format_error(exc)})", log_cb)

                processed_total += 1
                if pending >= batch_size:
                    conn.commit()
                    pending = 0
                if processed_total % PROGRESS_EVERY == 0:
                    update_progress("영상 pHash 계산 중")

            if pending:
                conn.commit()

            summary["videos"] = {
                "total": video_targets,
                "updated": videos_updated,
                "missing": videos_missing,
                "failed": videos_failed,
                "skipped_existing": videos_skipped,
            }

        updated_total = 0
        if include_images:
            updated_total += int(summary.get("images", {}).get("updated", 0) or 0)
        if include_videos:
            updated_total += int(summary.get("videos", {}).get("updated", 0) or 0)
        if updated_total > 0 or force:
            cleared = clear_phash_relations(conn=conn, cur=update_cur)
            if cleared:
                summary["relations_cleared"] = cleared
                _emit("pHash relations cache cleared", log_cb)
            groups_cleared = clear_phash_groups(conn=conn, cur=update_cur)
            if groups_cleared:
                summary["groups_cleared"] = groups_cleared
                _emit("pHash group cache cleared", log_cb)

    elapsed = time.time() - start
    summary["elapsed"] = elapsed

    sample_items = summary.get("sample_items", [])
    if include_images:
        sample_items.append(
            f"images: total={summary['images'].get('total', 0)} updated={summary['images'].get('updated', 0)} "
            f"missing={summary['images'].get('missing', 0)} failed={summary['images'].get('failed', 0)}"
        )
    if include_videos:
        sample_items.append(
            f"videos: total={summary['videos'].get('total', 0)} updated={summary['videos'].get('updated', 0)} "
            f"missing={summary['videos'].get('missing', 0)} failed={summary['videos'].get('failed', 0)}"
        )
    if error_samples:
        sample_items.extend(error_samples[:ERROR_SAMPLE_LIMIT])
    sample_items.append(f"elapsed={elapsed:.1f}s")
    summary["sample_items"] = sample_items

    update_progress("pHash 계산 완료")
    return {"status": "ok", "message": "pHash 추출 완료", "summary": summary}

from __future__ import annotations

import logging
import os
import shutil
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Callable, Iterable, Optional, Tuple

from PIL import UnidentifiedImageError

from core.media.thumbs import (
    THUMB_CACHE_DIR,
    build_thumb_cache_path,
    generate_thumbnail,
    normalize_thumb_rel_path,
    thumb_cache_is_fresh,
)

IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".webp", ".gif")
FAILED_SAMPLE_LIMIT = 20
FAILURE_ACTIONS = {"none", "failed", "quarantine"}

logger = logging.getLogger(__name__)


def iter_image_paths(dest_dir: str) -> Iterable[str]:
    thumb_root = os.path.abspath(THUMB_CACHE_DIR)
    failed_root = os.path.abspath(os.path.join(dest_dir, "failed"))
    quarantine_root = os.path.abspath(os.path.join(dest_dir, "quarantine"))
    for root, dirs, files in os.walk(dest_dir):
        abs_root = os.path.abspath(root)
        if abs_root.startswith((thumb_root, failed_root, quarantine_root)):
            dirs[:] = []
            continue
        for name in files:
            if name.lower().endswith(IMAGE_EXTS):
                yield os.path.join(root, name)


def _format_error(exc: Exception) -> str:
    message = str(exc).strip()
    if message:
        return f"{type(exc).__name__}: {message}"
    return f"{type(exc).__name__}"


def _safe_unique_path(base_dir: Path, filename: str) -> Path:
    target = base_dir / filename
    if not target.exists():
        return target
    stem, ext = os.path.splitext(filename)
    idx = 1
    while True:
        candidate = base_dir / f"{stem}_{idx}{ext}"
        if not candidate.exists():
            return candidate
        idx += 1


def _normalize_failure_action(action: Optional[str]) -> str:
    value = (action or "none").strip().lower()
    return value if value in FAILURE_ACTIONS else "none"


def _resolve_failure_root(dest_dir: str, action: str) -> Optional[Path]:
    if action == "failed":
        return Path(dest_dir) / "failed" / "thumb_prebuild"
    if action == "quarantine":
        return Path(dest_dir) / "quarantine" / "thumb_prebuild"
    return None


def _move_failure_file(abs_path: str, dest_dir: str, action: str) -> tuple[bool, Optional[str], Optional[str]]:
    root = _resolve_failure_root(dest_dir, action)
    if root is None:
        return False, None, None
    src = Path(abs_path)
    try:
        rel_path = os.path.relpath(abs_path, dest_dir)
    except ValueError:
        rel_path = src.name
    if rel_path.startswith(".."):
        rel_path = src.name
    target_dir = root / os.path.dirname(rel_path)
    try:
        src_resolved = src.resolve()
        root_resolved = root.resolve()
        try:
            src_resolved.relative_to(root_resolved)
            return False, None, None
        except ValueError:
            pass
    except Exception:
        pass
    target_dir.mkdir(parents=True, exist_ok=True)
    target_name = f"{src.stem}(failed_TP){src.suffix}"
    target = _safe_unique_path(target_dir, target_name)
    try:
        shutil.move(abs_path, target.as_posix())
    except Exception as exc:
        return False, None, _format_error(exc)
    return True, target.as_posix(), None


def build_thumb_for_file(abs_path: str, dest_dir: str) -> Tuple[str, str, Optional[str], Optional[str]]:
    rel_path = os.path.relpath(abs_path, dest_dir)
    normalized = normalize_thumb_rel_path(rel_path)
    if not normalized:
        return (abs_path, "skipped", None, None)
    thumb_path = build_thumb_cache_path(normalized)
    if thumb_cache_is_fresh(thumb_path, abs_path):
        return (abs_path, "skipped", None, None)
    try:
        generate_thumbnail(abs_path, thumb_path)
        return (abs_path, "created", None, None)
    except UnidentifiedImageError as exc:
        error_message = _format_error(exc)
        logger.warning("썸네일 생성 실패(손상 이미지): %s (%s)", abs_path, error_message, exc_info=exc)
        return (abs_path, "failed", error_message, "unidentified")
    except Exception as exc:
        error_message = _format_error(exc)
        logger.warning("썸네일 생성 실패: %s (%s)", abs_path, error_message, exc_info=exc)
        return (abs_path, "failed", error_message, None)


def run_thumb_prebuild(
    dest_dir: str,
    *,
    workers: Optional[int] = None,
    failure_action: Optional[str] = None,
    progress_cb: Optional[Callable[[float, str | None, dict | None], None]] = None,
    log_cb: Optional[Callable[[str], None]] = None,
    cancel_event=None,
) -> dict:
    dest_dir = os.path.abspath(dest_dir)
    if not os.path.isdir(dest_dir):
        raise FileNotFoundError(f"DEST 경로가 존재하지 않습니다: {dest_dir}")

    def emit(message: str) -> None:
        if log_cb:
            log_cb(message)
        else:
            logger.info(message)

    start = time.time()
    created = skipped = failed = 0
    unidentified_failed = 0
    moved_failed = 0
    moved_quarantine = 0
    failed_items: list[dict[str, str]] = []
    unidentified_items: list[dict[str, str]] = []
    paths = list(iter_image_paths(dest_dir))
    total = len(paths)
    action = _normalize_failure_action(failure_action)
    emit(f"썸네일 프리빌드 시작: {total}건")

    if workers is None:
        workers = max(2, min(8, (os.cpu_count() or 4)))

    if total == 0:
        summary = {
            "total": 0,
            "created": 0,
            "skipped": 0,
            "failed": 0,
            "unidentified_failed": 0,
            "moved_failed": 0,
            "moved_quarantine": 0,
            "elapsed": 0.0,
        }
        emit("썸네일 프리빌드 대상이 없습니다.")
        return {"status": "ok", "message": "썸네일 프리빌드 완료", "summary": summary}

    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {executor.submit(build_thumb_for_file, path, dest_dir): path for path in paths}
        processed = 0
        for future in as_completed(futures):
            if cancel_event is not None and cancel_event.is_set():
                for pending in futures:
                    pending.cancel()
                emit("썸네일 프리빌드가 취소되었습니다.")
                break
            abs_path, status, error_message, category = future.result()
            processed += 1
            if status == "created":
                created += 1
            elif status == "failed":
                failed += 1
                if category == "unidentified":
                    unidentified_failed += 1
                    if error_message:
                        unidentified_items.append({"path": abs_path, "error": error_message})
                    emit(f"손상 PNG 감지: {abs_path}")
                    if action in {"failed", "quarantine"}:
                        moved, target_path, move_error = _move_failure_file(abs_path, dest_dir, action)
                        if moved and target_path:
                            if action == "failed":
                                moved_failed += 1
                                emit(f"failed 폴더 이동: {abs_path} -> {target_path}")
                            else:
                                moved_quarantine += 1
                                emit(f"격리 폴더 이동: {abs_path} -> {target_path}")
                        elif move_error:
                            label = "failed 폴더" if action == "failed" else "격리 폴더"
                            emit(f"{label} 이동 실패: {abs_path} ({move_error})")
                if error_message:
                    failed_items.append({"path": abs_path, "error": error_message})
            else:
                skipped += 1
            if progress_cb:
                progress = (processed / total) * 100 if total else 0
                summary = {
                    "total": total,
                    "created": created,
                    "skipped": skipped,
                    "failed": failed,
                    "unidentified_failed": unidentified_failed,
                    "moved_failed": moved_failed,
                    "moved_quarantine": moved_quarantine,
                }
                progress_cb(progress, f"진행 {processed}/{total}", summary)
            if processed % 200 == 0 or processed == total:
                emit(f"진행: {processed}/{total}")

    elapsed = time.time() - start
    summary = {
        "total": total,
        "created": created,
        "skipped": skipped,
        "failed": failed,
        "unidentified_failed": unidentified_failed,
        "moved_failed": moved_failed,
        "moved_quarantine": moved_quarantine,
        "elapsed": round(elapsed, 1),
    }
    if failed_items:
        summary["failed_samples"] = failed_items[:FAILED_SAMPLE_LIMIT]
        summary["failed_sample_limit"] = FAILED_SAMPLE_LIMIT
    if unidentified_items:
        summary["unidentified_samples"] = unidentified_items[:FAILED_SAMPLE_LIMIT]
        summary["unidentified_sample_limit"] = FAILED_SAMPLE_LIMIT
    status = "ok" if failed == 0 else "failed"
    if cancel_event is not None and cancel_event.is_set():
        status = "cancelled"
        message = "썸네일 프리빌드 취소됨"
    else:
        message = "썸네일 프리빌드 완료"
    emit(
        f"썸네일 프리빌드 완료 (생성 {created}, 건너뜀 {skipped}, 실패 {failed}) - {elapsed:.1f}s"
    )
    if failed_items:
        sample_paths = [item["path"] for item in summary["failed_samples"]]
        emit(f"실패 파일 상위 {len(sample_paths)}개: {', '.join(sample_paths)}")
        if failed > len(sample_paths):
            emit(f"추가 실패 {failed - len(sample_paths)}건은 요약에서 제외되었습니다.")
    return {"status": status, "message": message, "summary": summary}

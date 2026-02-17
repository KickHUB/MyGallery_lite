# core/full_refresh.py
# Full re-index of images (including video thumbnails) + stale DB cleanup.

from __future__ import annotations

import logging
import os
import re
import shutil
import sqlite3
from concurrent.futures import ThreadPoolExecutor, as_completed
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Iterable

from settings import (
    DB_BACKUP_DIR,
    DEST,
    DEST_FOLDER_NAME,
    DB_PATH,
    MAX_DB_BACKUPS,
    METADATA_MISSING_EXTENDED_CHECKS,
    WD14_MODEL_PATH,
)
from core.media.gallery_layout import get_content_root, get_media_root, rel_under_dest
from core.db.search_utils import remove_image_from_db, save_tags_to_db
from core.tagging.tag_utils import extract_prompt_from_file, extract_prompt_with_reason
from core.tagging.wd14_tagger import AUTO_WD14_SOURCE, auto_tag_rel_path, should_auto_tag_on_refresh
from core.booru.booru_dict import ensure_booru_tables
from core.booru.booru_item_tags import replace_item_tags
from core.media.thumbs import (
    build_thumb_cache_path,
    generate_thumbnail,
    normalize_thumb_rel_path,
    thumb_cache_is_fresh,
)
from core.media.video_index import (
    bulk_upsert_from_dest,
    ensure_videos_table,
    remove_video_from_db,
)


class RefreshCancelled(Exception):
    """사용자 취소 시 흐름 제어용 예외."""

    pass


class BackupFailed(Exception):
    """DB 백업 실패 시 전체 재정리를 중단하기 위한 예외."""

    pass

logger = logging.getLogger(__name__)

DATE_FOLDER_PATTERN = re.compile(r"\d{4}-\d{2}-\d{2}")

REASON_CODES = {
    "missing_file": "missing_file",
    "permission_denied": "permission_denied",
    "parse_error": "parse_error",
    "db_error": "db_error",
    "io_error": "io_error",
    "already_indexed": "already_indexed",
    "metadata_missing": "metadata_missing",
    "cache_fresh": "cache_fresh",
    "videos_excluded": "videos_excluded",
    "unsupported_format": "unsupported_format",
    "unknown_error": "unknown_error",
    "no_db": "no_db",
}

IMAGE_SCAN_PARSERS = {
    ".png": "png_metadata",
    ".jpg": "exiftool",
    ".jpeg": "exiftool",
    ".webp": "exiftool",
}
IMAGE_DISCOVERY_EXTS = tuple(sorted(set(IMAGE_SCAN_PARSERS.keys()) | {".gif"}))


def _get_prompt_parser(ext: str) -> str | None:
    return IMAGE_SCAN_PARSERS.get(ext.lower())


def _iter_image_candidates(root: Path) -> Iterable[Path]:
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if path.suffix.lower() in IMAGE_DISCOVERY_EXTS:
            yield path


def _is_metadata_empty(value: object) -> bool:
    return value is None or (isinstance(value, str) and not value.strip())


def _should_rescan_metadata(
    row: tuple,
    lora_image_ids: set[int],
    include_extended: bool,
) -> bool:
    (
        image_id,
        _file,
        positive,
        negative,
        width,
        height,
        seed,
        sampler,
        steps,
        cfg,
    ) = row
    core_values = (positive, negative, width, height, seed)
    missing = any(_is_metadata_empty(val) for val in core_values)
    if include_extended:
        extended_values = (sampler, steps, cfg)
        missing = missing or any(_is_metadata_empty(val) for val in extended_values)
    if image_id not in lora_image_ids:
        missing = True
    return missing


def _metadata_missing_reasons(
    row: tuple,
    lora_image_ids: set[int],
    include_extended: bool,
) -> list[str]:
    (
        image_id,
        _file,
        positive,
        negative,
        width,
        height,
        seed,
        sampler,
        steps,
        cfg,
    ) = row
    reasons: list[str] = []
    if _is_metadata_empty(positive):
        reasons.append("positive")
    if _is_metadata_empty(negative):
        reasons.append("negative")
    if _is_metadata_empty(width):
        reasons.append("width")
    if _is_metadata_empty(height):
        reasons.append("height")
    if _is_metadata_empty(seed):
        reasons.append("seed")
    if include_extended:
        if _is_metadata_empty(sampler):
            reasons.append("sampler")
        if _is_metadata_empty(steps):
            reasons.append("steps")
        if _is_metadata_empty(cfg):
            reasons.append("cfg")
    if image_id not in lora_image_ids:
        reasons.append("loras")
    return reasons


def _init_step_counters(step_names: list[str]) -> dict[str, dict[str, object]]:
    return {
        step: {"success": 0, "skip": 0, "fail": 0, "reasons": {"skip": {}, "fail": {}}}
        for step in step_names
    }


def _bump_counter(
    counters: dict[str, dict[str, object]],
    step: str,
    outcome: str,
    reason: str | None = None,
    count: int = 1,
) -> None:
    if step not in counters:
        return
    counters[step][outcome] += count
    if reason:
        reason_bucket = counters[step]["reasons"].setdefault(outcome, {})
        reason_bucket[reason] = reason_bucket.get(reason, 0) + count


def _merge_reason_totals(
    counters: dict[str, dict[str, object]], outcome: str
) -> dict[str, int]:
    totals: dict[str, int] = {}
    for step_data in counters.values():
        reason_bucket = step_data["reasons"].get(outcome, {})
        for reason, count in reason_bucket.items():
            totals[reason] = totals.get(reason, 0) + count
    return totals


def _format_reason_summary(reason_totals: dict[str, int], label: str) -> str:
    parts = [f"{label}({reason})={count}" for reason, count in sorted(reason_totals.items())]
    return ", ".join(parts)


def _classify_exception(exc: Exception) -> str:
    if isinstance(exc, FileNotFoundError):
        return REASON_CODES["missing_file"]
    if isinstance(exc, PermissionError):
        return REASON_CODES["permission_denied"]
    if isinstance(exc, sqlite3.Error):
        return REASON_CODES["db_error"]
    if isinstance(exc, ValueError):
        return REASON_CODES["parse_error"]
    if isinstance(exc, OSError):
        return REASON_CODES["io_error"]
    return REASON_CODES["unknown_error"]


def _log_issue(
    level: str,
    step: str,
    reason: str,
    message: str,
    *,
    exc: Exception | None = None,
) -> None:
    msg = f"[{step}][{reason}] {message}"
    if level == "info":
        logger.info(msg)
    elif level == "warning":
        logger.warning(msg)
    else:
        logger.error(msg, exc_info=exc is not None)


def _safe_unique_path(base_dir: Path, filename: str) -> Path:
    target = base_dir / filename
    if not target.exists():
        return target
    stem, ext = os.path.splitext(filename)
    i = 1
    while True:
        cand = base_dir / f"{stem}_{i}{ext}"
        if not cand.exists():
            return cand
        i += 1


def _prune_db_backups(backup_dir: Path, stem: str, suffix: str, max_backups: int) -> None:
    if max_backups <= 0:
        return

    try:
        backups = sorted(
            [p for p in backup_dir.glob(f"{stem}_*{suffix}") if p.is_file()],
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
    except Exception as e:
        logger.warning("⚠️ DB 백업 목록 확인 실패(%s): %s", backup_dir, e)
        return

    for stale in backups[max_backups:]:
        try:
            stale.unlink()
            logger.info("🧹 오래된 DB 백업 삭제: %s", stale)
        except Exception as e:
            logger.warning("⚠️ 오래된 DB 백업 삭제 실패(%s): %s", stale, e)


def _maybe_call(cb, **payload):
    if not cb:
        return
    try:
        cb(**payload)
    except Exception:
        logger.debug("progress_cb 호출 중 무시 가능한 예외 발생", exc_info=True)


def _ensure_not_cancelled(cancel_event):
    if cancel_event and cancel_event.is_set():
        raise RefreshCancelled("사용자에 의해 취소됨")


def _process_image_for_scan(img: Path, dest: Path, date_folder: Path, cancel_event):
    _ensure_not_cancelled(cancel_event)
    info, failure_reason = extract_prompt_with_reason(img)
    _ensure_not_cancelled(cancel_event)
    if info:
        return {
            "info": info,
            "moved": 0,
            "move_failed": False,
            "move_reason": None,
            "extract_failure_reason": None,
        }

    failed_root = dest / "failed" / date_folder.name
    failed_root.mkdir(parents=True, exist_ok=True)
    target = _safe_unique_path(failed_root, f"{img.stem}(failed_PM){img.suffix}")
    try:
        shutil.move(img.as_posix(), target.as_posix())
        remove_image_from_db(rel_under_dest(dest, img))
        logger.info("🚫 메타데이터 없음 → failed 이동: %s", img.name)
        return {
            "info": None,
            "moved": 1,
            "move_failed": False,
            "move_reason": None,
            "extract_failure_reason": failure_reason,
        }
    except Exception as e:
        reason = _classify_exception(e)
        _log_issue("warning", "이동", reason, f"failed 이동 실패: {img.name} ({e})")
        logger.debug("failed 이동 실패 상세(%s)", img, exc_info=True)
        return {
            "info": None,
            "moved": 0,
            "move_failed": True,
            "move_reason": reason,
            "extract_failure_reason": failure_reason,
        }


def _process_failed_image(img: Path, dest: Path, date_folder: Path, cancel_event):
    _ensure_not_cancelled(cancel_event)
    info = extract_prompt_from_file(img)
    _ensure_not_cancelled(cancel_event)
    if not info:
        return {
            "info": None,
            "restored": False,
            "restore_failed": False,
            "restore_reason": None,
        }

    normal_dir = get_media_root(dest, date_folder.name, 'images', create=True)
    clean_name = f"{img.name.split('(failed')[0]}{img.suffix}"
    target = _safe_unique_path(normal_dir, clean_name)
    try:
        shutil.move(img.as_posix(), target.as_posix())
        info = extract_prompt_from_file(target)
        if info:
            logger.info("♻️ failed 복구: %s", target.name)
            return {
                "info": info,
                "restored": True,
                "restore_failed": False,
                "restore_reason": None,
            }
    except Exception as e:
        reason = _classify_exception(e)
        _log_issue("warning", "복구", reason, f"failed 복구 실패: {img.name} ({e})")
        logger.debug("failed 복구 실패 상세(%s)", img, exc_info=True)
        return {
            "info": None,
            "restored": False,
            "restore_failed": True,
            "restore_reason": reason,
        }

    return {
        "info": None,
        "restored": False,
        "restore_failed": False,
        "restore_reason": None,
    }


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


def _optimal_workers(task_count: int) -> int:
    if task_count <= 1:
        return 1
    cpu = os.cpu_count() or 4
    return max(1, min(32, task_count, cpu * 4))


def _restore_failed_images(
    *,
    dest: Path,
    cancel_event,
    progress_cb=None,
    progress_start: float = 0,
    progress_end: float = 100,
    remaining_steps: list[str] | None = None,
    counters: dict[str, dict[str, object]] | None = None,
) -> dict[str, object]:
    def report(progress: float, detail: str):
        _maybe_call(
            progress_cb,
            progress=progress,
            stage="failed 복구",
            detail=detail,
            remaining_steps=list(remaining_steps) if remaining_steps is not None else [],
        )

    _ensure_not_cancelled(cancel_event)
    report(progress_start, "failed 폴더 복구 시도")

    total_failed = 0
    processed_failed = 0
    restored_from_failed = 0
    failed_restore_failures = 0
    skipped_missing = 0
    restored_items: list[dict] = []
    failed_dir = dest / "failed"
    if failed_dir.exists():
        failed_candidates: dict[Path, list[Path]] = {}
        for date_folder in sorted(p for p in failed_dir.iterdir() if p.is_dir()):
            _ensure_not_cancelled(cancel_event)
            candidates = []
            for img in _iter_image_candidates(date_folder):
                parser = _get_prompt_parser(img.suffix)
                if not parser:
                    if counters is not None:
                        _bump_counter(
                            counters, "복구", "skip", REASON_CODES["unsupported_format"]
                        )
                    logger.info(
                        "지원하지 않는 포맷으로 failed 복구 스킵: %s (%s)",
                        img.name,
                        img.suffix,
                    )
                    continue
                candidates.append(img)
            if candidates:
                failed_candidates[date_folder] = candidates

        total_failed = sum(len(v) for v in failed_candidates.values())
        if total_failed:
            worker_count = _optimal_workers(total_failed)
            with ThreadPoolExecutor(max_workers=worker_count) as executor:
                future_to_item = {}
                for date_folder, imgs in failed_candidates.items():
                    for img in imgs:
                        fut = executor.submit(
                            _process_failed_image, img, dest, date_folder, cancel_event
                        )
                        future_to_item[fut] = (date_folder, img)

                for future in as_completed(future_to_item):
                    _ensure_not_cancelled(cancel_event)
                    date_folder, img = future_to_item[future]
                    try:
                        result = future.result()
                    except Exception as e:
                        failed_restore_failures += 1
                        processed_failed += 1
                        reason = _classify_exception(e)
                        if counters is not None:
                            _bump_counter(counters, "복구", "fail", reason)
                        _log_issue(
                            "warning",
                            "복구",
                            reason,
                            f"failed 복구 실패: {img.name} ({e})",
                        )
                        logger.debug("failed 복구 실패 상세(%s)", img, exc_info=True)
                        progress = progress_start + (
                            (processed_failed / total_failed) * (progress_end - progress_start)
                        )
                        report(progress, f"{img.name} 복구 실패: {e}")
                        continue
                    processed_failed += 1
                    info = result.get("info")
                    restore_failed = result.get("restore_failed")
                    restore_reason = result.get("restore_reason")
                    if info:
                        restored_items.append(info)
                    if result.get("restored"):
                        restored_from_failed += 1
                        if counters is not None:
                            _bump_counter(counters, "복구", "success")
                    elif restore_failed:
                        failed_restore_failures += 1
                        if counters is not None:
                            _bump_counter(counters, "복구", "fail", restore_reason)
                    else:
                        skipped_missing += 1
                        if counters is not None:
                            _bump_counter(
                                counters, "복구", "skip", REASON_CODES["metadata_missing"]
                            )

                    progress = progress_start + (
                        (processed_failed / total_failed) * (progress_end - progress_start)
                    )
                    report(
                        progress,
                        f"failed 복구 {processed_failed}/{total_failed}",
                    )

            if failed_restore_failures:
                logger.info("failed 복구 실패 건수: %d", failed_restore_failures)

    failed_detail = "failed 복구 완료"
    if total_failed:
        failed_detail = (
            f"failed 복구 완료 (실패 {failed_restore_failures}건)"
            if failed_restore_failures
            else "failed 복구 완료"
        )

    report(progress_end, failed_detail)
    return {
        "total_failed": total_failed,
        "processed_failed": processed_failed,
        "restored_from_failed": restored_from_failed,
        "failed_restore_failures": failed_restore_failures,
        "skipped_missing": skipped_missing,
        "restored_items": restored_items,
    }


def recover_failed_only(progress_cb=None, cancel_event=None) -> dict[str, object]:
    steps = ["failed 복구"]
    counters = _init_step_counters(["복구"])

    def report(progress: float, stage: str, detail: str | None = None, summary=None):
        _maybe_call(
            progress_cb,
            progress=progress,
            stage=stage,
            detail=detail or stage,
            remaining_steps=[],
            summary=summary,
        )

    dest = Path(DEST)
    scan_root = get_content_root(dest)
    if not dest.exists():
        report(100, "종료", "DEST 경로가 존재하지 않아 작업을 종료합니다.")
        return {
            "total_failed": 0,
            "restored_from_failed": 0,
            "failed_restore_failures": 0,
            "skipped_missing": 0,
        }

    report(5, "failed 복구", "failed 복구 준비", summary=None)
    result = _restore_failed_images(
        dest=dest,
        cancel_event=cancel_event,
        progress_cb=progress_cb,
        progress_start=5,
        progress_end=95,
        remaining_steps=steps,
        counters=counters,
    )

    restored_items = result.get("restored_items") or []
    if restored_items:
        save_tags_to_db(restored_items)

    fail_reason_totals = _merge_reason_totals(counters, "fail")
    skip_reason_totals = _merge_reason_totals(counters, "skip")
    summary_payload = {
        "steps": counters,
        "reasons": {"fail": fail_reason_totals, "skip": skip_reason_totals},
    }
    report(100, "완료", "failed 복구 완료", summary=summary_payload)
    result_summary = {
        "total_failed": result.get("total_failed", 0),
        "restored_from_failed": result.get("restored_from_failed", 0),
        "failed_restore_failures": result.get("failed_restore_failures", 0),
        "skipped_missing": result.get("skipped_missing", 0),
        "summary": summary_payload,
    }
    return result_summary


def run_db_backup(progress_cb=None, log_cb=None, cancel_event=None) -> dict[str, object]:
    def emit_progress(progress: float, message: str, summary: dict | None = None) -> None:
        if progress_cb:
            progress_cb(progress=progress, message=message, summary=summary)

    def emit_log(message: str) -> None:
        if log_cb:
            log_cb(message)
        else:
            logger.info(message)

    db_path = Path(DB_PATH)
    backup_dir = Path(DB_BACKUP_DIR) if DB_BACKUP_DIR else Path(DEST) / "db_backups"
    if not db_path.exists():
        emit_log(f"DB 파일이 없어 백업을 건너뜁니다: {db_path}")
        emit_progress(100, "DB 파일 없음 - 백업 건너뜀", summary={"status": "skipped"})
        return {"status": "ok", "message": "DB 백업 건너뜀", "summary": {"skipped": True}}

    emit_progress(5, "DB 백업 준비 중")
    _ensure_not_cancelled(cancel_event)
    try:
        backup_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_target = _safe_unique_path(
            backup_dir, f"{db_path.stem}_{timestamp}{db_path.suffix}"
        )

        wal_file = Path(f"{db_path}-wal")
        shm_file = Path(f"{db_path}-shm")
        with sqlite3.connect(db_path.as_posix()) as source:
            try:
                journal_mode = source.execute("PRAGMA journal_mode").fetchone()
                journal_mode = journal_mode[0] if journal_mode else "unknown"
            except Exception:
                journal_mode = "unknown"

            if str(journal_mode).lower() == "wal":
                try:
                    checkpoint_result = source.execute(
                        "PRAGMA wal_checkpoint(PASSIVE)"
                    ).fetchone()
                    emit_log(f"🧩 WAL checkpoint 진행(journal_mode=WAL): {checkpoint_result}")
                except Exception as e:
                    logger.warning("⚠️ WAL checkpoint 실패: %s", e)

            with sqlite3.connect(backup_target.as_posix()) as dest_conn:
                source.backup(dest_conn)

        _prune_db_backups(backup_dir, db_path.stem, db_path.suffix, MAX_DB_BACKUPS)
        emit_log(f"💾 DB 백업 생성: {backup_target}")
        summary = {"backup_path": backup_target.as_posix(), "journal_mode": journal_mode}
        emit_progress(100, "DB 백업 완료", summary=summary)
        return {"status": "ok", "message": "DB 백업 완료", "summary": summary}
    except Exception as e:
        emit_log(f"❌ DB 백업 실패: {e}")
        emit_progress(100, f"DB 백업 실패: {e}", summary={"error": str(e)})
        return {"status": "failed", "message": f"DB 백업 실패: {e}", "error": str(e)}


def run_image_scan(
    progress_cb=None,
    log_cb=None,
    cancel_event=None,
    *,
    force_rescan: bool = False,
) -> dict[str, object]:
    def emit_progress(progress: float, message: str, summary: dict | None = None) -> None:
        if progress_cb:
            progress_cb(progress=progress, message=message, summary=summary)

    def emit_log(message: str) -> None:
        if log_cb:
            log_cb(message)
        else:
            logger.info(message)

    dest = Path(DEST)
    scan_root = get_content_root(dest)
    if not dest.exists():
        emit_progress(100, "DEST 경로가 존재하지 않아 작업을 종료합니다.")
        return {"status": "failed", "message": "DEST 경로가 존재하지 않습니다.", "error": "DEST not found"}

    counters = _init_step_counters(["스캔", "이동"])
    emit_progress(5, "이미지 스캔 준비 중")
    _ensure_not_cancelled(cancel_event)

    refreshed = 0
    skipped_existing = 0
    moved_to_failed = 0
    scan_failures = 0
    reparse_success = 0
    reparse_fail = 0

    existing_files: set[str] = set()
    metadata_missing_files: set[str] = set()
    metadata_missing_reason_counts: Counter[str] = Counter()
    extract_failure_reasons: Counter[str] = Counter()
    if force_rescan:
        emit_log("🔁 강제 재스캔 활성화: 기존 인덱스/메타데이터 상태와 무관하게 큐에 추가합니다.")
    else:
        try:
            with sqlite3.connect(DB_PATH) as conn:
                cur = conn.cursor()
                cur.execute("SELECT DISTINCT image_id FROM loras")
                lora_image_ids = {row[0] for row in cur.fetchall() if row[0] is not None}
                cur.execute(
                    """
                    SELECT id, file, positive, negative, width, height, seed,
                           sampler, steps, cfg
                    FROM images
                    """
                )
                for row in cur.fetchall():
                    image_id, file, *_ = row
                    existing_files.add(file)
                    if _should_rescan_metadata(
                        row, lora_image_ids, METADATA_MISSING_EXTENDED_CHECKS
                    ):
                        metadata_missing_files.add(file)
                        reasons = _metadata_missing_reasons(
                            row, lora_image_ids, METADATA_MISSING_EXTENDED_CHECKS
                        )
                        metadata_missing_reason_counts.update(reasons)
        except Exception as e:
            existing_files = set()
            metadata_missing_files = set()
            reason = _classify_exception(e)
            _log_issue("warning", "스캔", reason, f"DB 이미지 목록 사전 로드 실패: {e}")
            logger.debug("DB 이미지 목록 사전 로드 실패 상세", exc_info=True)
        if metadata_missing_reason_counts:
            detail = ", ".join(
                f"{key}={count}" for key, count in sorted(metadata_missing_reason_counts.items())
            )
        else:
            detail = "없음"
        emit_log(f"📊 메타데이터 누락 기준별 카운트: {detail}")

    emit_progress(10, "정상 폴더 스캔 시작")
    candidates_by_folder: dict[Path, list[Path]] = {}
    metadata_rescan_planned = 0
    metadata_missing_not_found = set(metadata_missing_files)
    for date_folder in sorted(
        p for p in scan_root.iterdir()
        if p.is_dir() and DATE_FOLDER_PATTERN.fullmatch(p.name)
    ):
        _ensure_not_cancelled(cancel_event)
        folder_candidates = []
        for img in _iter_image_candidates(date_folder):
            _ensure_not_cancelled(cancel_event)
            parser = _get_prompt_parser(img.suffix)
            if not parser:
                _bump_counter(counters, "스캔", "skip", REASON_CODES["unsupported_format"])
                emit_log(
                    f"파일은 존재하지만 대상 확장자 제외: {img.name} ({img.suffix})"
                )
                continue
            rel_file = f"{dest.name}/{img.relative_to(dest).as_posix()}"
            if not force_rescan:
                if rel_file in existing_files and rel_file not in metadata_missing_files:
                    skipped_existing += 1
                    _bump_counter(counters, "스캔", "skip", REASON_CODES["already_indexed"])
                    emit_log(f"이미 인덱싱됨 + 메타 누락 아님: {img.name}")
                    continue
                if rel_file in metadata_missing_files:
                    metadata_rescan_planned += 1
                    metadata_missing_not_found.discard(rel_file)
                    emit_log(f"메타 누락으로 재스캔 큐에 추가됨: {img.name}")
            folder_candidates.append(img)

        if folder_candidates:
            candidates_by_folder[date_folder] = folder_candidates
        else:
            emit_log(f"No indexable images in {date_folder.name}")

    if metadata_missing_files and not force_rescan:
        emit_log(
            "📌 메타데이터 누락 감지: 총 %d건 중 %d건을 재스캔 큐에 추가, 파일 미발견 %d건"
            % (
                len(metadata_missing_files),
                metadata_rescan_planned,
                len(metadata_missing_not_found),
            )
        )

    total_candidates = sum(len(v) for v in candidates_by_folder.values())
    processed_candidates = 0
    items_by_folder: dict[Path, list[dict]] = {}
    if total_candidates:
        worker_count = _optimal_workers(total_candidates)
        with ThreadPoolExecutor(max_workers=worker_count) as executor:
            future_to_item: dict = {}
            for date_folder, imgs in candidates_by_folder.items():
                for img in imgs:
                    fut = executor.submit(
                        _process_image_for_scan, img, dest, date_folder, cancel_event
                    )
                    future_to_item[fut] = (date_folder, img)

            for future in as_completed(future_to_item):
                _ensure_not_cancelled(cancel_event)
                date_folder, img = future_to_item[future]
                try:
                    result = future.result()
                except Exception as e:
                    scan_failures += 1
                    processed_candidates += 1
                    reparse_fail += 1
                    reason = _classify_exception(e)
                    _bump_counter(counters, "스캔", "fail", reason)
                    _log_issue(
                        "warning",
                        "스캔",
                        reason,
                        f"이미지 스캔 실패: {img.name} ({e})",
                    )
                    logger.debug("이미지 스캔 실패 상세(%s)", img, exc_info=True)
                    progress = 10 + (processed_candidates / total_candidates) * 80
                    emit_progress(progress, f"{img.name} 처리 실패: {e}")
                    continue

                processed_candidates += 1
                moved_to_failed += result.get("moved", 0)
                info = result.get("info")
                move_failed = result.get("move_failed")
                move_reason = result.get("move_reason")
                extract_failure_reason = result.get("extract_failure_reason")
                if info:
                    items_by_folder.setdefault(date_folder, []).append(info)
                    _bump_counter(counters, "스캔", "success")
                    reparse_success += 1
                else:
                    _bump_counter(
                        counters, "스캔", "skip", REASON_CODES["metadata_missing"]
                    )
                    reparse_fail += 1
                    if extract_failure_reason:
                        extract_failure_reasons[extract_failure_reason] += 1
                if move_failed:
                    _bump_counter(counters, "이동", "fail", move_reason)
                elif result.get("moved"):
                    _bump_counter(counters, "이동", "success")

                progress = 10 + (processed_candidates / total_candidates) * 80
                emit_progress(
                    progress,
                    f"이미지 스캔 {processed_candidates}/{total_candidates}",
                )

        total_save_items = sum(len(items) for items in items_by_folder.values())
        saved_items = 0
        if total_save_items:
            emit_progress(90, f"스캔 결과 저장 중 0/{total_save_items}")
        for folder, items in items_by_folder.items():
            if not items:
                continue
            emit_progress(
                90 + (saved_items / total_save_items) * 10 if total_save_items else 90,
                f"스캔 결과 저장 중 {saved_items}/{total_save_items}",
            )
            save_tags_to_db(items)
            _auto_tag_items(items)
            saved_items += len(items)
            emit_progress(
                90 + (saved_items / total_save_items) * 10 if total_save_items else 100,
                f"스캔 결과 저장 중 {saved_items}/{total_save_items}",
            )
            refreshed += 1
        if scan_failures:
            emit_log(f"이미지 스캔 실패 건수: {scan_failures}")
        if extract_failure_reasons:
            detail = ", ".join(
                f"{reason}={count}"
                for reason, count in sorted(extract_failure_reasons.items())
            )
            emit_log(f"🧾 extract_prompt_from_file 실패 원인별 카운트: {detail}")

    if skipped_existing:
        emit_log(f"이미 인덱싱되어 건너뛴 이미지 수: {skipped_existing}")

    fail_reason_totals = _merge_reason_totals(counters, "fail")
    skip_reason_totals = _merge_reason_totals(counters, "skip")
    emit_log(
        "📌 스캔 요약: 대상 %d건 / 강제 재스캔 %s / 스킵 사유 %s / 재파싱 성공 %d건 / 실패 %d건"
        % (
            total_candidates,
            force_rescan,
            skip_reason_totals,
            reparse_success,
            reparse_fail,
        )
    )
    summary = {
        "refreshed_folders": refreshed,
        "moved_to_failed": moved_to_failed,
        "scan_failures": scan_failures,
        "skipped_existing": skipped_existing,
        "scan_targets": total_candidates,
        "reparse_success": reparse_success,
        "reparse_fail": reparse_fail,
        "force_rescan": force_rescan,
        "steps": counters,
        "reasons": {"fail": fail_reason_totals, "skip": skip_reason_totals},
    }
    emit_progress(100, "이미지 스캔 완료", summary=summary)
    return {"status": "ok", "message": "이미지 스캔 완료", "summary": summary}


def run_failed_recovery(progress_cb=None, log_cb=None, cancel_event=None) -> dict[str, object]:
    def emit_log(message: str) -> None:
        if log_cb:
            log_cb(message)
        else:
            logger.info(message)

    def wrap_progress(**payload) -> None:
        if not progress_cb:
            return
        message = payload.get("detail") or payload.get("stage") or "failed 복구 진행 중"
        progress_cb(
            progress=float(payload.get("progress", 0)),
            message=message,
            summary=payload.get("summary"),
        )

    emit_log("failed 복구 작업을 시작합니다.")
    result = recover_failed_only(progress_cb=wrap_progress, cancel_event=cancel_event)
    summary = result.get("summary") if isinstance(result, dict) else None
    return {
        "status": "ok",
        "message": "failed 복구 완료",
        "summary": summary or result,
    }


def run_image_cleanup(progress_cb=None, log_cb=None, cancel_event=None) -> dict[str, object]:
    def emit_progress(progress: float, message: str, summary: dict | None = None) -> None:
        if progress_cb:
            progress_cb(progress=progress, message=message, summary=summary)

    def emit_log(message: str) -> None:
        if log_cb:
            log_cb(message)
        else:
            logger.info(message)

    if not DB_PATH or not Path(DB_PATH).exists():
        emit_progress(100, "DB 파일이 없어 이미지 정리를 건너뜁니다.")
        return {"status": "failed", "message": "DB 파일이 존재하지 않습니다.", "error": "DB not found"}

    emit_progress(5, "DB 내 오래된 이미지 확인 중")
    stale_images_removed = 0
    try:
        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()
        cur.execute("SELECT file FROM images")
        db_files = [row[0] for row in cur.fetchall()]
        conn.close()
    except Exception as e:
        reason = _classify_exception(e)
        _log_issue("warning", "이미지 정리", reason, f"DB 이미지 목록 조회 실패: {e}")
        logger.debug("DB 이미지 목록 조회 실패 상세", exc_info=True)
        db_files = []

    total_files = len(db_files) or 1
    for idx, f in enumerate(db_files, start=1):
        _ensure_not_cancelled(cancel_event)
        rel = str(f).replace("\\", "/")
        for prefix in (f"{DEST_FOLDER_NAME}/", "Sorted_by_Date/"):
            if rel.startswith(prefix):
                rel = rel[len(prefix):]
        abs_path = os.path.join(DEST, rel)
        if not os.path.exists(abs_path):
            try:
                remove_image_from_db(f)
                stale_images_removed += 1
                emit_log(f"🗑️ Removed stale DB entry for {f}")
            except Exception as e:
                reason = _classify_exception(e)
                _log_issue(
                    "warning", "이미지 정리", reason, f"DB 항목 삭제 실패: {f} ({e})"
                )
                logger.debug("DB 항목 삭제 실패 상세(%s)", f, exc_info=True)
        progress = min(99, (idx / total_files) * 100)
        emit_progress(progress, f"이미지 정리 {idx}/{total_files}")

    summary = {"stale_images_removed": stale_images_removed}
    emit_progress(100, "이미지 정리 완료", summary=summary)
    return {"status": "ok", "message": "이미지 정리 완료", "summary": summary}


def run_video_index(progress_cb=None, log_cb=None, cancel_event=None) -> dict[str, object]:
    def emit_progress(progress: float, message: str, summary: dict | None = None) -> None:
        if progress_cb:
            progress_cb(progress=progress, message=message, summary=summary)

    def emit_log(message: str) -> None:
        if log_cb:
            log_cb(message)
        else:
            logger.info(message)

    emit_progress(5, "영상 인덱싱 준비 중")
    _ensure_not_cancelled(cancel_event)
    ensure_videos_table()
    try:
        video_indexed = bulk_upsert_from_dest()
        emit_log(f"영상 인덱싱 완료: {video_indexed}건")
        summary = {"video_indexed": video_indexed}
        emit_progress(100, "영상 인덱스 완료", summary=summary)
        return {"status": "ok", "message": "영상 인덱스 완료", "summary": summary}
    except Exception as e:
        emit_log(f"영상 인덱싱 실패: {e}")
        emit_progress(100, f"영상 인덱싱 실패: {e}", summary={"error": str(e)})
        return {"status": "failed", "message": f"영상 인덱스 실패: {e}", "error": str(e)}


def run_video_cleanup(progress_cb=None, log_cb=None, cancel_event=None) -> dict[str, object]:
    def emit_progress(progress: float, message: str, summary: dict | None = None) -> None:
        if progress_cb:
            progress_cb(progress=progress, message=message, summary=summary)

    def emit_log(message: str) -> None:
        if log_cb:
            log_cb(message)
        else:
            logger.info(message)

    if not DB_PATH or not Path(DB_PATH).exists():
        emit_progress(100, "DB 파일이 없어 영상 정리를 건너뜁니다.")
        return {"status": "failed", "message": "DB 파일이 존재하지 않습니다.", "error": "DB not found"}

    emit_progress(5, "DB 내 오래된 영상 확인 중")
    try:
        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()
        cur.execute("SELECT rel_video, rel_thumb FROM videos")
        db_videos = cur.fetchall()
        conn.close()
    except Exception as e:
        reason = _classify_exception(e)
        _log_issue("warning", "영상 정리", reason, f"영상 목록 조회 실패: {e}")
        logger.debug("영상 목록 조회 실패 상세", exc_info=True)
        db_videos = []

    cleaned_videos = 0
    total_videos = len(db_videos) or 1
    for idx, (rel_video, rel_thumb) in enumerate(db_videos, start=1):
        _ensure_not_cancelled(cancel_event)
        abs_video = os.path.join(DEST, rel_video)
        if not os.path.exists(abs_video):
            try:
                remove_video_from_db(rel_video)
                cleaned_videos += 1
                emit_log(f"🗑️ Removed stale video DB entry for {rel_video}")
            except Exception as e:
                reason = _classify_exception(e)
                _log_issue(
                    "warning",
                    "영상 정리",
                    reason,
                    f"영상 DB 항목 삭제 실패: {rel_video} ({e})",
                )
                logger.debug("영상 DB 항목 삭제 실패 상세(%s)", rel_video, exc_info=True)
        progress = min(99, (idx / total_videos) * 100)
        emit_progress(progress, f"영상 정리 {idx}/{total_videos}")

    summary = {"cleaned_videos": cleaned_videos}
    emit_progress(100, "영상 정리 완료", summary=summary)
    return {"status": "ok", "message": "영상 정리 완료", "summary": summary}


def run_orphan_cleanup(
    *,
    include_videos: bool = True,
    progress_cb=None,
    log_cb=None,
    cancel_event=None,
) -> dict[str, object]:
    def emit_progress(progress: float, message: str, summary: dict | None = None) -> None:
        if progress_cb:
            progress_cb(progress=progress, message=message, summary=summary)

    def emit_log(message: str) -> None:
        if log_cb:
            log_cb(message)
        else:
            logger.info(message)

    def map_progress(start: float, end: float):
        span = end - start

        def _mapped(progress: float, message: str, summary: dict | None = None) -> None:
            scaled = start + (progress / 100) * span
            emit_progress(scaled, message)

        return _mapped

    emit_log("고아 데이터 정리 작업을 시작합니다.")
    summary: dict[str, object] = {
        "stale_images_removed": 0,
        "cleaned_videos": 0,
        "include_videos": include_videos,
        "sample_items": [],
    }

    image_result = run_image_cleanup(
        progress_cb=map_progress(0, 50),
        log_cb=log_cb,
        cancel_event=cancel_event,
    )
    image_summary = image_result.get("summary") or {}
    stale_images_removed = int(image_summary.get("stale_images_removed") or 0)
    summary["stale_images_removed"] = stale_images_removed
    summary["sample_items"].append(f"이미지 고아 데이터 제거: {stale_images_removed}건")

    video_result = None
    if include_videos:
        video_result = run_video_cleanup(
            progress_cb=map_progress(50, 100),
            log_cb=log_cb,
            cancel_event=cancel_event,
        )
        video_summary = video_result.get("summary") or {}
        cleaned_videos = int(video_summary.get("cleaned_videos") or 0)
        summary["cleaned_videos"] = cleaned_videos
        summary["sample_items"].append(f"영상 고아 데이터 제거: {cleaned_videos}건")
    else:
        summary["sample_items"].append("영상 고아 데이터 정리: 건너뜀")
        emit_progress(100, "영상 정리를 건너뜁니다.", summary=summary)

    errors = []
    if image_result.get("status") != "ok":
        errors.append(image_result.get("error") or image_result.get("message") or "이미지 정리 실패")
    if include_videos and video_result and video_result.get("status") != "ok":
        errors.append(video_result.get("error") or video_result.get("message") or "영상 정리 실패")

    emit_progress(100, "고아 데이터 정리 완료", summary=summary)
    if errors:
        return {
            "status": "failed",
            "message": "고아 데이터 정리 실패",
            "summary": summary,
            "error": "; ".join(errors),
        }
    return {"status": "ok", "message": "고아 데이터 정리 완료", "summary": summary}

def full_refresh(progress_cb=None, cancel_event=None, include_videos: bool = True) -> None:
    step_labels = [
        "백업",
        "스캔",
        "이동",
        "복구",
        "영상 인덱스",
        "썸네일 프리빌드",
    ]
    counters = _init_step_counters(step_labels)
    steps = [
        "DB 백업",
        "이미지 스캔",
        "failed 복구",
        "이미지 정리",
    ]
    if include_videos:
        steps.extend(["영상 인덱스", "영상 정리"])
    steps.append("썸네일 프리빌드")

    def report(
        progress: float,
        stage: str,
        detail: str | None = None,
        remaining=None,
        summary=None,
    ):
        _maybe_call(
            progress_cb,
            progress=progress,
            stage=stage,
            detail=detail or stage,
            remaining_steps=list(remaining) if remaining is not None else steps,
            summary=summary,
        )

    dest = Path(DEST)
    scan_root = get_content_root(dest)
    if not dest.exists():
        logger.warning("DEST not found. Nothing to refresh.")
        report(100, "종료", "DEST 경로가 존재하지 않아 작업을 종료합니다.")
        return

    db_path = Path(DB_PATH)
    backup_dir = Path(DB_BACKUP_DIR) if DB_BACKUP_DIR else dest / "db_backups"
    backup_created = None
    backup_error: Exception | None = None
    report(2, "준비", "DB 백업 준비", remaining=steps)
    _ensure_not_cancelled(cancel_event)
    if db_path.exists():
        try:
            backup_dir.mkdir(parents=True, exist_ok=True)
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            backup_target = _safe_unique_path(
                backup_dir, f"{db_path.stem}_{timestamp}{db_path.suffix}"
            )

            wal_file = Path(f"{db_path}-wal")
            shm_file = Path(f"{db_path}-shm")
            with sqlite3.connect(db_path.as_posix()) as source:
                try:
                    journal_mode = source.execute("PRAGMA journal_mode").fetchone()
                    journal_mode = journal_mode[0] if journal_mode else "unknown"
                except Exception:
                    journal_mode = "unknown"

                if str(journal_mode).lower() == "wal":
                    try:
                        checkpoint_result = source.execute(
                            "PRAGMA wal_checkpoint(PASSIVE)"
                        ).fetchone()
                        logger.info(
                            "🧩 WAL checkpoint 진행(journal_mode=WAL): %s", checkpoint_result
                        )
                    except Exception as e:
                        logger.warning("⚠️ WAL checkpoint 실패: %s", e)

                with sqlite3.connect(backup_target.as_posix()) as dest_conn:
                    source.backup(dest_conn)

            backup_created = backup_target
            logger.info(
                "💾 DB 백업 생성: %s (journal_mode=%s, wal=%s, shm=%s)",
                backup_target,
                journal_mode,
                wal_file.exists(),
                shm_file.exists(),
            )
            _bump_counter(counters, "백업", "success")
            report(10, "DB 백업", f"DB 백업 생성: {backup_target}", remaining=steps[1:])
        except Exception as e:
            backup_error = e
            reason = _classify_exception(e)
            _bump_counter(counters, "백업", "fail", reason)
            _log_issue("warning", "백업", reason, f"DB 백업 실패: {e}")
            logger.error(
                "❌ DB 백업 실패(%s): %s", backup_dir, e, exc_info=True
            )
            report(
                5,
                "오류",
                f"DB 백업 실패: {backup_dir} ({e}). 경로/권한을 확인하고 재시도하세요.",
                remaining=[],
            )
    else:
        logger.info("DB 파일이 없어 백업을 건너뜁니다: %s", db_path)
        _bump_counter(counters, "백업", "skip", REASON_CODES["no_db"])

    if db_path.exists() and not backup_created:
        detail = (
            "DB 백업을 생성하지 못해 전체 재정리를 중단합니다. "
            f"백업 경로: {backup_dir}. 경로/권한/디스크 공간을 확인한 뒤 다시 시도하세요."
        )
        if backup_error:
            detail += f" 오류: {backup_error}"
        logger.error(detail)
        report(5, "오류", detail, remaining=[])
        raise BackupFailed(detail)

    refreshed = 0
    skipped_existing = 0
    indexed_files = set()
    moved_to_failed = 0
    restored_from_failed = 0
    stale_images_removed = 0
    scan_failures = 0
    failed_restore_failures = 0

    existing_files: set[str] = set()
    metadata_missing_files: set[str] = set()
    try:
        with sqlite3.connect(DB_PATH) as conn:
            cur = conn.cursor()
            cur.execute("SELECT DISTINCT image_id FROM loras")
            lora_image_ids = {row[0] for row in cur.fetchall() if row[0] is not None}
            cur.execute(
                """
                SELECT id, file, positive, negative, width, height, seed,
                       sampler, steps, cfg
                FROM images
                """
            )
            for row in cur.fetchall():
                image_id, file, *_ = row
                existing_files.add(file)
                if _should_rescan_metadata(
                    row, lora_image_ids, METADATA_MISSING_EXTENDED_CHECKS
                ):
                    metadata_missing_files.add(file)
    except Exception as e:
        existing_files = set()
        metadata_missing_files = set()
        reason = _classify_exception(e)
        _log_issue("warning", "스캔", reason, f"DB 이미지 목록 사전 로드 실패: {e}")
        logger.debug("DB 이미지 목록 사전 로드 실패 상세", exc_info=True)

    _ensure_not_cancelled(cancel_event)
    report(15, "이미지 스캔", "정상 폴더 스캔 시작", remaining=steps[1:])
    # 1) 정상 폴더 스캔 + 실패 이미지 분리 (extract_prompt_from_file 병렬화)
    candidates_by_folder: dict[Path, list[Path]] = {}
    metadata_rescan_planned = 0
    metadata_missing_not_found = set(metadata_missing_files)
    for date_folder in sorted(
        p
        for p in scan_root.iterdir()
        if p.is_dir() and DATE_FOLDER_PATTERN.fullmatch(p.name)
    ):
        _ensure_not_cancelled(cancel_event)
        folder_candidates = []
        for img in _iter_image_candidates(date_folder):
            _ensure_not_cancelled(cancel_event)
            parser = _get_prompt_parser(img.suffix)
            if not parser:
                _bump_counter(counters, "스캔", "skip", REASON_CODES["unsupported_format"])
                logger.info(
                    "지원하지 않는 포맷 스킵: %s (%s)",
                    img.name,
                    img.suffix,
                )
                continue
            rel_file = f"{dest.name}/{img.relative_to(dest).as_posix()}"
            if rel_file in existing_files and rel_file not in metadata_missing_files:
                skipped_existing += 1
                _bump_counter(counters, "스캔", "skip", REASON_CODES["already_indexed"])
                continue
            if rel_file in metadata_missing_files:
                metadata_rescan_planned += 1
                metadata_missing_not_found.discard(rel_file)
            folder_candidates.append(img)

        if folder_candidates:
            candidates_by_folder[date_folder] = folder_candidates
        else:
            logger.info("No indexable images in %s", date_folder.name)

    if metadata_missing_files:
        logger.info(
            "📌 메타데이터 누락 감지: 총 %d건 중 %d건을 재스캔 큐에 추가, 파일 미발견 %d건",
            len(metadata_missing_files),
            metadata_rescan_planned,
            len(metadata_missing_not_found),
        )

    total_candidates = sum(len(v) for v in candidates_by_folder.values())
    processed_candidates = 0
    if total_candidates:
        items_by_folder: dict[Path, list[dict]] = {}
        worker_count = _optimal_workers(total_candidates)
        with ThreadPoolExecutor(max_workers=worker_count) as executor:
            future_to_item: dict = {}
            for date_folder, imgs in candidates_by_folder.items():
                for img in imgs:
                    fut = executor.submit(
                        _process_image_for_scan, img, dest, date_folder, cancel_event
                    )
                    future_to_item[fut] = (date_folder, img)

            for future in as_completed(future_to_item):
                _ensure_not_cancelled(cancel_event)
                date_folder, img = future_to_item[future]
                try:
                    result = future.result()
                except Exception as e:
                    scan_failures += 1
                    processed_candidates += 1
                    reason = _classify_exception(e)
                    _bump_counter(counters, "스캔", "fail", reason)
                    _log_issue(
                        "warning",
                        "스캔",
                        reason,
                        f"이미지 스캔 실패: {img.name} ({e})",
                    )
                    logger.debug("이미지 스캔 실패 상세(%s)", img, exc_info=True)
                    progress = 15 + (processed_candidates / total_candidates) * 25
                    report(
                        progress,
                        "이미지 스캔",
                        f"{img.name} 처리 실패: {e}",
                        remaining=steps[2:],
                    )
                    continue

                processed_candidates += 1
                moved_to_failed += result.get("moved", 0)
                info = result.get("info")
                move_failed = result.get("move_failed")
                move_reason = result.get("move_reason")
                if info:
                    items_by_folder.setdefault(date_folder, []).append(info)
                    if info.get("file"):
                        indexed_files.add(info["file"])
                    _bump_counter(counters, "스캔", "success")
                else:
                    _bump_counter(
                        counters, "스캔", "skip", REASON_CODES["metadata_missing"]
                    )
                if move_failed:
                    _bump_counter(counters, "이동", "fail", move_reason)
                elif result.get("moved"):
                    _bump_counter(counters, "이동", "success")

                progress = 15 + (processed_candidates / total_candidates) * 25
                report(
                    progress,
                    "이미지 스캔",
                    f"이미지 스캔 {processed_candidates}/{total_candidates}",
                    remaining=steps[2:],
                )

        for folder, items in items_by_folder.items():
            if items:
                save_tags_to_db(items)
                refreshed += 1
        if scan_failures:
            logger.info("이미지 스캔 실패 건수: %d", scan_failures)
    
    if skipped_existing:
        logger.info("이미 인덱싱되어 건너뛴 이미지 수: %d", skipped_existing)

    scan_detail = "폴더 스캔 완료"
    if total_candidates:
        scan_detail = f"폴더 스캔 완료 (실패 {scan_failures}건)" if scan_failures else "폴더 스캔 완료"

    report(40, "이미지 스캔", scan_detail, remaining=steps[2:])

    restore_result = _restore_failed_images(
        dest=dest,
        cancel_event=cancel_event,
        progress_cb=progress_cb,
        progress_start=45,
        progress_end=55,
        remaining_steps=steps[3:],
        counters=counters,
    )
    total_failed = int(restore_result.get("total_failed", 0) or 0)
    restored_items = restore_result.get("restored_items") or []
    if restored_items:
        save_tags_to_db(restored_items)
        _auto_tag_items(restored_items)
        for item in restored_items:
            if item.get("file"):
                indexed_files.add(item["file"])
    restored_from_failed += int(restore_result.get("restored_from_failed", 0) or 0)
    failed_restore_failures += int(restore_result.get("failed_restore_failures", 0) or 0)

    # Remove stale DB entries (files that no longer exist in DEST)
    _ensure_not_cancelled(cancel_event)
    report(60, "이미지 정리", "DB 내 오래된 이미지 확인", remaining=steps[3:])
    try:
        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()
        cur.execute("SELECT file FROM images")
        db_files = [row[0] for row in cur.fetchall()]
        conn.close()
    except Exception as e:
        reason = _classify_exception(e)
        _log_issue("warning", "이미지 정리", reason, f"DB 이미지 목록 조회 실패: {e}")
        logger.debug("DB 이미지 목록 조회 실패 상세", exc_info=True)
        db_files = []

    for f in db_files:
        _ensure_not_cancelled(cancel_event)
        rel = str(f).replace("\\", "/")
        for prefix in (f"{DEST_FOLDER_NAME}/", "Sorted_by_Date/"):
            if rel.startswith(prefix):
                rel = rel[len(prefix):]
        abs_path = os.path.join(DEST, rel)
        if not os.path.exists(abs_path):
            try:
                remove_image_from_db(f)
                stale_images_removed += 1
                logger.info("🗑️ Removed stale DB entry for %s", f)
            except Exception as e:
                reason = _classify_exception(e)
                _log_issue(
                    "warning", "이미지 정리", reason, f"DB 항목 삭제 실패: {f} ({e})"
                )
                logger.debug("DB 항목 삭제 실패 상세(%s)", f, exc_info=True)

    report(70, "이미지 정리", "이미지 정리 완료", remaining=steps[4:])

    video_indexed = 0
    cleaned_videos = 0
    if include_videos:
        ensure_videos_table()
        _ensure_not_cancelled(cancel_event)
        report(75, "영상 인덱스", "영상 재인덱싱 시작", remaining=steps[4:])
        try:
            video_indexed = bulk_upsert_from_dest()
            if video_indexed:
                _bump_counter(counters, "영상 인덱스", "success", count=video_indexed)
        except Exception as e:
            reason = _classify_exception(e)
            _bump_counter(counters, "영상 인덱스", "fail", reason)
            _log_issue("warning", "영상 인덱스", reason, f"영상 재인덱싱 실패: {e}")
            logger.debug("영상 재인덱싱 실패 상세", exc_info=True)

        _ensure_not_cancelled(cancel_event)
        report(85, "영상 정리", "DB 내 오래된 영상 확인", remaining=steps[5:])
        try:
            conn = sqlite3.connect(DB_PATH)
            cur = conn.cursor()
            cur.execute("SELECT rel_video, rel_thumb FROM videos")
            db_videos = cur.fetchall()
            conn.close()
        except Exception as e:
            reason = _classify_exception(e)
            _log_issue("warning", "영상 정리", reason, f"영상 목록 조회 실패: {e}")
            logger.debug("영상 목록 조회 실패 상세", exc_info=True)
            db_videos = []

        for rel_video, rel_thumb in db_videos:
            _ensure_not_cancelled(cancel_event)
            abs_video = os.path.join(DEST, rel_video)
            if not os.path.exists(abs_video):
                try:
                    remove_video_from_db(rel_video)
                    cleaned_videos += 1
                    logger.info("🗑️ Removed stale video DB entry for %s", rel_video)
                except Exception as e:
                    reason = _classify_exception(e)
                    _log_issue(
                        "warning",
                        "영상 정리",
                        reason,
                        f"영상 DB 항목 삭제 실패: {rel_video} ({e})",
                    )
                    logger.debug("영상 DB 항목 삭제 실패 상세(%s)", rel_video, exc_info=True)
    else:
        report(
            75,
            "영상 단계 건너뜀",
            "요청에 따라 영상 인덱싱과 정리를 건너뜁니다.",
            remaining=steps[4:],
        )
        _bump_counter(counters, "영상 인덱스", "skip", REASON_CODES["videos_excluded"])

    thumb_targets = set()
    for rel_path in indexed_files:
        normalized = normalize_thumb_rel_path(rel_path)
        if normalized:
            thumb_targets.add(normalized)

    if include_videos:
        for rel_video, rel_thumb in db_videos:
            if not rel_video:
                continue
            thumb_rel = rel_thumb or rel_video
            normalized = normalize_thumb_rel_path(thumb_rel)
            if normalized:
                thumb_targets.add(normalized)

    thumb_list = sorted(thumb_targets)
    thumb_total = len(thumb_list)
    thumb_created = 0
    thumb_skipped = 0
    thumb_missing = 0
    thumb_failed = 0
    thumb_progress_start = 90 if include_videos else 80
    thumb_progress_end = 98

    report(
        thumb_progress_start,
        "썸네일 프리빌드",
        f"썸네일 프리빌드 시작 ({thumb_total}건)",
        remaining=steps[-1:],
    )
    if thumb_total:
        for idx, rel_path in enumerate(thumb_list, start=1):
            _ensure_not_cancelled(cancel_event)
            abs_path = os.path.join(DEST, rel_path)
            if not os.path.exists(abs_path):
                thumb_missing += 1
                _bump_counter(
                    counters, "썸네일 프리빌드", "skip", REASON_CODES["missing_file"]
                )
            else:
                thumb_path = build_thumb_cache_path(rel_path)
                if thumb_cache_is_fresh(thumb_path, abs_path):
                    thumb_skipped += 1
                    _bump_counter(
                        counters, "썸네일 프리빌드", "skip", REASON_CODES["cache_fresh"]
                    )
                else:
                    try:
                        generate_thumbnail(abs_path, thumb_path)
                        thumb_created += 1
                        _bump_counter(counters, "썸네일 프리빌드", "success")
                    except Exception as e:
                        thumb_failed += 1
                        reason = _classify_exception(e)
                        _bump_counter(counters, "썸네일 프리빌드", "fail", reason)
                        _log_issue(
                            "warning",
                            "썸네일 프리빌드",
                            reason,
                            f"썸네일 프리빌드 실패: {rel_path} ({e})",
                        )
                        logger.debug("썸네일 프리빌드 실패 상세(%s)", rel_path, exc_info=True)

            progress = thumb_progress_start
            if thumb_total:
                progress += (idx / thumb_total) * (thumb_progress_end - thumb_progress_start)
            report(
                progress,
                "썸네일 프리빌드",
                f"썸네일 프리빌드 {idx}/{thumb_total}",
                remaining=steps[-1:],
            )

    report(
        thumb_progress_end,
        "썸네일 프리빌드",
        (
            "썸네일 프리빌드 완료"
            f" (생성 {thumb_created}, 건너뜀 {thumb_skipped}, 누락 {thumb_missing}, 실패 {thumb_failed})"
        ),
        remaining=steps[-1:],
    )

    logger.info(
        "🖼️ 썸네일 프리빌드 완료: 생성 %d, 건너뜀 %d, 누락 %d, 실패 %d",
        thumb_created,
        thumb_skipped,
        thumb_missing,
        thumb_failed,
    )

    if backup_created:
        _prune_db_backups(backup_dir, db_path.stem, db_path.suffix, MAX_DB_BACKUPS)

    completion_detail = "전체 재정리 완료"
    if scan_failures or failed_restore_failures:
        completion_detail += (
            f" (이미지 스캔 실패 {scan_failures}건, failed 복구 실패 {failed_restore_failures}건)"
        )

    fail_reason_totals = _merge_reason_totals(counters, "fail")
    skip_reason_totals = _merge_reason_totals(counters, "skip")
    reason_summaries = []
    if fail_reason_totals:
        reason_summaries.append(_format_reason_summary(fail_reason_totals, "실패"))
    if skip_reason_totals:
        reason_summaries.append(_format_reason_summary(skip_reason_totals, "스킵"))
    reason_summary_text = ", ".join(reason_summaries)

    summary_payload = {
        "steps": counters,
        "reasons": {"fail": fail_reason_totals, "skip": skip_reason_totals},
    }
    report(100, "완료", completion_detail, remaining=[], summary=summary_payload)

    logger.info(
        "전체 재정리 완료. 갱신된 날짜 폴더 수: %d, failed 이동: %d, failed 복구: %d, 이미지 정리: %d, 영상 인덱스: %d, 영상 정리: %d, 이미지 스캔 실패: %d, failed 복구 실패: %d%s",
        refreshed,
        moved_to_failed,
        restored_from_failed,
        stale_images_removed,
        video_indexed,
        cleaned_videos,
        scan_failures,
        failed_restore_failures,
        f", 사유별 집계: {reason_summary_text}" if reason_summary_text else "",
    )

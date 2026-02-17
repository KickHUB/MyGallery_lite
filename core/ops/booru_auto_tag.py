from __future__ import annotations

import logging
import os
import sqlite3
import time
from pathlib import Path
from typing import Any, Dict, List

from settings import DB_PATH, WD14_MODEL_PATH
from core.db.search_utils import ensure_image_tables, normalize_media_path
from core.booru.booru_dict import ensure_booru_tables
from core.booru.booru_item_tags import normalize_booru_tags
from core.tagging.wd14_tagger import AUTO_WD14_SOURCE, is_video_pair_image, tag_image
from core.utils.path_utils import resolve_dest_path

logger = logging.getLogger(__name__)

DEFAULT_BATCH_SIZE = 30
PROGRESS_EVERY = 20
ERROR_SAMPLE_LIMIT = 20


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


def _replace_item_tags_in_tx(
    cur: sqlite3.Cursor,
    media_type: str,
    media_path: str,
    tags: List[str],
    source: str,
) -> None:
    norm_tags = normalize_booru_tags(tags)
    cur.execute(
        "DELETE FROM booru_item_tags WHERE media_type=? AND media_path=? AND source=?",
        (media_type, media_path, source),
    )
    if not norm_tags:
        return
    rows = [(media_type, media_path, tag, source) for tag in norm_tags]
    cur.executemany(
        "INSERT INTO booru_item_tags (media_type, media_path, tag, source) VALUES (?, ?, ?, ?)",
        rows,
    )


def run_booru_auto_tag(
    *,
    force: bool = False,
    limit: int = 0,
    progress_cb=None,
    log_cb=None,
    cancel_event=None,
) -> Dict[str, Any]:
    if not WD14_MODEL_PATH or not Path(WD14_MODEL_PATH).exists():
        message = "WD14 모델 경로가 설정되지 않아 자동 태깅을 실행할 수 없습니다."
        _emit(message, log_cb)
        return {"status": "failed", "message": message, "error": message}

    ensure_image_tables()
    ensure_booru_tables()

    limit = max(0, int(limit or 0))
    force = bool(force)

    summary: Dict[str, Any] = {
        "source": AUTO_WD14_SOURCE,
        "force": force,
        "limit": limit,
        "total_images": 0,
        "target_total": 0,
        "processed": 0,
        "tagged": 0,
        "skipped_existing": 0,
        "skipped_video": 0,
        "missing": 0,
        "failed": 0,
        "duration_sec": 0,
        "sample_label": "자동 태깅 오류/누락 샘플",
        "sample_items": [],
    }
    error_samples: List[str] = summary["sample_items"]
    start_ts = time.time()

    def update_progress(message: str) -> None:
        if not progress_cb:
            return
        total = summary.get("target_total") or 0
        processed = summary.get("processed") or 0
        percent = 100 if total <= 0 else (processed / total) * 100
        progress_cb(percent, message, summary)

    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        update_cur = conn.cursor()

        cur.execute("SELECT COUNT(*) FROM images")
        total_images = int(cur.fetchone()[0] or 0)
        summary["total_images"] = total_images

        if force:
            target_total = total_images
        else:
            cur.execute(
                """
                SELECT COUNT(*)
                FROM images
                WHERE NOT EXISTS (
                    SELECT 1
                    FROM booru_item_tags
                    WHERE media_type='image'
                      AND media_path = images.file
                      AND source = ?
                )
                """,
                (AUTO_WD14_SOURCE,),
            )
            target_total = int(cur.fetchone()[0] or 0)
            summary["skipped_existing"] = max(0, total_images - target_total)

        if limit > 0:
            target_total = min(target_total, limit)

        summary["target_total"] = target_total

        if target_total <= 0:
            summary["duration_sec"] = round(time.time() - start_ts, 3)
            message = "자동 태깅 대상이 없습니다."
            return {"status": "ok", "message": message, "summary": summary}

        _emit(f"Danbooru 자동 태깅 시작: 대상 {target_total}건", log_cb)

        sql = "SELECT file FROM images"
        params: list[Any] = []
        if not force:
            sql += (
                " WHERE NOT EXISTS ("
                "SELECT 1 FROM booru_item_tags "
                "WHERE media_type='image' AND media_path = images.file AND source = ?)"
            )
            params.append(AUTO_WD14_SOURCE)
        if limit > 0:
            sql += " LIMIT ?"
            params.append(limit)
        cur.execute(sql, params)

        pending = 0
        for row in cur:
            if cancel_event is not None and cancel_event.is_set():
                _emit("Danbooru 자동 태깅이 취소되었습니다.", log_cb)
                break

            rel_path = row["file"] if row else ""
            rel_path = rel_path or ""
            media_path = normalize_media_path(rel_path)
            if not media_path:
                summary["missing"] += 1
                summary["processed"] += 1
                continue

            if is_video_pair_image(Path(media_path)):
                summary["skipped_video"] += 1
                summary["processed"] += 1
                continue

            abs_path = resolve_dest_path(media_path)
            if not abs_path or not os.path.isfile(abs_path):
                summary["missing"] += 1
                if len(error_samples) < ERROR_SAMPLE_LIMIT:
                    error_samples.append(f"missing: {media_path}")
                summary["processed"] += 1
                continue

            try:
                tags, rating_code = tag_image(abs_path)
            except Exception as exc:
                summary["failed"] += 1
                if len(error_samples) < ERROR_SAMPLE_LIMIT:
                    error_samples.append(f"failed: {media_path} ({_format_error(exc)})")
                summary["processed"] += 1
                continue

            _replace_item_tags_in_tx(
                update_cur,
                "image",
                media_path,
                tags,
                AUTO_WD14_SOURCE,
            )
            if rating_code is None:
                update_cur.execute(
                    "DELETE FROM booru_item_rating WHERE media_type=? AND media_path=? AND source=?",
                    ("image", media_path, AUTO_WD14_SOURCE),
                )
            else:
                update_cur.execute(
                    """
                    INSERT INTO booru_item_rating (media_type, media_path, rating, source)
                    VALUES (?, ?, ?, ?)
                    ON CONFLICT(media_type, media_path, source)
                    DO UPDATE SET rating=excluded.rating, updated_at=CURRENT_TIMESTAMP
                    """,
                    ("image", media_path, rating_code, AUTO_WD14_SOURCE),
                )

            summary["tagged"] += 1
            summary["processed"] += 1
            pending += 1

            if pending >= DEFAULT_BATCH_SIZE:
                conn.commit()
                pending = 0

            if summary["processed"] % PROGRESS_EVERY == 0:
                update_progress("Danbooru 자동 태깅 진행 중")

        if pending:
            conn.commit()

    summary["duration_sec"] = round(time.time() - start_ts, 3)
    update_progress("Danbooru 자동 태깅 완료")
    message = "Danbooru 자동 태깅 완료"
    _emit(message, log_cb)
    return {"status": "ok", "message": message, "summary": summary}

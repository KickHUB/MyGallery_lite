from __future__ import annotations

import logging
import os
import sqlite3
import time
from datetime import datetime
from typing import Any, Dict, Iterable, Optional

from settings import DB_PATH
from core.db.search_utils import ensure_image_tables, normalize_media_path
from core.media.video_index import ensure_videos_table
from core.db.phash_relations import ensure_phash_group_tables, clear_phash_groups
from core.utils.path_utils import resolve_dest_path

logger = logging.getLogger(__name__)

DEFAULT_DISTANCE = 12
PROGRESS_EVERY = 100


def _emit(message: str, log_cb=None) -> None:
    if log_cb:
        log_cb(message)
    else:
        logger.info(message)


def _phash_to_int(value: Optional[str]) -> Optional[int]:
    if not value:
        return None
    try:
        return int(str(value), 16)
    except (TypeError, ValueError):
        return None


def _hamming_distance(a: int, b: int) -> int:
    return (a ^ b).bit_count()


def _parse_date_to_ts(value: Optional[str]) -> Optional[float]:
    if not value:
        return None
    raw = str(value).strip()
    if not raw:
        return None
    try:
        cleaned = raw.replace("/", "-").replace("T", " ").replace("Z", "")
        return datetime.fromisoformat(cleaned).timestamp()
    except ValueError:
        return None


def _media_key(media_type: str, media_path: str) -> str:
    return f"{media_type}::{media_path}"


def _iter_group_choice(group_ids: Iterable[int], group_meta: Dict[int, Dict[str, Any]]) -> Optional[int]:
    best_id = None
    best_ts = None
    for gid in group_ids:
        meta = group_meta.get(gid)
        if not meta:
            continue
        ts = meta.get("base_ts")
        if best_id is None or (ts is not None and (best_ts is None or ts < best_ts)):
            best_id = gid
            best_ts = ts
    return best_id


def run_phash_group_build(
    *,
    distance: int = DEFAULT_DISTANCE,
    mode: str = "rebuild",
    include_images: bool = True,
    include_videos: bool = True,
    progress_cb=None,
    log_cb=None,
    cancel_event=None,
) -> Dict[str, Any]:
    distance = max(0, int(distance or DEFAULT_DISTANCE))
    mode = (mode or "rebuild").lower()
    if mode not in {"rebuild", "incremental"}:
        mode = "rebuild"

    ensure_image_tables()
    ensure_videos_table()
    ensure_phash_group_tables()

    summary: Dict[str, Any] = {
        "distance": distance,
        "mode": mode,
        "include_images": bool(include_images),
        "include_videos": bool(include_videos),
        "groups_created": 0,
        "items_added": 0,
        "items_skipped": 0,
        "sample_label": "pHash 연관관계 요약",
        "sample_items": [],
    }
    start = time.time()

    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()

        if mode == "rebuild":
            cleared = clear_phash_groups(conn=conn, cur=cur)
            if cleared:
                summary["groups_cleared"] = cleared
                _emit(f"기존 연관관계 {cleared}건 제거", log_cb)

        group_meta: Dict[int, Dict[str, Any]] = {}
        group_media: Dict[str, int] = {}
        if mode == "incremental":
            cur.execute("SELECT id, base_phash, base_ts FROM phash_groups")
            for row in cur.fetchall():
                group_meta[row["id"]] = {"base_phash": row["base_phash"], "base_ts": row["base_ts"]}
            cur.execute("SELECT group_id, media_type, media_path FROM phash_group_items")
            for row in cur.fetchall():
                group_media[_media_key(row["media_type"], row["media_path"])] = row["group_id"]

        items: list[Dict[str, Any]] = []
        paired_thumb_set: set[str] = set()
        if include_images:
            cur.execute("SELECT rel_thumb FROM videos WHERE rel_thumb IS NOT NULL AND rel_thumb != ''")
            for row in cur.fetchall():
                thumb_norm = normalize_media_path(row["rel_thumb"])
                if thumb_norm:
                    paired_thumb_set.add(thumb_norm)
        if include_images:
            cur.execute("SELECT file, date, phash FROM images WHERE phash IS NOT NULL AND phash != ''")
            for row in cur.fetchall():
                phash_int = _phash_to_int(row["phash"])
                if phash_int is None:
                    continue
                ts = _parse_date_to_ts(row["date"])
                if ts is None:
                    abs_path = resolve_dest_path(row["file"])
                    if abs_path:
                        try:
                            ts = float(os.path.getmtime(abs_path))
                        except OSError:
                            ts = 0.0
                    else:
                        ts = 0.0
                media_type = "image"
                if paired_thumb_set:
                    image_norm = normalize_media_path(row["file"])
                    if image_norm in paired_thumb_set:
                        media_type = "pair"
                items.append(
                    {
                        "media_type": media_type,
                        "media_path": row["file"],
                        "phash": row["phash"],
                        "phash_int": phash_int,
                        "ts": float(ts or 0.0),
                    }
                )
        if include_videos:
            cur.execute(
                "SELECT rel_video, date, mtime, phash FROM videos WHERE phash IS NOT NULL AND phash != ''"
            )
            for row in cur.fetchall():
                phash_int = _phash_to_int(row["phash"])
                if phash_int is None:
                    continue
                ts = _parse_date_to_ts(row["date"])
                if ts is None:
                    ts = float(row["mtime"] or 0.0)
                items.append(
                    {
                        "media_type": "video",
                        "media_path": row["rel_video"],
                        "phash": row["phash"],
                        "phash_int": phash_int,
                        "ts": float(ts or 0.0),
                    }
                )

        items.sort(key=lambda item: (item["ts"], item["media_path"]))
        total = len(items)
        processed: list[Dict[str, Any]] = []
        items_added = 0
        items_skipped = 0
        groups_created = 0

        def update_progress(message: str) -> None:
            if not progress_cb:
                return
            percent = 100 if total == 0 else (len(processed) / total) * 100
            progress_cb(percent, message, summary)

        def insert_group_item(
            group_id: int,
            item: Dict[str, Any],
            base_phash_int: int,
        ) -> None:
            nonlocal items_added
            dist = _hamming_distance(base_phash_int, item["phash_int"])
            cur.execute(
                '''
                INSERT OR IGNORE INTO phash_group_items
                (group_id, media_type, media_path, phash, distance, ts)
                VALUES (?, ?, ?, ?, ?, ?)
                ''',
                (
                    group_id,
                    item["media_type"],
                    item["media_path"],
                    item["phash"],
                    dist,
                    item["ts"],
                ),
            )
            if cur.rowcount:
                items_added += 1
                group_media[_media_key(item["media_type"], item["media_path"])] = group_id

        for item in items:
            if cancel_event is not None and cancel_event.is_set():
                _emit("pHash 연관관계 구축이 취소되었습니다.", log_cb)
                break
            key = _media_key(item["media_type"], item["media_path"])
            if key in group_media:
                items_skipped += 1
                processed.append(item)
                continue

            matches: list[Dict[str, Any]] = []
            for prev in processed:
                if _hamming_distance(item["phash_int"], prev["phash_int"]) <= distance:
                    matches.append(prev)

            if not matches:
                processed.append(item)
                continue

            grouped_ids = {
                group_media.get(_media_key(m["media_type"], m["media_path"]))
                for m in matches
                if _media_key(m["media_type"], m["media_path"]) in group_media
            }
            grouped_ids.discard(None)

            if grouped_ids:
                group_id = _iter_group_choice(grouped_ids, group_meta)
                if group_id is not None:
                    base_meta = group_meta[group_id]
                    base_phash_int = _phash_to_int(base_meta["base_phash"]) or item["phash_int"]
                    insert_group_item(group_id, item, base_phash_int)
            else:
                base_item = min(matches, key=lambda m: (m["ts"], m["media_path"]))
                cur.execute(
                    '''
                    INSERT INTO phash_groups (base_media, base_path, base_phash, base_ts)
                    VALUES (?, ?, ?, ?)
                    ''',
                    (
                        base_item["media_type"],
                        base_item["media_path"],
                        base_item["phash"],
                        base_item["ts"],
                    ),
                )
                group_id = cur.lastrowid
                group_meta[group_id] = {
                    "base_phash": base_item["phash"],
                    "base_ts": base_item["ts"],
                }
                groups_created += 1
                base_phash_int = base_item["phash_int"]
                insert_group_item(group_id, base_item, base_phash_int)
                for match in matches:
                    insert_group_item(group_id, match, base_phash_int)
                insert_group_item(group_id, item, base_phash_int)

            processed.append(item)
            if len(processed) % PROGRESS_EVERY == 0:
                update_progress("pHash 연관관계 구축 중...")

        conn.commit()

    summary["groups_created"] = groups_created
    summary["items_added"] = items_added
    summary["items_skipped"] = items_skipped
    summary["elapsed"] = time.time() - start
    summary["sample_items"] = [
        f"groups_created={groups_created}",
        f"items_added={items_added}",
        f"items_skipped={items_skipped}",
        f"elapsed={summary['elapsed']:.1f}s",
    ]
    update_progress("pHash 연관관계 구축 완료")
    return {"status": "ok", "message": "pHash 연관관계 구축 완료", "summary": summary}

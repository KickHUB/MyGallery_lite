from __future__ import annotations

import sqlite3
from typing import Iterable, List, Dict, Any, Optional

from settings import DB_PATH
from core.booru.booru_dict import ensure_booru_tables, normalize_booru_tag

MANUAL_SOURCE = "manual"


def normalize_booru_tags(tags: Iterable[str]) -> List[str]:
    seen: set[str] = set()
    result: List[str] = []
    for raw in tags or []:
        if raw is None:
            continue
        tag = normalize_booru_tag(str(raw))
        if not tag or tag in seen:
            continue
        seen.add(tag)
        result.append(tag)
    return result


def _normalize_item_key(media_type: str, media_path: str) -> tuple[str, str]:
    media = (media_type or "").strip().lower() or "image"
    from core.db.search_utils import normalize_media_path
    path = normalize_media_path(media_path or "")
    return media, path


def get_item_tags(
    media_type: str,
    media_path: str,
    *,
    source: str = MANUAL_SOURCE,
    conn: sqlite3.Connection | None = None,
) -> List[str]:
    media, path = _normalize_item_key(media_type, media_path)
    if not path:
        return []
    created_conn = conn is None
    if conn is None:
        conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    try:
        ensure_booru_tables(cur=cur, conn=conn)
        cur.execute(
            "SELECT tag FROM booru_item_tags WHERE media_type=? AND media_path=? AND source=? ORDER BY tag",
            (media, path, source),
        )
        rows = cur.fetchall()
        return [row[0] for row in rows if row and row[0]]
    finally:
        if created_conn:
            conn.close()


def replace_item_tags(
    media_type: str,
    media_path: str,
    tags: Iterable[str],
    *,
    source: str = MANUAL_SOURCE,
    conn: sqlite3.Connection | None = None,
) -> List[str]:
    media, path = _normalize_item_key(media_type, media_path)
    norm_tags = normalize_booru_tags(tags)
    if not path:
        return norm_tags

    created_conn = conn is None
    if conn is None:
        conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    try:
        ensure_booru_tables(cur=cur, conn=conn)
        cur.execute("BEGIN")
        cur.execute(
            "DELETE FROM booru_item_tags WHERE media_type=? AND media_path=? AND source=?",
            (media, path, source),
        )
        if norm_tags:
            rows = [(media, path, tag, source) for tag in norm_tags]
            cur.executemany(
                "INSERT INTO booru_item_tags (media_type, media_path, tag, source) VALUES (?, ?, ?, ?)",
                rows,
            )
        conn.commit()
        return norm_tags
    except Exception:
        conn.rollback()
        raise
    finally:
        if created_conn:
            conn.close()


def delete_item_tags(
    media_type: str,
    media_path: str,
    *,
    conn: sqlite3.Connection | None = None,
) -> int:
    media, path = _normalize_item_key(media_type, media_path)
    if not path:
        return 0
    created_conn = conn is None
    if conn is None:
        conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    try:
        ensure_booru_tables(cur=cur, conn=conn)
        cur.execute(
            "DELETE FROM booru_item_tags WHERE media_type=? AND media_path=?",
            (media, path),
        )
        if created_conn:
            conn.commit()
        return cur.rowcount or 0
    finally:
        if created_conn:
            conn.close()


def delete_item_ratings(
    media_type: str,
    media_path: str,
    *,
    conn: sqlite3.Connection | None = None,
) -> int:
    media, path = _normalize_item_key(media_type, media_path)
    if not path:
        return 0
    created_conn = conn is None
    if conn is None:
        conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    try:
        ensure_booru_tables(cur=cur, conn=conn)
        cur.execute(
            "DELETE FROM booru_item_rating WHERE media_type=? AND media_path=?",
            (media, path),
        )
        if created_conn:
            conn.commit()
        return cur.rowcount or 0
    finally:
        if created_conn:
            conn.close()


def get_manual_tags(
    media_type: str,
    media_path: str,
    *,
    conn: sqlite3.Connection | None = None,
) -> List[str]:
    return get_item_tags(media_type, media_path, source=MANUAL_SOURCE, conn=conn)


def list_item_tag_sources(
    media_type: str,
    media_path: str,
    *,
    conn: sqlite3.Connection | None = None,
) -> List[str]:
    media, path = _normalize_item_key(media_type, media_path)
    if not path:
        return []
    created_conn = conn is None
    if conn is None:
        conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    try:
        ensure_booru_tables(cur=cur, conn=conn)
        cur.execute(
            """
            SELECT DISTINCT source
            FROM booru_item_tags
            WHERE media_type=? AND media_path=?
            ORDER BY source
            """,
            (media, path),
        )
        rows = cur.fetchall()
        return [row[0] for row in rows if row and row[0]]
    finally:
        if created_conn:
            conn.close()


def get_booru_tags_with_counts(
    *,
    limit: int = 2000,
    media_type: Optional[str] = "image",
) -> List[Dict[str, Any]]:
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    try:
        ensure_booru_tables(cur=cur, conn=conn)
        params: List[Any] = []
        where_clauses = ["t.tag IS NOT NULL", "TRIM(t.tag) <> ''"]
        if media_type:
            where_clauses.append("t.media_type = ?")
            params.append(media_type)
        where_sql = " AND ".join(where_clauses)
        cur.execute(
            f"""
            SELECT
                t.tag,
                COALESCE(d.category, 'general') AS category,
                COUNT(DISTINCT t.media_path) AS cnt
            FROM booru_item_tags t
            LEFT JOIN booru_dict d ON d.tag = t.tag
            WHERE {where_sql}
            GROUP BY t.tag, COALESCE(d.category, 'general')
            ORDER BY cnt DESC, t.tag ASC
            LIMIT ?
            """,
            (*params, limit),
        )
        rows = cur.fetchall()
        return [
            {"tag": row[0], "category": (row[1] or "general"), "count": int(row[2] or 0)}
            for row in rows
            if row and row[0]
        ]
    finally:
        conn.close()


def get_booru_category_presence_counts(
    *,
    media_type: Optional[str] = "image",
) -> Dict[str, int]:
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    try:
        ensure_booru_tables(cur=cur, conn=conn)
        params: List[Any] = []
        where_clauses = ["t.tag IS NOT NULL", "TRIM(t.tag) <> ''"]
        if media_type:
            where_clauses.append("t.media_type = ?")
            params.append(media_type)
        where_sql = " AND ".join(where_clauses)
        cur.execute(
            f"""
            SELECT
                COALESCE(d.category, 'general') AS category,
                COUNT(DISTINCT t.media_path) AS cnt
            FROM booru_item_tags t
            LEFT JOIN booru_dict d ON d.tag = t.tag
            WHERE {where_sql}
            GROUP BY COALESCE(d.category, 'general')
            """,
            params,
        )
        rows = cur.fetchall()
        result: Dict[str, int] = {}
        for row in rows:
            if not row:
                continue
            category = str(row[0] or "general").lower()
            result[category] = int(row[1] or 0)
        return result
    finally:
        conn.close()


def get_booru_rating_media_count(
    *,
    media_type: Optional[str] = "image",
) -> int:
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    try:
        ensure_booru_tables(cur=cur, conn=conn)
        params: List[Any] = []
        where_sql = ""
        if media_type:
            where_sql = "WHERE media_type = ?"
            params.append(media_type)
        cur.execute(
            f"""
            SELECT COUNT(DISTINCT media_path) AS cnt
            FROM booru_item_rating
            {where_sql}
            """,
            params,
        )
        row = cur.fetchone()
        return int(row[0] or 0)
    finally:
        conn.close()


def get_booru_rating_counts(
    *,
    media_type: Optional[str] = "image",
) -> Dict[int, int]:
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    try:
        ensure_booru_tables(cur=cur, conn=conn)
        params: List[Any] = []
        where_sql = ""
        if media_type:
            where_sql = "WHERE media_type = ?"
            params.append(media_type)
        cur.execute(
            f"""
            SELECT rating, COUNT(DISTINCT media_path) AS cnt
            FROM booru_item_rating
            {where_sql}
            GROUP BY rating
            """,
            params,
        )
        rows = cur.fetchall()
        return {int(row[0]): int(row[1] or 0) for row in rows if row and row[0] is not None}
    finally:
        conn.close()

from __future__ import annotations

import re
import sqlite3
import threading
from typing import Dict, Optional

from settings import DB_PATH

_table_init_lock = threading.RLock()
_booru_tables_ready = False


def normalize_booru_tag(tag: str) -> str:
    text = (tag or "")
    text = str(text).strip().lstrip("\ufeff").lower()
    text = re.sub(r"\s+", " ", text)
    return text.replace(" ", "_")


def ensure_booru_tables(cur: Optional[sqlite3.Cursor] = None, conn: Optional[sqlite3.Connection] = None) -> None:
    """Ensure that Danbooru tag dictionary tables exist."""
    global _booru_tables_ready

    if _booru_tables_ready and cur is None and conn is None:
        return

    with _table_init_lock:
        if _booru_tables_ready and cur is None and conn is None:
            return

        close_conn = False
        if cur is None:
            created_conn = conn is None
            conn = sqlite3.connect(DB_PATH) if created_conn else conn
            cur = conn.cursor()
            close_conn = created_conn

        cur.execute(
            '''
            CREATE TABLE IF NOT EXISTS booru_dict (
                tag TEXT PRIMARY KEY,
                category TEXT DEFAULT 'general',
                post_count INTEGER DEFAULT 0,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
            '''
        )
        cur.execute(
            '''
            CREATE INDEX IF NOT EXISTS idx_booru_dict_category_count
            ON booru_dict(category, post_count DESC)
            '''
        )
        cur.execute(
            '''
            CREATE TABLE IF NOT EXISTS booru_item_tags (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                media_type TEXT NOT NULL,
                media_path TEXT NOT NULL,
                tag TEXT NOT NULL,
                source TEXT NOT NULL DEFAULT 'manual',
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(media_type, media_path, tag, source)
            )
            '''
        )
        cur.execute(
            '''
            CREATE INDEX IF NOT EXISTS idx_booru_item_tags_media
            ON booru_item_tags(media_type, media_path)
            '''
        )
        cur.execute(
            '''
            CREATE INDEX IF NOT EXISTS idx_booru_item_tags_tag
            ON booru_item_tags(tag)
            '''
        )
        cur.execute(
            '''
            CREATE TABLE IF NOT EXISTS booru_meta (
                key TEXT PRIMARY KEY,
                value TEXT
            )
            '''
        )
        cur.execute(
            '''
            CREATE TABLE IF NOT EXISTS booru_item_rating (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                media_type TEXT NOT NULL,
                media_path TEXT NOT NULL,
                rating INTEGER NOT NULL,
                source TEXT NOT NULL DEFAULT 'manual',
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(media_type, media_path, source)
            )
            '''
        )
        cur.execute(
            '''
            CREATE INDEX IF NOT EXISTS idx_booru_item_rating_media
            ON booru_item_rating(media_type, media_path)
            '''
        )

        if conn is not None:
            conn.commit()
        if close_conn and conn is not None:
            conn.close()
        _booru_tables_ready = True


def get_booru_meta(cur: Optional[sqlite3.Cursor] = None, conn: Optional[sqlite3.Connection] = None) -> Dict[str, str]:
    close_conn = False
    if cur is None:
        created_conn = conn is None
        conn = sqlite3.connect(DB_PATH) if created_conn else conn
        cur = conn.cursor()
        close_conn = created_conn

    ensure_booru_tables(cur=cur, conn=conn)
    cur.execute("SELECT key, value FROM booru_meta")
    rows = cur.fetchall()

    if close_conn and conn is not None:
        conn.close()
    return {str(k): "" if v is None else str(v) for k, v in rows}

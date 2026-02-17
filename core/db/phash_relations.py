from __future__ import annotations

import sqlite3
import threading
from typing import Optional

from settings import DB_PATH

_PHASH_REL_LOCK = threading.RLock()
_PHASH_REL_READY = False
_PHASH_GROUP_READY = False


def ensure_phash_relations_table(
    *, conn: Optional[sqlite3.Connection] = None, cur: Optional[sqlite3.Cursor] = None
) -> None:
    global _PHASH_REL_READY
    if _PHASH_REL_READY:
        return
    with _PHASH_REL_LOCK:
        if _PHASH_REL_READY:
            return
        close_conn = False
        if conn is None and cur is not None:
            conn = cur.connection
        if conn is None:
            conn = sqlite3.connect(DB_PATH)
            close_conn = True
        if cur is None:
            cur = conn.cursor()
        cur.execute(
            '''
            CREATE TABLE IF NOT EXISTS phash_relations (
                base_phash TEXT NOT NULL,
                other_phash TEXT NOT NULL,
                distance INTEGER NOT NULL,
                created_at REAL DEFAULT (strftime('%s','now')),
                PRIMARY KEY (base_phash, other_phash)
            )
            '''
        )
        cur.execute(
            'CREATE INDEX IF NOT EXISTS idx_phash_rel_base_dist ON phash_relations(base_phash, distance)'
        )
        cur.execute(
            'CREATE INDEX IF NOT EXISTS idx_phash_rel_other ON phash_relations(other_phash)'
        )
        conn.commit()
        if close_conn and conn is not None:
            conn.close()
        _PHASH_REL_READY = True


def clear_phash_relations(
    *, conn: Optional[sqlite3.Connection] = None, cur: Optional[sqlite3.Cursor] = None
) -> int:
    close_conn = False
    if conn is None:
        conn = sqlite3.connect(DB_PATH)
        close_conn = True
    if cur is None:
        cur = conn.cursor()
    try:
        cur.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='phash_relations'"
        )
        if not cur.fetchone():
            return 0
        cur.execute("DELETE FROM phash_relations")
        deleted = cur.rowcount if cur.rowcount is not None and cur.rowcount >= 0 else 0
        conn.commit()
        return int(deleted or 0)
    finally:
        if close_conn and conn is not None:
            conn.close()


def ensure_phash_group_tables(
    *, conn: Optional[sqlite3.Connection] = None, cur: Optional[sqlite3.Cursor] = None
) -> None:
    global _PHASH_GROUP_READY
    if _PHASH_GROUP_READY:
        return
    with _PHASH_REL_LOCK:
        if _PHASH_GROUP_READY:
            return
        close_conn = False
        if conn is None and cur is not None:
            conn = cur.connection
        if conn is None:
            conn = sqlite3.connect(DB_PATH)
            close_conn = True
        if cur is None:
            cur = conn.cursor()
        cur.execute(
            '''
            CREATE TABLE IF NOT EXISTS phash_groups (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                base_media TEXT NOT NULL,
                base_path TEXT NOT NULL,
                base_phash TEXT NOT NULL,
                base_ts REAL NOT NULL,
                created_at REAL DEFAULT (strftime('%s','now'))
            )
            '''
        )
        cur.execute(
            '''
            CREATE TABLE IF NOT EXISTS phash_group_items (
                group_id INTEGER NOT NULL,
                media_type TEXT NOT NULL,
                media_path TEXT NOT NULL,
                phash TEXT NOT NULL,
                distance INTEGER NOT NULL,
                ts REAL NOT NULL,
                created_at REAL DEFAULT (strftime('%s','now')),
                UNIQUE(media_type, media_path)
            )
            '''
        )
        cur.execute(
            'CREATE INDEX IF NOT EXISTS idx_phash_groups_base ON phash_groups(base_phash)'
        )
        cur.execute(
            'CREATE INDEX IF NOT EXISTS idx_phash_group_items_group ON phash_group_items(group_id)'
        )
        cur.execute(
            'CREATE INDEX IF NOT EXISTS idx_phash_group_items_distance ON phash_group_items(distance)'
        )
        conn.commit()
        if close_conn and conn is not None:
            conn.close()
        _PHASH_GROUP_READY = True


def clear_phash_groups(
    *, conn: Optional[sqlite3.Connection] = None, cur: Optional[sqlite3.Cursor] = None
) -> int:
    close_conn = False
    if conn is None:
        conn = sqlite3.connect(DB_PATH)
        close_conn = True
    if cur is None:
        cur = conn.cursor()
    try:
        cur.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='phash_group_items'"
        )
        if not cur.fetchone():
            return 0
        cur.execute("DELETE FROM phash_group_items")
        deleted_items = cur.rowcount if cur.rowcount is not None and cur.rowcount >= 0 else 0
        cur.execute("DELETE FROM phash_groups")
        conn.commit()
        return int(deleted_items or 0)
    finally:
        if close_conn and conn is not None:
            conn.close()

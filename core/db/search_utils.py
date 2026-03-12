# core/search_utils.py
# Provides search_images, autocomplete_tags, get_all_models and DB helpers.

from __future__ import annotations

import os
import logging
import math
import sqlite3
import json
import time
import threading
import re
from collections import OrderedDict
from typing import List, Dict, Any, Optional, Tuple

import settings

from core.media.video_index import ensure_videos_table
from core.booru.booru_dict import ensure_booru_tables, normalize_booru_tag
from core.booru.booru_item_tags import delete_item_ratings, delete_item_tags
from core.tagging.tag_utils import filter_tags
from settings import (
    DB_PATH,
    DEST_FOLDER_NAME,
    DRAFTS_FOLDER_NAME,
    PERF_LOGS,
    SEARCH_USE_FTS,
    FTS_AUTO_BUILD,
    SPLIT_IMAGE_RELATION_LOADS,
    SEARCH_TOTAL_CACHE_TTL_SECONDS,
    SEARCH_TOTAL_DATASET_COUNT_TTL_SECONDS,
    SEARCH_TOTAL_LARGE_DATASET_THRESHOLD,
    SEARCH_TOTAL_SKIP_LARGE_DATASET_TOTALS,
)
from core.media.gallery_layout import extract_date_from_path

_table_init_lock = threading.RLock()
_collection_tables_ready = False
_model_category_tables_ready = False
_image_tables_ready = False
_fts_tables_ready = False
_fts_search_enabled = False
_SEARCH_TOTAL_CACHE_LOCK = threading.Lock()
_SEARCH_TOTAL_CACHE: "OrderedDict[Tuple[object, ...], Dict[str, object]]" = OrderedDict()
_SEARCH_TOTAL_CACHE_LIMIT = 200
_SEARCH_TOTAL_CACHE_TTL_SECONDS = float(SEARCH_TOTAL_CACHE_TTL_SECONDS)
_DATASET_COUNT_CACHE_LOCK = threading.Lock()
_DATASET_COUNT_CACHE: Dict[str, object] = {"total": None, "updated_at": 0.0}
_DATASET_COUNT_CACHE_TTL_SECONDS = float(SEARCH_TOTAL_DATASET_COUNT_TTL_SECONDS)
logger = logging.getLogger(__name__)


def _normalize_model_filter(model: Optional[Any]) -> Optional[Tuple[str, ...]]:
    if model is None:
        return None
    if isinstance(model, (list, tuple, set)):
        items = [str(item).strip() for item in model if str(item).strip()]
        return tuple(sorted(items)) if items else None
    model_str = str(model).strip()
    return (model_str,) if model_str else None


def _normalize_collection_ids(
    collection_ids: Optional[List[Any]],
) -> Optional[Tuple[Any, ...]]:
    if collection_ids is None:
        return None
    if not collection_ids:
        return ()
    if any(isinstance(item, (list, tuple, set)) for item in collection_ids):
        groups = []
        seen_groups = set()
        for group in collection_ids:
            if not isinstance(group, (list, tuple, set)):
                group = [group]
            cleaned = []
            seen = set()
            for cid in group:
                try:
                    cid_int = int(cid)
                except (TypeError, ValueError):
                    continue
                if cid_int in seen:
                    continue
                seen.add(cid_int)
                cleaned.append(cid_int)
            if not cleaned:
                continue
            group_key = tuple(sorted(cleaned))
            if group_key in seen_groups:
                continue
            seen_groups.add(group_key)
            groups.append(group_key)
        return tuple(sorted(groups))
    cleaned = []
    seen = set()
    for cid in collection_ids:
        try:
            cid_int = int(cid)
        except (TypeError, ValueError):
            continue
        if cid_int in seen:
            continue
        seen.add(cid_int)
        cleaned.append(cid_int)
    return tuple(cleaned)


def _get_search_total_cache_key(
    query: str,
    match_mode: str,
    model: Optional[Any],
    model_match: str,
    sampler: Optional[str],
    seed: Optional[int],
    steps: Optional[int],
    draft_mode: str,
    collection_ids: Optional[List[Any]],
    collection_match: str,
    tag_source: str,
) -> Tuple[object, ...]:
    return (
        (query or "").lower(),
        str(match_mode or "").lower(),
        _normalize_model_filter(model),
        str(model_match or "").lower(),
        (sampler or "").lower(),
        seed,
        steps,
        str(draft_mode or ""),
        _normalize_collection_ids(collection_ids),
        str(collection_match or "").lower(),
        str(tag_source or "").lower(),
    )


def _resolve_collection_filter_ids(
    conn: sqlite3.Connection,
    collection_ids: Optional[List[int]],
    *,
    collection_id: Optional[int] = None,
    collection_subtree_cache: Optional[Dict[int, List[int]]] = None,
) -> Optional[List[List[int]]]:
    if collection_ids is None:
        if collection_id is None:
            return None
        collection_ids = [collection_id]
    if not collection_ids:
        return []
    subtree_cache: Dict[int, List[int]] = collection_subtree_cache or {}
    resolved: List[List[int]] = []
    for raw_id in collection_ids:
        try:
            cid = int(raw_id)
        except (TypeError, ValueError):
            continue
        group: List[int] = []
        seen: set[int] = set()
        for sub_id in get_subtree_collection_ids(conn, cid, cache=subtree_cache):
            if sub_id in seen:
                continue
            seen.add(sub_id)
            group.append(sub_id)
        if group:
            resolved.append(group)
    return resolved


def _get_cached_total_count(cache_key: Tuple[object, ...]) -> Optional[int]:
    now = time.time()
    with _SEARCH_TOTAL_CACHE_LOCK:
        cached = _SEARCH_TOTAL_CACHE.get(cache_key)
        if not cached:
            return None
        updated_at = float(cached.get("updated_at", 0))
        if now - updated_at > _SEARCH_TOTAL_CACHE_TTL_SECONDS:
            _SEARCH_TOTAL_CACHE.pop(cache_key, None)
            return None
        _SEARCH_TOTAL_CACHE.move_to_end(cache_key)
        total = cached.get("total")
        return int(total) if total is not None else None


def _set_cached_total_count(cache_key: Tuple[object, ...], total: int) -> None:
    with _SEARCH_TOTAL_CACHE_LOCK:
        _SEARCH_TOTAL_CACHE[cache_key] = {"total": int(total), "updated_at": time.time()}
        _SEARCH_TOTAL_CACHE.move_to_end(cache_key)
        while len(_SEARCH_TOTAL_CACHE) > _SEARCH_TOTAL_CACHE_LIMIT:
            _SEARCH_TOTAL_CACHE.popitem(last=False)


def get_dataset_image_count() -> int:
    ensure_image_tables()
    now = time.time()
    with _DATASET_COUNT_CACHE_LOCK:
        cached_total = _DATASET_COUNT_CACHE.get("total")
        cached_at = float(_DATASET_COUNT_CACHE.get("updated_at", 0.0))
        if cached_total is not None and now - cached_at <= _DATASET_COUNT_CACHE_TTL_SECONDS:
            return int(cached_total)
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    try:
        cur.execute("SELECT COUNT(*) FROM images")
        total = cur.fetchone()[0] or 0
    finally:
        conn.close()
    with _DATASET_COUNT_CACHE_LOCK:
        _DATASET_COUNT_CACHE["total"] = int(total)
        _DATASET_COUNT_CACHE["updated_at"] = time.time()
    return int(total)


def is_large_dataset(*, threshold: Optional[int] = None) -> bool:
    if not SEARCH_TOTAL_SKIP_LARGE_DATASET_TOTALS:
        return False
    limit = SEARCH_TOTAL_LARGE_DATASET_THRESHOLD if threshold is None else int(threshold)
    if limit <= 0:
        return False
    try:
        return get_dataset_image_count() >= limit
    except Exception:
        return False


def should_skip_total_count(
    *,
    query: str = "",
    model: Optional[Any] = None,
    sampler: Optional[str] = None,
    seed: Optional[int] = None,
    steps: Optional[int] = None,
    collection_ids: Optional[List[Any]] = None,
    draft_mode: str = "exclude",
    threshold: Optional[int] = None,
) -> bool:
    if not SEARCH_TOTAL_SKIP_LARGE_DATASET_TOTALS:
        return False
    if query and str(query).strip():
        return False
    if model or sampler or seed is not None or steps is not None:
        return False
    if collection_ids:
        return False
    if str(draft_mode or "") not in {"exclude", ""}:
        return False
    return is_large_dataset(threshold=threshold)


def _create_image_indexes(cur: sqlite3.Cursor) -> None:
    """Ensure images table indexes exist for common query patterns."""
    index_statements = [
        'CREATE INDEX IF NOT EXISTS idx_images_file ON images(file)',
        'CREATE INDEX IF NOT EXISTS idx_images_date ON images(date)',
        'CREATE INDEX IF NOT EXISTS idx_images_order ON images(date, file, id)',
        'CREATE INDEX IF NOT EXISTS idx_images_model ON images(model)',
        'CREATE INDEX IF NOT EXISTS idx_images_sampler ON images(sampler)',
        'CREATE INDEX IF NOT EXISTS idx_images_seed ON images(seed)',
        'CREATE INDEX IF NOT EXISTS idx_images_steps ON images(steps)',
        'CREATE INDEX IF NOT EXISTS idx_images_phash ON images(phash)',
    ]
    for stmt in index_statements:
        cur.execute(stmt)


def _fts_table_exists(cur: sqlite3.Cursor) -> bool:
    cur.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='images_fts'")
    return cur.fetchone() is not None


def _create_fts_tables(cur: sqlite3.Cursor) -> None:
    cur.execute(
        '''
        CREATE VIRTUAL TABLE IF NOT EXISTS images_fts
        USING fts5(
            positive,
            negative,
            content='images',
            content_rowid='id',
            tokenize='unicode61'
        )
        '''
    )
    cur.execute(
        '''
        CREATE TRIGGER IF NOT EXISTS trg_images_fts_ai
        AFTER INSERT ON images
        BEGIN
            INSERT INTO images_fts(rowid, positive, negative)
            VALUES (new.id, new.positive, new.negative);
        END;
        '''
    )
    cur.execute(
        '''
        CREATE TRIGGER IF NOT EXISTS trg_images_fts_ad
        AFTER DELETE ON images
        BEGIN
            INSERT INTO images_fts(images_fts, rowid, positive, negative)
            VALUES ('delete', old.id, old.positive, old.negative);
        END;
        '''
    )
    cur.execute(
        '''
        CREATE TRIGGER IF NOT EXISTS trg_images_fts_au
        AFTER UPDATE ON images
        BEGIN
            INSERT INTO images_fts(images_fts, rowid, positive, negative)
            VALUES ('delete', old.id, old.positive, old.negative);
            INSERT INTO images_fts(rowid, positive, negative)
            VALUES (new.id, new.positive, new.negative);
        END;
        '''
    )


def _drop_fts_tables(cur: sqlite3.Cursor) -> None:
    cur.execute("DROP TRIGGER IF EXISTS trg_images_fts_ai")
    cur.execute("DROP TRIGGER IF EXISTS trg_images_fts_ad")
    cur.execute("DROP TRIGGER IF EXISTS trg_images_fts_au")
    cur.execute("DROP TABLE IF EXISTS images_fts")


def _rebuild_fts_index(cur: sqlite3.Cursor) -> None:
    cur.execute("INSERT INTO images_fts(images_fts) VALUES('rebuild')")


def ensure_fts_tables(
    cur: sqlite3.Cursor,
    conn: sqlite3.Connection,
    *,
    rebuild: bool = False,
) -> bool:
    global _fts_tables_ready, _fts_search_enabled
    try:
        existed_before = _fts_table_exists(cur)
        _create_fts_tables(cur)
        if rebuild or not existed_before:
            _rebuild_fts_index(cur)
        conn.commit()
        _fts_tables_ready = True
        _fts_search_enabled = True
        return True
    except sqlite3.OperationalError as exc:
        logger.warning("FTS 테이블 초기화 실패: %s", exc)
        _fts_search_enabled = False
        return False


def ensure_collection_tables(cur: Optional[sqlite3.Cursor] = None, conn: Optional[sqlite3.Connection] = None) -> None:
    """Ensure that collection metadata tables exist."""
    global _collection_tables_ready

    if _collection_tables_ready and cur is None and conn is None:
        return

    with _table_init_lock:
        if _collection_tables_ready and cur is None and conn is None:
            return

        close_conn = False
        if cur is None:
            created_conn = conn is None
            conn = sqlite3.connect(DB_PATH) if created_conn else conn
            cur = conn.cursor()
            close_conn = created_conn

        cur.execute(
            '''
            CREATE TABLE IF NOT EXISTS collections (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                parent_id INTEGER REFERENCES collections(id) ON DELETE SET NULL,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
            '''
        )
        cur.execute('PRAGMA table_info(collections)')
        existing_cols = {row[1] for row in cur.fetchall()}
        if 'parent_id' not in existing_cols:
            cur.execute('ALTER TABLE collections ADD COLUMN parent_id INTEGER REFERENCES collections(id) ON DELETE SET NULL')
        cur.execute('CREATE INDEX IF NOT EXISTS idx_collections_parent ON collections(parent_id)')
        cur.execute(
            'CREATE UNIQUE INDEX IF NOT EXISTS uidx_collections_parent_name '
            'ON collections(IFNULL(parent_id, 0), name)'
        )
        cur.execute(
            '''
            CREATE TABLE IF NOT EXISTS collection_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                collection_id INTEGER NOT NULL,
                media_path TEXT NOT NULL,
                media_type TEXT NOT NULL,
                UNIQUE(collection_id, media_path),
                FOREIGN KEY(collection_id) REFERENCES collections(id) ON DELETE CASCADE
            )
            '''
        )
        cur.execute('CREATE INDEX IF NOT EXISTS idx_collection_items_collection ON collection_items(collection_id)')
        cur.execute('CREATE INDEX IF NOT EXISTS idx_collection_items_media_path ON collection_items(media_path)')
        cur.execute(
            'CREATE INDEX IF NOT EXISTS idx_collection_items_collection_type_path '
            'ON collection_items(collection_id, media_type, media_path)'
        )

        if conn is not None:
            conn.commit()
        if close_conn and conn is not None:
            conn.close()
        _collection_tables_ready = True


def ensure_model_category_tables(
    cur: Optional[sqlite3.Cursor] = None,
    conn: Optional[sqlite3.Connection] = None,
) -> None:
    """Ensure that model category metadata tables exist."""
    global _model_category_tables_ready

    if _model_category_tables_ready and cur is None and conn is None:
        return

    with _table_init_lock:
        if _model_category_tables_ready and cur is None and conn is None:
            return

        close_conn = False
        if cur is None:
            created_conn = conn is None
            conn = sqlite3.connect(DB_PATH) if created_conn else conn
            cur = conn.cursor()
            close_conn = created_conn

        cur.execute(
            '''
            CREATE TABLE IF NOT EXISTS model_categories (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                parent_id INTEGER REFERENCES model_categories(id) ON DELETE SET NULL,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
            '''
        )
        cur.execute('PRAGMA table_info(model_categories)')
        existing_cols = {row[1] for row in cur.fetchall()}
        if 'parent_id' not in existing_cols:
            cur.execute(
                'ALTER TABLE model_categories ADD COLUMN parent_id '
                'INTEGER REFERENCES model_categories(id) ON DELETE SET NULL'
            )
        cur.execute('CREATE INDEX IF NOT EXISTS idx_model_categories_parent ON model_categories(parent_id)')
        cur.execute(
            'CREATE UNIQUE INDEX IF NOT EXISTS uidx_model_categories_parent_name '
            'ON model_categories(IFNULL(parent_id, 0), name)'
        )
        cur.execute(
            '''
            CREATE TABLE IF NOT EXISTS model_category_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                category_id INTEGER NOT NULL,
                model_name TEXT NOT NULL,
                UNIQUE(category_id, model_name),
                FOREIGN KEY(category_id) REFERENCES model_categories(id) ON DELETE CASCADE
            )
            '''
        )
        cur.execute('CREATE INDEX IF NOT EXISTS idx_model_category_items_category ON model_category_items(category_id)')
        cur.execute('CREATE INDEX IF NOT EXISTS idx_model_category_items_name ON model_category_items(model_name)')

        if conn is not None:
            conn.commit()
        if close_conn and conn is not None:
            conn.close()
        _model_category_tables_ready = True

def ensure_image_tables() -> None:
    """Ensure that the images, tags and loras tables exist in the database."""
    global _image_tables_ready
    if _image_tables_ready:
        return

    with _table_init_lock:
        if _image_tables_ready:
            return

        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()

        ensure_collection_tables(cur=cur, conn=conn)
        ensure_model_category_tables(cur=cur, conn=conn)

        cur.execute(
            '''
            CREATE TABLE IF NOT EXISTS images (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                file TEXT UNIQUE,
                date TEXT,
                model TEXT,
                models TEXT,
                positive TEXT,
                negative TEXT,
                width INTEGER,
                height INTEGER,
                created TEXT,
                seed TEXT,
                steps INTEGER,
                cfg REAL,
                sampler TEXT,
                scheduler TEXT,
                denoise REAL,
                model_checkpoint TEXT,
                vae_name TEXT,
                workflow_id TEXT,
                node_count INTEGER,
                guidance REAL,
                phash TEXT,
                extras TEXT
            )
            '''
        )
        cur.execute(
            '''
            CREATE TABLE IF NOT EXISTS tags (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                image_id INTEGER,
                tag TEXT
            )
            '''
        )
        cur.execute(
            '''
            CREATE TABLE IF NOT EXISTS loras (
                image_id INTEGER,
                name TEXT,
                strength REAL
            )
            '''
        )
        cur.execute('CREATE INDEX IF NOT EXISTS idx_tags_tag ON tags(tag)')
        cur.execute('CREATE INDEX IF NOT EXISTS idx_tags_image ON tags(image_id)')
        cur.execute('CREATE INDEX IF NOT EXISTS idx_tags_tag_image ON tags(tag, image_id)')
        cur.execute('PRAGMA index_list(tags)')
        existing_tag_indexes = {row[1] for row in cur.fetchall()}
        if 'idx_tags_image_tag_unique' not in existing_tag_indexes:
            cur.execute(
                '''
                DELETE FROM tags
                WHERE id NOT IN (
                    SELECT MIN(id) FROM tags GROUP BY image_id, tag
                )
                '''
            )
            cur.execute(
                'CREATE UNIQUE INDEX IF NOT EXISTS idx_tags_image_tag_unique ON tags(image_id, tag)'
            )
        cur.execute('CREATE INDEX IF NOT EXISTS idx_loras_image ON loras(image_id)')

        # Add missing columns for existing databases
        cur.execute('PRAGMA table_info(images)')
        existing_cols = {row[1] for row in cur.fetchall()}
        required_cols = {
            'width': 'INTEGER',
            'height': 'INTEGER',
            'created': 'TEXT',
            'seed': 'TEXT',
            'steps': 'INTEGER',
            'cfg': 'REAL',
            'sampler': 'TEXT',
            'scheduler': 'TEXT',
            'denoise': 'REAL',
            'model_checkpoint': 'TEXT',
            'models': 'TEXT',
            'vae_name': 'TEXT',
            'workflow_id': 'TEXT',
            'node_count': 'INTEGER',
            'guidance': 'REAL',
            'phash': 'TEXT',
            'extras': 'TEXT',
        }
        for col, col_type in required_cols.items():
            if col not in existing_cols:
                cur.execute(f'ALTER TABLE images ADD COLUMN {col} {col_type}')

        _create_image_indexes(cur)
        if SEARCH_USE_FTS:
            ensure_fts_tables(cur, conn, rebuild=FTS_AUTO_BUILD)
        elif _fts_table_exists(cur):
            _fts_tables_ready = True
            _fts_search_enabled = False

        conn.commit()
        conn.close()
        _image_tables_ready = True

def _normalize_keywords(query: str) -> List[str]:
    """Split the query by commas and normalize spaces/underscores."""
    return [kw.strip().replace('_', ' ') for kw in query.split(',') if kw.strip()]


def _normalize_booru_keywords(query: str) -> List[str]:
    keywords = []
    for kw in query.split(","):
        normalized = normalize_booru_tag(kw)
        if not normalized:
            continue
        keywords.append(normalized)
    return keywords


def _fts_query_for_keyword(keyword: str) -> str:
    cleaned = keyword.replace('"', '').replace("'", "").strip()
    if not cleaned:
        return ""
    tokens = [token for token in cleaned.split() if token]
    if not tokens:
        return ""
    if any(not re.match(r"^\w+$", token) for token in tokens):
        return ""
    return " ".join(f"{token}*" for token in tokens)


def _keyword_filter_clause(keyword: str, *, use_fts: bool) -> Tuple[str, List[Any]]:
    if use_fts:
        fts_query = _fts_query_for_keyword(keyword)
        if fts_query:
            clause = (
                '('
                'EXISTS(SELECT 1 FROM images_fts WHERE images_fts.rowid = images.id AND images_fts MATCH ?) '
                'OR EXISTS(SELECT 1 FROM tags t WHERE t.image_id = images.id AND t.tag = ?)'
                ')'
            )
            return clause, [fts_query, keyword.lower()]
    clause = (
        '('
        'images.positive LIKE ? OR images.negative LIKE ? '
        'OR EXISTS(SELECT 1 FROM tags t WHERE t.image_id = images.id AND t.tag = ?)'
        ')'
    )
    return clause, [f'%{keyword}%', f'%{keyword}%', keyword.lower()]


def _booru_keyword_filter_clause(keyword: str) -> Tuple[str, List[Any]]:
    rating_map = {
        "general": 0,
        "sensitive": 1,
        "questionable": 2,
        "explicit": 3,
    }
    if keyword.startswith("missing:"):
        missing_key = keyword.split(":", 1)[1].strip().lower()
        if missing_key in {"rating", "ratings"}:
            clause = (
                "NOT EXISTS("
                "SELECT 1 FROM booru_item_rating br "
                "WHERE br.media_type = 'image' AND br.media_path = images.file"
                ")"
            )
            return clause, []
        clause = (
            "NOT EXISTS("
            "SELECT 1 FROM booru_item_tags bt "
            "LEFT JOIN booru_dict d ON d.tag = bt.tag "
            "WHERE bt.media_type = 'image' AND bt.media_path = images.file "
            "AND COALESCE(d.category, 'general') = ?"
            ")"
        )
        return clause, [missing_key]
    if keyword.startswith("rating:"):
        rating_key = keyword.split(":", 1)[1]
        rating_val = rating_map.get(rating_key)
        if rating_val is not None:
            clause = (
                "EXISTS("
                "SELECT 1 FROM booru_item_rating br "
                "WHERE br.media_type = 'image' AND br.media_path = images.file AND br.rating = ?"
                ")"
            )
            return clause, [rating_val]
    clause = (
        "EXISTS("
        "SELECT 1 FROM booru_item_tags bt "
        "WHERE bt.media_type = 'image' AND bt.media_path = images.file AND bt.tag = ?"
        ")"
    )
    return clause, [keyword]

def _build_filter_sql(
    query: str,
    match_mode: str,
    model: Optional[Any],
    model_match: str,
    sampler: Optional[str],

    seed: Optional[int],

    steps: Optional[int],
    draft_mode: str = 'exclude',
    collection_ids: Optional[List[List[int]]] = None,
    collection_match: str = "and",
    exclude_video_thumbs: bool = False,
    tag_source: str = "prompt",
):
    sql = ' WHERE 1=1 '
    params: List[Any] = []
    use_fts = _fts_search_enabled
    model_logic = "or" if str(model_match).lower() == "or" else "and"
    collection_logic = "or" if str(collection_match).lower() == "or" else "and"
    draft_mode = (draft_mode or 'exclude').lower()
    # Draft classification:
    # - Legacy layout: DEST/Drafts/YYYY-MM-DD/...
    # - New layout: DEST/<DEST_CONTENT_SUBDIR>/YYYY-MM-DD/drafts/...
    # We use LIKE patterns rather than strict prefixes so both layouts are covered.
    drafts_name = getattr(settings, 'DRAFTS_IN_DATE_DIRNAME', 'drafts') or 'drafts'
    draft_like_patterns = []

    # New layout: any path segment '/drafts_name/'
    draft_like_patterns.append(f"%/{drafts_name.lower()}/%")

    # Legacy top-level Drafts folder (and its prefixed form)
    if DRAFTS_FOLDER_NAME:
        legacy = DRAFTS_FOLDER_NAME.lower().rstrip('/')
        draft_like_patterns.append(legacy + '/%')
        if DEST_FOLDER_NAME:
            draft_like_patterns.append(f"{DEST_FOLDER_NAME.lower().rstrip('/')}/{legacy}/%")

    if draft_mode not in {'exclude', 'only', 'all'}:
        draft_mode = 'exclude'

    if draft_like_patterns:
        if draft_mode == 'exclude':
            for pat in draft_like_patterns:
                sql += ' AND LOWER(images.file) NOT LIKE ?'
                params.append(pat)
        elif draft_mode == 'only':
            ors = ['LOWER(images.file) LIKE ?' for _ in draft_like_patterns]
            sql += ' AND (' + ' OR '.join(ors) + ')'
            params.extend(draft_like_patterns)

    model_values: List[str] = []

    if model:
        if isinstance(model, (list, tuple, set)):
            seen_models = set()
            for entry in model:
                value = str(entry).strip()
                if not value or value in seen_models:
                    continue
                seen_models.add(value)
                model_values.append(value)
        else:
            value = str(model).strip()
            model_values = [value] if value else []

    if model_values:
        if model_logic == "or":
            clauses = []
            for model_name in model_values:
                clauses.append('(images.model = ? OR images.models = ? OR images.models LIKE ?)')
                params.extend([model_name, model_name, f'%"{model_name}"%'])
            sql += ' AND (' + ' OR '.join(clauses) + ')'
        else:
            for model_name in model_values:
                sql += ' AND (images.model = ? OR images.models = ? OR images.models LIKE ?)'
                params.extend([model_name, model_name, f'%"{model_name}"%'])
    if sampler:
        sql += ' AND images.sampler = ?'
        params.append(sampler)
    if seed is not None:
        sql += ' AND images.seed = ?'
        params.append(int(seed))
    if steps is not None:
        sql += ' AND images.steps = ?'
        params.append(int(steps))
    if exclude_video_thumbs:
        sql += (
            ' AND NOT EXISTS(SELECT 1 FROM videos '
            'WHERE videos.rel_thumb = images.file '
            "OR videos.rel_thumb = REPLACE(images.file, ? || '/', ''))"
        )
        params.append(DEST_FOLDER_NAME)

    if collection_ids is not None:
        if collection_ids:
            if collection_logic == "or":
                clauses = []
                for group in collection_ids:
                    if not group:
                        clauses.append('0')
                        continue
                    placeholders = ','.join('?' for _ in group)
                    clauses.append(
                        'EXISTS(SELECT 1 FROM collection_items ci '
                        f"WHERE ci.collection_id IN ({placeholders}) AND ci.media_type = 'image' "
                        'AND ci.media_path = images.file)'
                    )
                    params.extend(group)
                sql += ' AND (' + ' OR '.join(clauses) + ')'
            else:
                for group in collection_ids:
                    if not group:
                        sql += ' AND 0'
                        continue
                    placeholders = ','.join('?' for _ in group)
                    sql += (
                        ' AND EXISTS(SELECT 1 FROM collection_items ci '
                        f"WHERE ci.collection_id IN ({placeholders}) AND ci.media_type = 'image' "
                        'AND ci.media_path = images.file)'
                    )
                    params.extend(group)
        else:
            sql += ' AND 0'


    normalized_tag_source = (tag_source or "prompt").lower()
    keywords = _normalize_booru_keywords(query) if normalized_tag_source == "booru" else _normalize_keywords(query)
    if keywords:
        clause_builder = _booru_keyword_filter_clause if normalized_tag_source == "booru" else _keyword_filter_clause
        if str(match_mode).lower() == 'or':
            ors = []
            for kw in keywords:
                if normalized_tag_source == "booru":
                    clause, clause_params = clause_builder(kw)
                else:
                    clause, clause_params = clause_builder(kw, use_fts=use_fts)
                ors.append(clause)
                params.extend(clause_params)
            sql += ' AND (' + ' OR '.join(ors) + ')'
        else:
            for kw in keywords:
                if normalized_tag_source == "booru":
                    clause, clause_params = clause_builder(kw)
                else:
                    clause, clause_params = clause_builder(kw, use_fts=use_fts)
                sql += f' AND {clause}'
                params.extend(clause_params)

    return sql, params


def migrate_fts_tables(*, rebuild: bool = True, drop_existing: bool = False) -> bool:
    ensure_image_tables()
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    try:
        if drop_existing:
            _drop_fts_tables(cur)
        _create_fts_tables(cur)
        if rebuild:
            _rebuild_fts_index(cur)
        conn.commit()
        return True
    except sqlite3.OperationalError as exc:
        logger.warning("FTS 마이그레이션 실패: %s", exc)
        return False
    finally:
        conn.close()

def search_images(
    query: str = '',
    match_mode: str = 'and',
    sort_order: str = 'desc',
    limit: int = 100,
    page: int = 1,
    model: Optional[Any] = None,
    model_match: str = "and",
    sampler: Optional[str] = None,
    seed: Optional[int] = None,
    steps: Optional[int] = None,
    draft_mode: str = 'exclude',
    collection_id: Optional[int] = None,
    collection_ids: Optional[List[int]] = None,
    cursor: Optional[tuple[Optional[str], Optional[str], Optional[int]]] = None,
    use_offset: bool = True,
    *,
    include_total: bool = True,
    compact: bool = False,
    collection_subtree_cache: Optional[Dict[int, List[int]]] = None,
    collection_match: str = "and",
    split_relations: Optional[bool] = None,
    tag_source: str = "prompt",
) -> Dict[str, Any]:
    """Search images and return dict for UI/api:
       { 'results': [...], 'total_count': int, 'total_pages': int }
    """
    perf_enabled = PERF_LOGS
    overall_start = time.perf_counter() if perf_enabled else 0.0
    filter_ms = 0.0
    count_ms = 0.0
    data_ms = 0.0
    transform_ms = 0.0

    ensure_collection_tables()
    ensure_videos_table()
    if (tag_source or "").lower() == "booru":
        ensure_booru_tables()
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    order = 'DESC' if str(sort_order).lower().startswith('d') else 'ASC'
    use_offset = bool(use_offset or cursor is None)
    offset = max(0, (int(page) - 1) * max(1, int(limit)))
    limit = max(1, int(limit))

    collection_groups = _resolve_collection_filter_ids(
        conn,
        collection_ids,
        collection_id=collection_id,
        collection_subtree_cache=collection_subtree_cache,
    )

    filter_start = time.perf_counter() if perf_enabled else 0.0
    fsql, fparams = _build_filter_sql(
        query,
        match_mode,
        model,
        model_match,
        sampler,
        seed,
        steps,
        draft_mode,
        collection_groups,
        collection_match,
        exclude_video_thumbs=True,
        tag_source=tag_source,
    )
    if perf_enabled:
        filter_ms = (time.perf_counter() - filter_start) * 1000
    total: Optional[int] = None
    total_pages: Optional[int] = None
    cache_key = _get_search_total_cache_key(
        query,
        match_mode,
        model,
        model_match,
        sampler,
        seed,
        steps,
        draft_mode,
        collection_groups,
        collection_match,
        tag_source,
    )
    total = _get_cached_total_count(cache_key)
    if include_total and total is None:
        count_sql = '''
            SELECT COUNT(*)
            FROM images
        '''
        count_start = time.perf_counter() if perf_enabled else 0.0
        cur.execute(count_sql + fsql, fparams)
        total = cur.fetchone()[0] or 0
        if perf_enabled:
            count_ms = (time.perf_counter() - count_start) * 1000
        _set_cached_total_count(cache_key, int(total))
    if total is not None:
        total_pages = math.ceil(total / limit) if limit else 1

    cursor_sql = ''
    cursor_params: List[object] = []
    if cursor is not None and not use_offset:
        cursor_date, cursor_file, cursor_id = cursor
        operator = '<' if order == 'DESC' else '>'
        cursor_sql = f' AND (images.date, images.file, images.id) {operator} (?, ?, ?)'
        cursor_params = [cursor_date, cursor_file, cursor_id]

    split_relations = SPLIT_IMAGE_RELATION_LOADS if split_relations is None else bool(split_relations)
    load_relations = split_relations and not compact

    data_sql = (
        '''

        SELECT images.id, images.file, images.date, images.model, images.models, images.positive, images.negative,
               images.sampler, images.seed, images.steps, images.cfg,
               images.width, images.height, images.scheduler
        FROM images
        ''' + fsql + cursor_sql + f'''
        ORDER BY images.date {order}, images.file {order}, images.id {order}
        LIMIT ?
        '''
    )
    data_start = time.perf_counter() if perf_enabled else 0.0
    if use_offset:
        data_sql += ' OFFSET ?'
        cur.execute(data_sql, (*fparams, *cursor_params, limit, offset))
    else:
        cur.execute(data_sql, (*fparams, *cursor_params, limit))
    rows = cur.fetchall()
    if perf_enabled:
        data_ms = (time.perf_counter() - data_start) * 1000
    collections_by_file: Dict[str, List[str]] = {}
    loras_by_image: Dict[int, List[Dict[str, Any]]] = {}
    if load_relations and rows:
        chunk_size = 900
        image_ids = [row[0] for row in rows]
        image_files = [row[1] for row in rows]
        collection_sets: Dict[str, set[str]] = {}
        for i in range(0, len(image_files), chunk_size):
            chunk = image_files[i:i + chunk_size]
            placeholders = ','.join('?' for _ in chunk)
            cur.execute(
                '''
                SELECT ci.media_path, c.name
                FROM collection_items ci
                JOIN collections c ON ci.collection_id = c.id
                WHERE ci.media_path IN ({}) AND ci.media_type = 'image'
                '''.format(placeholders),
                chunk,
            )
            for media_path, name in cur.fetchall():
                if not media_path:
                    continue
                name_val = (name or '').strip()
                if not name_val:
                    continue
                collection_sets.setdefault(media_path, set()).add(name_val)
        collections_by_file = {path: sorted(names) for path, names in collection_sets.items()}

        for i in range(0, len(image_ids), chunk_size):
            chunk = image_ids[i:i + chunk_size]
            placeholders = ','.join('?' for _ in chunk)
            cur.execute(
                f'''
                SELECT image_id, name, strength
                FROM loras
                WHERE image_id IN ({placeholders})
                ''',
                chunk,
            )
            for image_id, name_raw, strength in cur.fetchall():
                name = (name_raw or '').strip()
                weight = None
                if strength is not None and str(strength) != '':
                    try:
                        weight = float(strength)
                    except (TypeError, ValueError):
                        weight = None
                if name or weight is not None:
                    loras_by_image.setdefault(int(image_id), []).append({'name': name, 'weight': weight})
    conn.close()

    results: List[Dict[str, Any]] = []
    transform_start = time.perf_counter() if perf_enabled else 0.0
    for row in rows:
        (
            image_id,
            file,
            date,
            model_val,
            models_raw,
            positive,
            negative,
            sampler_val,
            seed_val,
            steps_val,
            cfg_val,
            width_val,
            height_val,
            scheduler_val,
        ) = row
        collections_list = collections_by_file.get(file, [])
        lora_entries = loras_by_image.get(image_id, [])
        results.append({
            'id': image_id,
            'file': file,
            'date': date,
            'model': model_val,
            'models': _deserialize_models(models_raw),
            'positive': positive or '',
            'negative': negative or '',
            'sampler': sampler_val or '',
            'seed': seed_val,
            'steps': steps_val,
            'cfg': cfg_val,
            'width': width_val,
            'height': height_val,
            'scheduler': scheduler_val or '',
            'collections': collections_list,
            'loras': lora_entries,
        })

    next_cursor = None
    if rows:
        last_row = rows[-1]
        next_cursor = {
            'date': last_row[2],
            'file': last_row[1],
            'id': last_row[0],
        }
    if perf_enabled:
        transform_ms = (time.perf_counter() - transform_start) * 1000
        total_ms = (time.perf_counter() - overall_start) * 1000
        logger.info(
            "PERF DB search_images filter_ms=%.2f count_ms=%.2f data_ms=%.2f transform_ms=%.2f total_ms=%.2f "
            "limit=%s page=%s result_count=%s include_total=%s",
            filter_ms,
            count_ms,
            data_ms,
            transform_ms,
            total_ms,
            limit,
            page,
            len(results),
            include_total,
        )

    return {
        'results': results,
        'total_count': total,
        'total_pages': total_pages,
        'next_cursor': next_cursor,
    }


def get_search_total_count_with_meta(
    *,
    query: str = "",
    match_mode: str = "and",
    model: Optional[Any] = None,
    model_match: str = "and",
    sampler: Optional[str] = None,
    seed: Optional[int] = None,
    steps: Optional[int] = None,
    draft_mode: str = "exclude",
    collection_ids: Optional[List[int]] = None,
    collection_id: Optional[int] = None,
    collection_subtree_cache: Optional[Dict[int, List[int]]] = None,
    collection_match: str = "and",
    allow_defer: bool = False,
    tag_source: str = "prompt",
) -> Dict[str, object]:
    ensure_image_tables()
    ensure_collection_tables()
    ensure_videos_table()
    if (tag_source or "").lower() == "booru":
        ensure_booru_tables()
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    try:
        collection_groups = _resolve_collection_filter_ids(
            conn,
            collection_ids,
            collection_id=collection_id,
            collection_subtree_cache=collection_subtree_cache,
        )
        cache_key = _get_search_total_cache_key(
            query,
            match_mode,
            model,
            model_match,
            sampler,
            seed,
            steps,
            draft_mode,
            collection_groups,
            collection_match,
            tag_source,
        )
        cached = _get_cached_total_count(cache_key)
        if cached is not None:
            return {"total": cached, "cache_hit": True, "skipped": False, "skip_reason": None}
        if allow_defer and should_skip_total_count(
            query=query,
            model=model,
            sampler=sampler,
            seed=seed,
            steps=steps,
            collection_ids=collection_groups,
            draft_mode=draft_mode,
        ):
            return {
                "total": None,
                "cache_hit": False,
                "skipped": True,
                "skip_reason": "large_dataset_empty_query",
            }
        fsql, fparams = _build_filter_sql(
            query,
            match_mode,
            model,
            model_match,
            sampler,
            seed,
            steps,
            draft_mode,
            collection_groups,
            collection_match,
            exclude_video_thumbs=True,
            tag_source=tag_source,
        )
        count_sql = '''
            SELECT COUNT(*)
            FROM images
        '''
        cur.execute(count_sql + fsql, fparams)
        total = cur.fetchone()[0] or 0
        _set_cached_total_count(cache_key, int(total))
        return {"total": int(total), "cache_hit": False, "skipped": False, "skip_reason": None}
    finally:
        conn.close()


def get_search_total_count(
    *,
    query: str = "",
    match_mode: str = "and",
    model: Optional[Any] = None,
    model_match: str = "and",
    sampler: Optional[str] = None,
    seed: Optional[int] = None,
    steps: Optional[int] = None,
    draft_mode: str = "exclude",
    collection_ids: Optional[List[int]] = None,
    collection_id: Optional[int] = None,
    collection_subtree_cache: Optional[Dict[int, List[int]]] = None,
    collection_match: str = "and",
    allow_defer: bool = False,
    tag_source: str = "prompt",
) -> Optional[int]:
    meta = get_search_total_count_with_meta(
        query=query,
        match_mode=match_mode,
        model=model,
        model_match=model_match,
        sampler=sampler,
        seed=seed,
        steps=steps,
        draft_mode=draft_mode,
        collection_ids=collection_ids,
        collection_id=collection_id,
        collection_subtree_cache=collection_subtree_cache,
        collection_match=collection_match,
        allow_defer=allow_defer,
        tag_source=tag_source,
    )
    return meta["total"]


def search_images_cursor(
    query: str = '',
    match_mode: str = 'and',
    sort_order: str = 'desc',
    limit: int = 100,
    page: int = 1,
    model: Optional[Any] = None,
    model_match: str = "and",
    sampler: Optional[str] = None,
    seed: Optional[int] = None,
    steps: Optional[int] = None,
    draft_mode: str = 'exclude',
    collection_id: Optional[int] = None,
    collection_ids: Optional[List[int]] = None,
    *,
    collection_subtree_cache: Optional[Dict[int, List[int]]] = None,
    collection_match: str = "and",
    tag_source: str = "prompt",
) -> Dict[str, Any]:
    """Search only the last row for cursor pagination."""
    perf_enabled = PERF_LOGS
    overall_start = time.perf_counter() if perf_enabled else 0.0
    filter_ms = 0.0
    data_ms = 0.0
    transform_ms = 0.0

    ensure_collection_tables()
    ensure_videos_table()
    if (tag_source or "").lower() == "booru":
        ensure_booru_tables()
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    order = 'DESC' if str(sort_order).lower().startswith('d') else 'ASC'
    offset = max(0, (int(page) - 1) * max(1, int(limit)))
    limit = max(1, int(limit))

    collection_groups = _resolve_collection_filter_ids(
        conn,
        collection_ids,
        collection_id=collection_id,
        collection_subtree_cache=collection_subtree_cache,
    )

    filter_start = time.perf_counter() if perf_enabled else 0.0
    fsql, fparams = _build_filter_sql(
        query,
        match_mode,
        model,
        model_match,
        sampler,
        seed,
        steps,
        draft_mode,
        collection_groups,
        collection_match,
        exclude_video_thumbs=True,
        tag_source=tag_source,
    )
    if perf_enabled:
        filter_ms = (time.perf_counter() - filter_start) * 1000

    data_sql = (
        '''
        SELECT images.date, images.file, images.id
        FROM images
        ''' + fsql + f'''
        ORDER BY images.date {order}, images.file {order}, images.id {order}
        LIMIT ? OFFSET ?
        '''
    )
    data_start = time.perf_counter() if perf_enabled else 0.0
    cur.execute(data_sql, (*fparams, limit, offset))
    rows = cur.fetchall()
    if perf_enabled:
        data_ms = (time.perf_counter() - data_start) * 1000
    conn.close()

    next_cursor = None
    transform_start = time.perf_counter() if perf_enabled else 0.0
    if rows:
        last_row = rows[-1]
        next_cursor = {
            'date': last_row[0],
            'file': last_row[1],
            'id': last_row[2],
        }
    if perf_enabled:
        transform_ms = (time.perf_counter() - transform_start) * 1000
        total_ms = (time.perf_counter() - overall_start) * 1000
        logger.info(
            "PERF search_images_cursor filter_ms=%.2f data_ms=%.2f transform_ms=%.2f total_ms=%.2f "
            "limit=%s page=%s result_count=%s include_total=%s",
            filter_ms,
            data_ms,
            transform_ms,
            total_ms,
            limit,
            page,
            len(rows),
            False,
        )

    return {
        'results': [],
        'total_count': None,
        'total_pages': None,
        'next_cursor': next_cursor,
    }

def get_all_models() -> List[str]:
    """Return distinct model names as a simple list[str] for the UI dropdown."""
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute(
        '''
        SELECT DISTINCT TRIM(model) AS name
        FROM images
        WHERE model IS NOT NULL AND TRIM(model) <> ''
        UNION
        SELECT DISTINCT TRIM(model_checkpoint) AS name
        FROM images
        WHERE model_checkpoint IS NOT NULL AND TRIM(model_checkpoint) <> ''
        '''
    )
    rows = cur.fetchall()
    conn.close()
    models = [row[0] for row in rows if row and row[0]]
    return sorted(models, key=lambda x: x.lower())

def _build_recent_days_clause(recent_days: Optional[int], column: str) -> tuple[str, List[str]]:
    days = _safe_int(recent_days)
    if not days or days <= 0:
        return "", []
    return f" AND DATE({column}) >= DATE('now', ?)", [f"-{days} days"]

def get_model_usage_counts(recent_days: Optional[int] = None) -> List[Dict[str, Any]]:
    """Return model usage counts, optionally filtered by recent days."""
    ensure_image_tables()
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    date_clause, params = _build_recent_days_clause(recent_days, "images.date")
    cur.execute(
        f'''
        SELECT model, models
        FROM images
        WHERE (model IS NOT NULL AND TRIM(model) <> '')
           OR (models IS NOT NULL AND TRIM(models) <> '')
        {date_clause}
        ''',
        params,
    )
    rows = cur.fetchall()
    conn.close()
    counts: Dict[str, int] = {}
    for model_val, models_raw in rows:
        names = set(_deserialize_models(models_raw))
        if model_val and str(model_val).strip():
            names.add(str(model_val).strip())
        for name in names:
            counts[name] = counts.get(name, 0) + 1
    return [
        {"name": name, "count": count}
        for name, count in sorted(counts.items(), key=lambda item: (-item[1], item[0].lower()))
    ]

def get_lora_usage_counts(recent_days: Optional[int] = None) -> List[Dict[str, Any]]:
    """Return LoRA usage counts, optionally filtered by recent days."""
    ensure_image_tables()
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    days = _safe_int(recent_days)
    if days and days > 0:
        date_clause, params = _build_recent_days_clause(days, "images.date")
        cur.execute(
            f'''
            SELECT loras.name, COUNT(*) as cnt
            FROM loras
            JOIN images ON images.id = loras.image_id
            WHERE loras.name IS NOT NULL AND TRIM(loras.name) <> ''
            {date_clause}
            GROUP BY loras.name
            ORDER BY cnt DESC, loras.name COLLATE NOCASE ASC
            ''',
            params,
        )
    else:
        cur.execute(
            '''
            SELECT name, COUNT(*) as cnt
            FROM loras
            WHERE name IS NOT NULL AND TRIM(name) <> ''
            GROUP BY name
            ORDER BY cnt DESC, name COLLATE NOCASE ASC
            '''
        )
    rows = cur.fetchall()
    conn.close()
    return [{'name': name, 'count': cnt} for name, cnt in rows]

def get_all_tags_with_count(limit: int = 2000) -> List[Dict[str, Any]]:
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute(
        '''
        SELECT tag, COUNT(*) as cnt
        FROM tags
        WHERE tag IS NOT NULL AND TRIM(tag) <> ''
        GROUP BY tag
        ORDER BY cnt DESC
        LIMIT ?
        ''',
        (limit,),
    )
    rows = cur.fetchall()
    conn.close()
    return [{'tag': t, 'count': c} for (t, c) in rows]

def autocomplete_tags(prefix: str, limit: int = 10) -> List[str]:
    """Return tag suggestions starting with the given prefix (case-insensitive)."""
    prefix = (prefix or '').strip().replace('_', ' ').lower()
    if not prefix:
        return []
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute(
        '''
        SELECT tag, COUNT(*) as cnt
        FROM tags
        WHERE tag LIKE ?
        GROUP BY tag
        ORDER BY cnt DESC, tag ASC
        LIMIT ?
        ''',
        (f'{prefix}%', limit),
    )
    rows = cur.fetchall()
    conn.close()
    return [r[0] for r in rows]

def _to_rel_file_key(abs_or_rel: str) -> str:
    path = abs_or_rel or ''
    if DEST_FOLDER_NAME in path:
        tail = path.split(DEST_FOLDER_NAME, 1)[-1].lstrip('/\\')
        rel_path = os.path.join(DEST_FOLDER_NAME, tail)
    else:
        rel_path = path
    rel_norm = rel_path.replace('\\', '/')
    if rel_norm.lower().startswith(f"{DRAFTS_FOLDER_NAME.lower()}/") and DEST_FOLDER_NAME:
        rel_path = os.path.join(DEST_FOLDER_NAME, rel_norm)
    return rel_path.replace('\\', '/')


def _normalize_media_path(path: str) -> str:
    normalized = (path or '').replace('\\', '/').strip()
    if not normalized:
        return ''
    return _to_rel_file_key(normalized)


def normalize_media_path(media_path: str) -> str:
    """Public wrapper to normalize media paths for lookups."""
    return _normalize_media_path(media_path)

def _extract_date_from_rel(rel_path: str, default: str = 'unknown') -> str:
    """Extract YYYY-MM-DD from a DB relative path (supports legacy and new layouts)."""
    return extract_date_from_path(rel_path, default=default)


def _safe_int(value: Any) -> Optional[int]:
    """Convert value to int if possible, otherwise return None."""
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _safe_float(value: Any) -> Optional[float]:
    """Convert value to float if possible, otherwise return None."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _safe_text(value: Any) -> Optional[str]:
    """Ensure the value is a string or JSON representation."""
    if value is None or value == '':
        return None
    if isinstance(value, str):
        return value
    return json.dumps(value)

def _deserialize_models(value: Any) -> List[str]:
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        return [str(v).strip() for v in value if str(v).strip()]
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return []
        try:
            parsed = json.loads(stripped)
        except json.JSONDecodeError:
            return [stripped]
        if isinstance(parsed, list):
            return [str(v).strip() for v in parsed if str(v).strip()]
        if isinstance(parsed, str):
            return [parsed.strip()] if parsed.strip() else []
        return []
    return []

def save_tags_to_db(image_info: List[Dict[str, Any]]) -> int:
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    inserted = 0
    for item in image_info:
        raw_file = item.get('file', '')
        rel_path = _to_rel_file_key(raw_file)

        date = item.get('date') or _extract_date_from_rel(rel_path)
        model = (item.get('model') or '').strip()
        models_list = _deserialize_models(item.get('models'))
        if not model and models_list:
            model = models_list[0]
        if not models_list and model:
            models_list = [model]
        positive = (item.get('positive') or '').strip()
        negative = (item.get('negative') or '').strip()

        width = _safe_int(item.get('width'))
        height = _safe_int(item.get('height'))
        created = _safe_text(item.get('created'))
        seed = _safe_text(item.get('seed'))
        steps = _safe_int(item.get('steps'))
        cfg = _safe_float(item.get('cfg'))
        sampler = _safe_text(item.get('sampler'))
        scheduler = _safe_text(item.get('scheduler'))
        denoise = _safe_float(item.get('denoise'))
        model_checkpoint = _safe_text(item.get('model_checkpoint'))
        models = _safe_text(models_list or item.get('models'))
        vae_name = _safe_text(item.get('vae_name'))
        workflow_id = _safe_text(item.get('workflow_id'))
        node_count = _safe_int(item.get('node_count'))
        guidance = _safe_float(item.get('guidance'))
        extras = _safe_text(item.get('extras'))
        loras = item.get('loras', []) or []

        tags_pos = item.get('tags_positive', []) or []
        tags_neg = item.get('tags_negative', []) or []
        tags_legacy = item.get('tags', []) or []
        merged_tags: List[str] = []
        for t in [*tags_pos, *tags_neg, *tags_legacy]:
            t = (t or '').strip()
            if t:
                merged_tags.append(t.replace('_', ' ').lower())  # store lowercase
        merged_tags = filter_tags(merged_tags)
        seen_tags = set()
        deduped_tags: List[str] = []
        for tag in merged_tags:
            if tag in seen_tags:
                continue
            seen_tags.add(tag)
            deduped_tags.append(tag)
        merged_tags = deduped_tags

        needs_update = False
        conn.execute('SAVEPOINT image_upsert')
        try:
            cur.execute(
                '''
                INSERT INTO images(
                    file, date, model, models, positive, negative,
                    width, height, created, seed, steps, cfg, sampler, scheduler,
                    denoise, model_checkpoint, vae_name, workflow_id, node_count,
                    guidance, extras
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                ''',
                (
                    rel_path,
                    date,
                    model,
                    models,
                    positive,
                    negative,
                    width,
                    height,
                    created,
                    seed,
                    steps,
                    cfg,
                    sampler,
                    scheduler,
                    denoise,
                    model_checkpoint,
                    vae_name,
                    workflow_id,
                    node_count,
                    guidance,
                    extras,
                ),
            )
            conn.execute('RELEASE SAVEPOINT image_upsert')
            image_id = cur.lastrowid
            inserted += 1
        except sqlite3.IntegrityError:
            conn.execute('ROLLBACK TO SAVEPOINT image_upsert')
            conn.execute('RELEASE SAVEPOINT image_upsert')
            row = None
            for _ in range(5):
                cur.execute('SELECT id FROM images WHERE file = ?', (rel_path,))
                row = cur.fetchone()
                if row:
                    break
                time.sleep(0.05)
            if not row:
                raise sqlite3.IntegrityError(f'이미지를 다시 조회할 수 없습니다: {rel_path}')
            image_id = row[0]
            needs_update = True
        except Exception:
            conn.execute('ROLLBACK TO SAVEPOINT image_upsert')
            conn.execute('RELEASE SAVEPOINT image_upsert')
            raise

        if needs_update:
            cur.execute(
                '''
                UPDATE images SET date=?, model=?, models=?, positive=?, negative=?,
                    width=?, height=?, created=?, seed=?, steps=?, cfg=?, sampler=?,
                    scheduler=?, denoise=?, model_checkpoint=?, vae_name=?,
                    workflow_id=?, node_count=?, guidance=?, extras=?
                WHERE id=?
                ''',
                (
                    date,
                    model,
                    models,
                    positive,
                    negative,
                    width,
                    height,
                    created,
                    seed,
                    steps,
                    cfg,
                    sampler,
                    scheduler,
                    denoise,
                    model_checkpoint,
                    vae_name,
                    workflow_id,
                    node_count,
                    guidance,
                    extras,
                    image_id,
                ),
            )
            cur.execute('DELETE FROM tags WHERE image_id = ?', (image_id,))
            cur.execute('DELETE FROM loras WHERE image_id = ?', (image_id,))

        for tg in merged_tags:
            cur.execute(
                'INSERT OR IGNORE INTO tags(image_id, tag) VALUES (?, ?)',
                (image_id, tg),
            )

        for lora in loras:
            name = (lora.get('name') or '').strip()
            strength = lora.get('strength')
            if name:
                cur.execute(
                    'INSERT INTO loras(image_id, name, strength) VALUES (?, ?, ?)',
                    (image_id, name, strength),
                )

    conn.commit()
    conn.close()
    return inserted

def remove_image_from_db(file_path: str) -> None:
    rel_key = _to_rel_file_key(file_path)
    if not rel_key:
        return
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    delete_item_tags("image", rel_key, conn=conn)
    delete_item_ratings("image", rel_key, conn=conn)
    cur.execute(
        "DELETE FROM collection_items WHERE media_path = ? AND media_type = 'image'",
        (rel_key,),
    )
    cur.execute('SELECT id FROM images WHERE file = ?', (rel_key,))
    row = cur.fetchone()
    if row:
        image_id = row[0]
        cur.execute('DELETE FROM tags WHERE image_id = ?', (image_id,))
        cur.execute('DELETE FROM loras WHERE image_id = ?', (image_id,))
        cur.execute('DELETE FROM images WHERE id = ?', (image_id,))
    conn.commit()
    conn.close()


def list_collections() -> List[Dict[str, Any]]:
    ensure_collection_tables()
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute(
        '''
        SELECT c.id, c.name, c.parent_id, c.created_at, COUNT(ci.id) AS item_count
        FROM collections c
        LEFT JOIN collection_items ci ON c.id = ci.collection_id
        GROUP BY c.id
        ORDER BY c.created_at DESC, c.id DESC
        '''
    )
    rows = cur.fetchall()
    conn.close()
    return [
        {
            "id": cid,
            "name": name,
            "parent_id": parent_id,
            "created_at": created_at,
            "item_count": item_count or 0,
        }
        for (cid, name, parent_id, created_at, item_count) in rows
    ]


def list_model_categories() -> List[Dict[str, Any]]:
    ensure_model_category_tables()
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute(
        '''
        SELECT mc.id, mc.name, mc.parent_id, mc.created_at, COUNT(mci.id) AS model_count
        FROM model_categories mc
        LEFT JOIN model_category_items mci ON mc.id = mci.category_id
        GROUP BY mc.id
        ORDER BY mc.created_at DESC, mc.id DESC
        '''
    )
    rows = cur.fetchall()
    conn.close()
    return [
        {
            "id": cid,
            "name": name,
            "parent_id": parent_id,
            "created_at": created_at,
            "model_count": model_count or 0,
        }
        for (cid, name, parent_id, created_at, model_count) in rows
    ]


def get_model_category(category_id: int) -> Optional[Dict[str, Any]]:
    ensure_model_category_tables()
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute(
        'SELECT id, name, parent_id, created_at FROM model_categories WHERE id = ?',
        (int(category_id),),
    )
    row = cur.fetchone()
    conn.close()
    if not row:
        return None
    return {"id": row[0], "name": row[1], "parent_id": row[2], "created_at": row[3]}


def get_collection(collection_id: int) -> Optional[Dict[str, Any]]:
    ensure_collection_tables()
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute(
        'SELECT id, name, parent_id, created_at FROM collections WHERE id = ?',
        (int(collection_id),),
    )
    row = cur.fetchone()
    conn.close()
    if not row:
        return None
    return {"id": row[0], "name": row[1], "parent_id": row[2], "created_at": row[3]}


def _normalize_parent_id(parent_id: Optional[int]) -> Optional[int]:
    if parent_id is None:
        return None
    try:
        pid = int(parent_id)
    except (TypeError, ValueError):
        return None
    return pid if pid > 0 else None


def create_collection(name: str, parent_id: Optional[int] = None) -> int:
    ensure_collection_tables()
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    pid = _normalize_parent_id(parent_id)
    if pid:
        cur.execute('SELECT 1 FROM collections WHERE id = ?', (pid,))
        if not cur.fetchone():
            conn.close()
            raise ValueError('부모 컬렉션을 찾을 수 없습니다.')
    try:
        cur.execute(
            'INSERT INTO collections(name, parent_id) VALUES (?, ?)',
            ((name or '').strip(), pid),
        )
        conn.commit()
        return cur.lastrowid
    except sqlite3.IntegrityError as exc:
        conn.rollback()
        raise ValueError('같은 부모 아래에 동일한 이름의 모음집이 이미 있습니다.') from exc
    finally:
        conn.close()


def rename_collection(
    collection_id: int,
    new_name: str,
    parent_id: Optional[int] = None,
    *,
    update_parent: bool = False,
) -> bool:
    ensure_collection_tables()
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    pid = _normalize_parent_id(parent_id)
    if pid == collection_id:
        conn.close()
        raise ValueError('자기 자신을 부모로 설정할 수 없습니다.')
    if pid:
        cur.execute('SELECT 1 FROM collections WHERE id = ?', (pid,))
        if not cur.fetchone():
            conn.close()
            raise ValueError('부모 컬렉션을 찾을 수 없습니다.')
    params: List[Any] = [(new_name or '').strip()]
    sql = 'UPDATE collections SET name = ?'
    if update_parent:
        sql += ', parent_id = ?'
        params.append(pid)
    sql += ' WHERE id = ?'
    params.append(int(collection_id))
    try:
        cur.execute(sql, tuple(params))
        conn.commit()
        return cur.rowcount > 0
    except sqlite3.IntegrityError as exc:
        conn.rollback()
        raise ValueError('같은 부모 아래에 동일한 이름의 모음집이 이미 있습니다.') from exc
    finally:
        conn.close()


def delete_collection(collection_id: int) -> bool:
    ensure_collection_tables()
    conn = sqlite3.connect(DB_PATH)
    conn.execute('PRAGMA foreign_keys=ON')
    cur = conn.cursor()
    cur.execute('DELETE FROM collections WHERE id = ?', (int(collection_id),))
    conn.commit()
    removed = cur.rowcount > 0
    conn.close()
    return removed


def create_model_category(name: str, parent_id: Optional[int] = None) -> int:
    ensure_model_category_tables()
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    pid = _normalize_parent_id(parent_id)
    if pid:
        cur.execute('SELECT 1 FROM model_categories WHERE id = ?', (pid,))
        if not cur.fetchone():
            conn.close()
            raise ValueError('부모 카테고리를 찾을 수 없습니다.')
    try:
        cur.execute(
            'INSERT INTO model_categories(name, parent_id) VALUES (?, ?)',
            ((name or '').strip(), pid),
        )
        conn.commit()
        return cur.lastrowid
    except sqlite3.IntegrityError as exc:
        conn.rollback()
        raise ValueError('같은 부모 아래에 동일한 이름의 카테고리가 이미 있습니다.') from exc
    finally:
        conn.close()


def rename_model_category(
    category_id: int,
    new_name: str,
    parent_id: Optional[int] = None,
    *,
    update_parent: bool = False,
) -> bool:
    ensure_model_category_tables()
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    pid = _normalize_parent_id(parent_id)
    if pid == category_id:
        conn.close()
        raise ValueError('카테고리를 자기 자신 아래로 이동할 수 없습니다.')
    if update_parent and pid:
        cur.execute('SELECT 1 FROM model_categories WHERE id = ?', (pid,))
        if not cur.fetchone():
            conn.close()
            raise ValueError('부모 카테고리를 찾을 수 없습니다.')
    params: List[Any] = [(new_name or '').strip()]
    sql = 'UPDATE model_categories SET name = ?'
    if update_parent:
        sql += ', parent_id = ?'
        params.append(pid)
    sql += ' WHERE id = ?'
    params.append(int(category_id))
    try:
        cur.execute(sql, tuple(params))
        conn.commit()
        return (cur.rowcount or 0) > 0
    except sqlite3.IntegrityError as exc:
        conn.rollback()
        raise ValueError('같은 부모 아래에 동일한 이름의 카테고리가 이미 있습니다.') from exc
    finally:
        conn.close()


def delete_model_category(category_id: int) -> bool:
    ensure_model_category_tables()
    conn = sqlite3.connect(DB_PATH)
    conn.execute('PRAGMA foreign_keys=ON')
    cur = conn.cursor()
    cur.execute('DELETE FROM model_categories WHERE id = ?', (int(category_id),))
    conn.commit()
    removed = (cur.rowcount or 0) > 0
    conn.close()
    return removed


def get_model_category_children(parent_id: Optional[int] = None) -> List[Dict[str, Any]]:
    ensure_model_category_tables()
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    if parent_id is None:
        cur.execute(
            'SELECT id, name, parent_id, created_at FROM model_categories '
            'WHERE parent_id IS NULL ORDER BY name'
        )
    else:
        cur.execute(
            'SELECT id, name, parent_id, created_at FROM model_categories '
            'WHERE parent_id = ? ORDER BY name',
            (int(parent_id),),
        )
    rows = cur.fetchall()
    conn.close()
    return [
        {"id": cid, "name": name, "parent_id": pid, "created_at": created_at}
        for (cid, name, pid, created_at) in rows
    ]


def build_model_category_tree(categories: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    nodes = {c["id"]: {**c, "children": []} for c in categories}
    roots: List[Dict[str, Any]] = []
    for node in nodes.values():
        pid = node.get("parent_id")
        if pid and pid in nodes and pid != node["id"]:
            nodes[pid]["children"].append(node)
        else:
            roots.append(node)
    for node in nodes.values():
        node["children"].sort(key=lambda x: (x.get("name") or "").lower())
    roots.sort(key=lambda x: (x.get("name") or "").lower())
    return roots


def get_model_category_tree() -> List[Dict[str, Any]]:
    return build_model_category_tree(list_model_categories())


def get_subtree_model_category_ids(
    conn: sqlite3.Connection,
    root_id: int,
    *,
    cache: Optional[Dict[int, List[int]]] = None,
) -> List[int]:
    ensure_model_category_tables(conn=conn)
    cid = int(root_id)
    if cache is not None and cid in cache:
        return cache[cid]
    cur = conn.cursor()
    cur.execute(
        """
        WITH RECURSIVE sub(id) AS (
            SELECT id FROM model_categories WHERE id = ?
            UNION ALL
            SELECT c.id FROM model_categories c
            JOIN sub s ON c.parent_id = s.id
        )
        SELECT id FROM sub;
        """,
        (cid,),
    )
    ids = [row[0] for row in cur.fetchall()]
    if cache is not None:
        cache[cid] = ids
    return ids


def get_model_category_models(
    category_id: int,
    *,
    conn: Optional[sqlite3.Connection] = None,
    subtree_cache: Optional[Dict[int, List[int]]] = None,
) -> List[str]:
    ensure_model_category_tables(conn=conn)
    close_conn = False
    if conn is None:
        conn = sqlite3.connect(DB_PATH)
        close_conn = True
    ids = get_subtree_model_category_ids(conn, int(category_id), cache=subtree_cache)
    if not ids:
        if close_conn:
            conn.close()
        return []
    placeholders = ','.join(['?'] * len(ids))
    cur = conn.cursor()
    cur.execute(
        f'''
        SELECT DISTINCT model_name
        FROM model_category_items
        WHERE category_id IN ({placeholders})
        ORDER BY model_name COLLATE NOCASE ASC
        ''',
        ids,
    )
    models = [row[0] for row in cur.fetchall()]
    if close_conn:
        conn.close()
    return models


def assign_model_to_category(model_name: str, category_id: int) -> bool:
    ensure_model_category_tables()
    normalized = (model_name or '').strip()
    if not normalized:
        return False
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute('SELECT 1 FROM model_categories WHERE id = ?', (int(category_id),))
    if not cur.fetchone():
        conn.close()
        raise ValueError('카테고리를 찾을 수 없습니다.')
    cur.execute(
        'INSERT OR IGNORE INTO model_category_items(category_id, model_name) VALUES (?, ?)',
        (int(category_id), normalized),
    )
    inserted = (cur.rowcount or 0) > 0
    conn.commit()
    conn.close()
    return inserted


def remove_model_from_category(category_id: int, model_name: str) -> bool:
    ensure_model_category_tables()
    normalized = (model_name or '').strip()
    if not normalized:
        return False
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute(
        'DELETE FROM model_category_items WHERE category_id = ? AND model_name = ?',
        (int(category_id), normalized),
    )
    deleted = (cur.rowcount or 0) > 0
    conn.commit()
    conn.close()
    return deleted


def get_model_category_items(category_id: int) -> List[Dict[str, Any]]:
    ensure_model_category_tables()
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute(
        'SELECT model_name FROM model_category_items WHERE category_id = ? '
        'ORDER BY model_name COLLATE NOCASE ASC',
        (int(category_id),),
    )
    rows = cur.fetchall()
    conn.close()
    return [{"model_name": row[0]} for row in rows]


def get_collection_children(parent_id: Optional[int] = None) -> List[Dict[str, Any]]:
    ensure_collection_tables()
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    if parent_id is None:
        cur.execute(
            'SELECT id, name, parent_id, created_at FROM collections WHERE parent_id IS NULL ORDER BY name'
        )
    else:
        cur.execute(
            'SELECT id, name, parent_id, created_at FROM collections WHERE parent_id = ? ORDER BY name',
            (int(parent_id),),
        )
    rows = cur.fetchall()
    conn.close()
    return [
        {"id": cid, "name": name, "parent_id": pid, "created_at": created_at}
        for (cid, name, pid, created_at) in rows
    ]


def build_collection_tree(collections: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    nodes = {c["id"]: {**c, "children": []} for c in collections}
    roots: List[Dict[str, Any]] = []
    for node in nodes.values():
        pid = node.get("parent_id")
        if pid and pid in nodes and pid != node["id"]:
            nodes[pid]["children"].append(node)
        else:
            roots.append(node)
    for node in nodes.values():
        node["children"].sort(key=lambda x: (x.get("name") or "").lower())
    roots.sort(key=lambda x: (x.get("name") or "").lower())

    def _accumulate_counts(node: Dict[str, Any]) -> int:
        total = int(node.get("item_count") or 0)
        for child in node.get("children") or []:
            total += _accumulate_counts(child)
        node["total_item_count"] = total
        return total

    for root in roots:
        _accumulate_counts(root)
    return roots


def get_collection_tree() -> List[Dict[str, Any]]:
    return build_collection_tree(list_collections())


def get_subtree_collection_ids(
    conn: sqlite3.Connection,
    root_id: int,
    *,
    cache: Optional[Dict[int, List[int]]] = None,
) -> List[int]:
    ensure_collection_tables(conn=conn)
    cid = int(root_id)
    if cache is not None and cid in cache:
        return cache[cid]
    cur = conn.cursor()
    cur.execute(
        """
        WITH RECURSIVE sub(id) AS (
            SELECT id FROM collections WHERE id = ?
            UNION ALL
            SELECT c.id FROM collections c
            JOIN sub s ON c.parent_id = s.id
        )
        SELECT id FROM sub;
        """,
        (cid,),
    )
    ids = [row[0] for row in cur.fetchall()]
    if cache is not None:
        cache[cid] = ids
    return ids


def get_ancestor_ids(conn: sqlite3.Connection, collection_id: int) -> List[int]:
    ensure_collection_tables(conn=conn)
    cur = conn.cursor()
    ancestors: List[int] = []
    cid = int(collection_id)
    guard = 0
    while cid is not None and guard < 1024:
        cur.execute('SELECT parent_id FROM collections WHERE id = ?', (cid,))
        row = cur.fetchone()
        if not row:
            break
        pid = row[0]
        if pid is None:
            break
        ancestors.append(int(pid))
        cid = pid
        guard += 1
    return ancestors


def add_item_to_collection(collection_id: int, media_path: str, media_type: str = 'image') -> bool:
    ensure_collection_tables()
    normalized_path = _normalize_media_path(media_path)
    if not normalized_path:
        return False
    conn = sqlite3.connect(DB_PATH)
    conn.execute('PRAGMA foreign_keys=ON')
    cur = conn.cursor()
    normalized_type = (media_type or 'image').lower()
    cur.execute(
        'INSERT OR IGNORE INTO collection_items(collection_id, media_path, media_type) VALUES (?, ?, ?)',
        (int(collection_id), normalized_path, normalized_type),
    )
    inserted = (cur.rowcount or 0) > 0
    deleted = 0
    ancestor_ids = get_ancestor_ids(conn, int(collection_id))
    if ancestor_ids:
        placeholders = ','.join(['?'] * len(ancestor_ids))
        cur.execute(
            f'''
            DELETE FROM collection_items
            WHERE media_path = ?
              AND media_type = ?
              AND collection_id IN ({placeholders})
            ''',
            (normalized_path, normalized_type, *ancestor_ids),
        )
        deleted = (cur.rowcount or 0)
    conn.commit()
    conn.close()
    return inserted or (deleted > 0)


def remove_item_from_collection(collection_id: int, media_path: str) -> bool:
    ensure_collection_tables()
    normalized_path = _normalize_media_path(media_path)
    if not normalized_path:
        return False
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute(
        'DELETE FROM collection_items WHERE collection_id = ? AND media_path = ?',
        (int(collection_id), normalized_path),
    )
    conn.commit()
    removed = cur.rowcount > 0
    conn.close()
    return removed


def remove_items_from_collection(collection_id: int, media_paths: List[str]) -> Dict[str, Any]:
    """Remove multiple media paths from a collection at once.

    Returns a summary dict with removed/missing paths and invalid inputs.
    """
    ensure_collection_tables()
    normalized: List[str] = []
    invalid: List[str] = []
    for path in media_paths:
        norm = _normalize_media_path(path)
        if norm:
            normalized.append(norm)
        else:
            invalid.append(path)

    # Deduplicate while preserving order
    seen = set()
    unique_paths: List[str] = []
    for path in normalized:
        if path in seen:
            continue
        seen.add(path)
        unique_paths.append(path)

    if not unique_paths:
        return {
            "removed_count": 0,
            "removed_paths": [],
            "missing_paths": [],
            "invalid_count": len(invalid),
        }

    placeholders = ','.join(['?'] * len(unique_paths))
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    cur.execute(
        f'SELECT media_path FROM collection_items WHERE collection_id = ? AND media_path IN ({placeholders})',
        (int(collection_id), *unique_paths),
    )
    existing_rows = {row[0] for row in cur.fetchall()}

    cur.execute(
        f'DELETE FROM collection_items WHERE collection_id = ? AND media_path IN ({placeholders})',
        (int(collection_id), *unique_paths),
    )
    conn.commit()
    removed_count = cur.rowcount
    conn.close()

    missing_paths = [path for path in unique_paths if path not in existing_rows]

    return {
        "removed_count": removed_count,
        "removed_paths": list(existing_rows),
        "missing_paths": missing_paths,
        "invalid_count": len(invalid),
    }


def count_collection_items(
    collection_id: Optional[int] = None,
    media_type: Optional[str] = None,
    *,
    collection_ids: Optional[List[int]] = None,
    collection_subtree_cache: Optional[Dict[int, List[int]]] = None,
    collection_match: str = "and",
) -> int:
    perf_enabled = PERF_LOGS
    overall_start = time.perf_counter() if perf_enabled else 0.0
    filter_ms = 0.0
    count_ms = 0.0
    transform_ms = 0.0

    ensure_collection_tables()
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    filter_start = time.perf_counter() if perf_enabled else 0.0
    collection_groups = _resolve_collection_filter_ids(
        conn,
        collection_ids,
        collection_id=collection_id,
        collection_subtree_cache=collection_subtree_cache,
    )
    if not collection_groups:
        conn.close()
        if perf_enabled:
            filter_ms = (time.perf_counter() - filter_start) * 1000
            total_ms = (time.perf_counter() - overall_start) * 1000
            logger.info(
                "PERF count_collection_items filter_ms=%.2f count_ms=%.2f transform_ms=%.2f total_ms=%.2f "
                "limit=%s page=%s result_count=%s include_total=%s",
                filter_ms,
                count_ms,
                transform_ms,
                total_ms,
                0,
                1,
                0,
                False,
            )
        return 0
    params: List[Any] = []
    sql = 'SELECT COUNT(DISTINCT ci.media_path) FROM collection_items ci WHERE 1=1'
    media_type_value = (media_type or '').lower() if media_type else None
    if media_type_value:
        sql += ' AND ci.media_type = ?'
        params.append(media_type_value)
    collection_logic = "or" if str(collection_match).lower() == "or" else "and"
    if collection_logic == "or":
        clauses = []
        for group in collection_groups:
            if not group:
                clauses.append('0')
                continue
            placeholders = ','.join(['?'] * len(group))
            clause = (
                'EXISTS('
                f'SELECT 1 FROM collection_items ci2 WHERE ci2.media_path = ci.media_path '
                f'AND ci2.collection_id IN ({placeholders})'
            )
            if media_type_value:
                clause += ' AND ci2.media_type = ?'
            clause += ')'
            clauses.append(clause)
            params.extend(group)
            if media_type_value:
                params.append(media_type_value)
        sql += ' AND (' + ' OR '.join(clauses) + ')'
    else:
        for group in collection_groups:
            if not group:
                sql += ' AND 0'
                continue
            placeholders = ','.join(['?'] * len(group))
            exists_clause = (
                ' AND EXISTS('
                f'SELECT 1 FROM collection_items ci2 WHERE ci2.media_path = ci.media_path '
                f'AND ci2.collection_id IN ({placeholders})'
            )
            if media_type_value:
                exists_clause += ' AND ci2.media_type = ?'
            exists_clause += ')'
            sql += exists_clause
            params.extend(group)
            if media_type_value:
                params.append(media_type_value)
    if perf_enabled:
        filter_ms = (time.perf_counter() - filter_start) * 1000
    count_start = time.perf_counter() if perf_enabled else 0.0
    cur.execute(sql, params)
    (count,) = cur.fetchone()
    if perf_enabled:
        count_ms = (time.perf_counter() - count_start) * 1000
    conn.close()
    transform_start = time.perf_counter() if perf_enabled else 0.0
    result = int(count or 0)
    if perf_enabled:
        transform_ms = (time.perf_counter() - transform_start) * 1000
        total_ms = (time.perf_counter() - overall_start) * 1000
        logger.info(
            "PERF count_collection_items filter_ms=%.2f count_ms=%.2f transform_ms=%.2f total_ms=%.2f "
            "limit=%s page=%s result_count=%s include_total=%s",
            filter_ms,
            count_ms,
            transform_ms,
            total_ms,
            0,
            1,
            result,
            False,
        )
    return result


def query_collection_videos(
    collection_id: Optional[int] = None,
    page: int = 1,
    limit: int = 60,
    sort_order: str = 'desc',
    *,
    collection_ids: Optional[List[int]] = None,
    collection_subtree_cache: Optional[Dict[int, List[int]]] = None,
    collection_match: str = "and",
) -> List[Dict[str, Any]]:
    perf_enabled = PERF_LOGS
    overall_start = time.perf_counter() if perf_enabled else 0.0
    filter_ms = 0.0
    data_ms = 0.0
    transform_ms = 0.0

    ensure_collection_tables()
    ensure_videos_table()
    limit = max(1, int(limit))
    offset = max(0, (int(page) - 1) * limit)
    order = 'DESC' if str(sort_order).lower().startswith('d') else 'ASC'

    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    filter_start = time.perf_counter() if perf_enabled else 0.0
    collection_groups = _resolve_collection_filter_ids(
        conn,
        collection_ids,
        collection_id=collection_id,
        collection_subtree_cache=collection_subtree_cache,
    )
    if not collection_groups:
        conn.close()
        if perf_enabled:
            filter_ms = (time.perf_counter() - filter_start) * 1000
            total_ms = (time.perf_counter() - overall_start) * 1000
            logger.info(
                "PERF DB query_collection_videos filter_ms=%.2f data_ms=%.2f transform_ms=%.2f total_ms=%.2f "
                "limit=%s page=%s result_count=%s include_total=%s",
                filter_ms,
                data_ms,
                transform_ms,
                total_ms,
                limit,
                page,
                0,
                False,
            )
        return []
    params: List[Any] = []
    clauses: List[str] = []
    collection_logic = "or" if str(collection_match).lower() == "or" else "and"
    for group in collection_groups:
        if not group:
            clauses.append('0')
            continue
        placeholders = ','.join(['?'] * len(group))
        clauses.append(
            'EXISTS('
            f'SELECT 1 FROM collection_items ci '
            f'WHERE ci.media_path = ? || \'/\' || v.rel_video '
            f"AND ci.media_type = 'video' AND ci.collection_id IN ({placeholders})"
            ')'
        )
        params.append(DEST_FOLDER_NAME)
        params.extend(group)
    joiner = ' OR ' if collection_logic == "or" else ' AND '
    collection_sql = ' AND (' + joiner.join(clauses) + ')' if clauses else ''
    if perf_enabled:
        filter_ms = (time.perf_counter() - filter_start) * 1000
    data_start = time.perf_counter() if perf_enabled else 0.0
    cur.execute(
        f'''
        SELECT v.rel_video, v.rel_thumb, v.date, v.mtime, v.size, v.prompt, v.negative, v.sampler, v.cfg, v.seed, v.width, v.height, v.sound
        FROM videos v
        WHERE 1=1 {collection_sql}
        ORDER BY v.mtime {order}
        LIMIT ? OFFSET ?
        ''',
        (*params, limit, offset),
    )
    rows = cur.fetchall()
    if perf_enabled:
        data_ms = (time.perf_counter() - data_start) * 1000
    conn.close()

    items: List[Dict[str, Any]] = []
    transform_start = time.perf_counter() if perf_enabled else 0.0
    for rel_v, rel_t, date_part, mtime, size, prompt, negative, sampler, cfg, seed, width, height, sound in rows:
        thumb_rel = f"{DEST_FOLDER_NAME}/{rel_t}" if rel_t else f"{DEST_FOLDER_NAME}/{os.path.splitext(rel_v)[0] + '.png'}"
        meta = {
            'prompt': prompt or '',
            'negative': negative or '',
            'sampler': sampler or '',
            'cfg': cfg,
            'seed': seed,
            'width': width,
            'height': height,
        }
        items.append({
            'video_rel': f"{DEST_FOLDER_NAME}/{rel_v}",
            'thumb_rel': thumb_rel,
            'rel_thumb': thumb_rel,
            'date': date_part,
            'mtime': mtime,
            'size': size,
            'prompt': prompt or '',
            'negative': negative or '',
            'sampler': sampler or '',
            'cfg': cfg,
            'seed': seed,
            'width': width,
            'height': height,
            'sound': sound or '',
            'meta': meta,
        })
    if perf_enabled:
        transform_ms = (time.perf_counter() - transform_start) * 1000
        total_ms = (time.perf_counter() - overall_start) * 1000
        logger.info(
            "PERF DB query_collection_videos filter_ms=%.2f data_ms=%.2f transform_ms=%.2f total_ms=%.2f "
            "limit=%s page=%s result_count=%s include_total=%s",
            filter_ms,
            data_ms,
            transform_ms,
            total_ms,
            limit,
            page,
            len(items),
            False,
        )
    return items


def get_collection_items(collection_id: int, media_type: Optional[str] = None) -> List[Dict[str, Any]]:
    ensure_collection_tables()
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    params: List[Any] = [int(collection_id)]
    sql = 'SELECT media_path, media_type FROM collection_items WHERE collection_id = ?'
    if media_type:
        sql += ' AND media_type = ?'
        params.append((media_type or '').lower())
    sql += ' ORDER BY id DESC'
    cur.execute(sql, params)
    rows = cur.fetchall()
    conn.close()
    return [{"media_path": path, "media_type": mtype} for (path, mtype) in rows]


def get_collections_by_paths(media_paths: List[str]) -> Dict[str, List[Dict[str, Any]]]:
    """Return mapping of normalized media_path -> collection metadata list for given paths."""
    ensure_collection_tables()
    normalized: List[str] = []
    for p in media_paths:
        norm = normalize_media_path(p)
        if norm:
            normalized.append(norm)
    if not normalized:
        return {}

    placeholders = ','.join(['?'] * len(normalized))
    sql = f'''
        SELECT ci.media_path, c.id, c.name, c.parent_id
        FROM collection_items ci
        JOIN collections c ON ci.collection_id = c.id
        WHERE ci.media_path IN ({placeholders})
    '''

    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute(sql, normalized)
    rows = cur.fetchall()
    conn.close()

    mapping: Dict[str, List[Dict[str, Any]]] = {}
    for media_path, cid, name, parent_id in rows:
        mapping.setdefault(media_path, []).append(
            {
                "id": int(cid) if cid is not None else None,
                "name": name,
                "parent_id": int(parent_id) if parent_id is not None else None,
            }
        )
    return mapping

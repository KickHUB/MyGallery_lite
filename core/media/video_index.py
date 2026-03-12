
from __future__ import annotations

import json
import os
import sqlite3
import time
import logging
from pathlib import Path
import threading
from typing import List, Dict, Any, Optional

from settings import DB_PATH, DEST, DEST_FOLDER_NAME, DRAFTS_FOLDER_NAME, PERF_LOGS
from core.media.gallery_layout import find_date_in_parts
from core.tagging.tag_utils import extract_prompt_from_file
from core.booru.booru_item_tags import delete_item_ratings, delete_item_tags
from core.media.video_meta import detect_video_sound

VIDEO_EXTS = (".mp4", ".webm", ".mov", ".avi", ".mkv", ".gif")
_videos_table_ready = False
_videos_db_path: Optional[str] = None
_video_table_lock = threading.RLock()
logger = logging.getLogger(__name__)

def _normalize_keywords(query: str) -> List[str]:
    return [kw.strip().replace('_', ' ') for kw in query.split(',') if kw.strip()]


def videos_count(query: str = "", match_mode: str = "and") -> int:
    perf_enabled = PERF_LOGS
    overall_start = time.perf_counter() if perf_enabled else 0.0
    filter_ms = 0.0
    query_ms = 0.0
    serialize_ms = 0.0

    ensure_videos_table()
    filter_start = time.perf_counter() if perf_enabled else 0.0
    keywords = _normalize_keywords(query or "")
    conn = _connect()
    cur = conn.cursor()
    sql = "SELECT COUNT(*) FROM videos"
    params: List[Any] = []
    if keywords:
        clauses = []
        for kw in keywords:
            clauses.append("(COALESCE(prompt, '') LIKE ? OR COALESCE(negative, '') LIKE ?)")
            params.extend([f"%{kw}%", f"%{kw}%"])
        joiner = " OR " if str(match_mode).lower() == "or" else " AND "
        sql += " WHERE " + joiner.join(clauses)
    if perf_enabled:
        filter_ms = (time.perf_counter() - filter_start) * 1000
    query_start = time.perf_counter() if perf_enabled else 0.0
    cur.execute(sql, params)
    (n,) = cur.fetchone()
    if perf_enabled:
        query_ms = (time.perf_counter() - query_start) * 1000
    conn.close()
    serialize_start = time.perf_counter() if perf_enabled else 0.0
    result = n or 0
    if perf_enabled:
        serialize_ms = (time.perf_counter() - serialize_start) * 1000
        total_ms = (time.perf_counter() - overall_start) * 1000
        logger.info(
            "PERF DB videos_count filter_ms=%.2f query_ms=%.2f serialize_ms=%.2f total_ms=%.2f "
            "limit=%s page=%s result_count=%s include_total=%s",
            filter_ms,
            query_ms,
            serialize_ms,
            total_ms,
            0,
            1,
            result,
            False,
        )
    return result

def _connect():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL;")
    return conn


def _strip_rel_prefixes(value: str) -> str:
    prefixes = tuple(p for p in (f"{DEST_FOLDER_NAME}/", "Sorted_by_Date/") if p)
    draft_prefix = f"{DRAFTS_FOLDER_NAME}/" if DRAFTS_FOLDER_NAME else ""
    changed = True
    while changed:
        changed = False
        lower_val = value.lower()
        for prefix in prefixes:
            pre_low = prefix.lower()
            if lower_val.startswith(pre_low):
                value = value[len(prefix):]
                changed = True
                break
        if changed:
            continue
        if draft_prefix and lower_val.startswith((draft_prefix + draft_prefix).lower()):
            value = value[len(draft_prefix):]
            changed = True
    return value.replace("\\", "/")

def _ensure_video_columns(conn: sqlite3.Connection) -> None:
    cur = conn.cursor()
    cur.execute("PRAGMA table_info(videos)")
    existing_cols = {row[1] for row in cur.fetchall()}
    columns = {
        "prompt": "TEXT",
        "negative": "TEXT",
        "sampler": "TEXT",
        "steps": "INTEGER",
        "cfg": "REAL",
        "cfg_text": "TEXT",
        "seed": "INTEGER",
        "width": "INTEGER",
        "height": "INTEGER",
        "model_checkpoint": "TEXT",
        "models": "TEXT",
        "loras": "TEXT",
        "vae_name": "TEXT",
        "sound": "TEXT",
        "phash": "TEXT",
    }
    for col, type_sql in columns.items():
        if col not in existing_cols:
            try:
                cur.execute(f"ALTER TABLE videos ADD COLUMN {col} {type_sql}")
            except sqlite3.OperationalError as e:
                if "duplicate column name" not in str(e).lower():
                    raise
    conn.commit()

def ensure_videos_table():
    global _videos_table_ready, _videos_db_path
    if _videos_table_ready and _videos_db_path == DB_PATH:
        return
    if _videos_db_path != DB_PATH:
        _videos_table_ready = False

    with _video_table_lock:
        if _videos_table_ready and _videos_db_path == DB_PATH:
            return
        conn = _connect()
        cur = conn.cursor()
        cur.execute(
            '''
            CREATE TABLE IF NOT EXISTS videos (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                rel_video TEXT UNIQUE,
                rel_thumb TEXT,
                date TEXT,
                mtime REAL,
                size INTEGER,
                prompt TEXT,
                negative TEXT,
                sampler TEXT,
                steps INTEGER,
                cfg REAL,
                cfg_text TEXT,
                seed INTEGER,
                width INTEGER,
                height INTEGER,
                model_checkpoint TEXT,
                models TEXT,
                loras TEXT,
                vae_name TEXT,
                sound TEXT,
                phash TEXT
            )
            '''
        )
        _ensure_video_columns(conn)
        cur.execute('CREATE INDEX IF NOT EXISTS idx_videos_mtime ON videos(mtime DESC)')
        cur.execute('CREATE INDEX IF NOT EXISTS idx_videos_date ON videos(date)')
        cur.execute('CREATE INDEX IF NOT EXISTS idx_videos_phash ON videos(phash)')
        conn.commit()
        conn.close()
        _videos_table_ready = True
        _videos_db_path = DB_PATH

def _to_rel(path: str) -> str:
    # Store paths relative to DEST (no leading DEST_FOLDER_NAME)
    p = Path(path).resolve()
    try:
        return str(p.relative_to(Path(DEST).resolve())).replace('\\','/')
    except Exception:
        # fallback: already relative
        return str(p).replace('\\','/')

def _has_meta_value(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (list, tuple, set, dict)):
        return bool(value)
    return True


def _merge_meta_dicts(primary: Optional[Dict[str, Any]], fallback: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    primary = primary or {}
    fallback = fallback or {}
    if not primary:
        return dict(fallback)
    if not fallback:
        return dict(primary)

    merged = dict(fallback)
    extras: Dict[str, Any] = {}
    fallback_extras = fallback.get("extras")
    primary_extras = primary.get("extras")
    if isinstance(fallback_extras, dict):
        extras.update(fallback_extras)
    if isinstance(primary_extras, dict):
        extras.update(primary_extras)
    if extras:
        merged["extras"] = extras

    for key, value in primary.items():
        if key == "extras":
            continue
        if _has_meta_value(value):
            merged[key] = value
    return merged


def _extract_meta(meta: Optional[Dict[str, Any]] = None, thumb_path: Optional[str] = None) -> Dict[str, Any]:
    resolved_meta = dict(meta or {})
    if thumb_path:
        thumb_candidate = Path(thumb_path)
        if meta is None:
            try:
                resolved_meta = extract_prompt_from_file(thumb_path) or {}
            except Exception:
                resolved_meta = {}
        elif thumb_candidate.suffix.lower() == ".png":
            try:
                thumb_meta = extract_prompt_from_file(thumb_path) or {}
            except Exception:
                thumb_meta = {}
            resolved_meta = _merge_meta_dicts(thumb_meta, resolved_meta)

    meta = resolved_meta
    def _as_int(val):
        try:
            return int(str(val).strip())
        except (TypeError, ValueError):
            return None

    def _normalize_cfg(val):
        if isinstance(val, (list, tuple)):
            numeric_values = []
            for item in val:
                try:
                    numeric_values.append(float(str(item).strip()))
                except (TypeError, ValueError):
                    continue
            if not numeric_values:
                return None, None
            first = numeric_values[0]
            if all(abs(item - first) < 1e-9 for item in numeric_values[1:]):
                return first, None
            return None, ", ".join(f"{item:g}" for item in numeric_values)
        if isinstance(val, str):
            stripped = val.strip()
            if stripped.startswith("[") and stripped.endswith("]"):
                try:
                    parsed = json.loads(stripped)
                except Exception:
                    parsed = None
                if isinstance(parsed, list):
                    return _normalize_cfg(parsed)
        try:
            return float(str(val).strip()), None
        except (TypeError, ValueError):
            return None, None

    model_checkpoint = meta.get("model_checkpoint") or meta.get("model")
    models = meta.get("models")
    if not models and model_checkpoint:
        models = [model_checkpoint]
    cfg_value, cfg_text = _normalize_cfg(meta.get("cfg"))
    return {
        "prompt": meta.get("positive") or meta.get("prompt") or "",
        "negative": meta.get("negative") or "",
        "sampler": meta.get("sampler"),
        "steps": _as_int(meta.get("steps")),
        "cfg": cfg_value,
        "cfg_text": cfg_text,
        "seed": _as_int(meta.get("seed")),
        "width": _as_int(meta.get("width")),
        "height": _as_int(meta.get("height")),
        "model_checkpoint": model_checkpoint,
        "models": models,
        "loras": meta.get("loras"),
        "vae_name": meta.get("vae_name"),
    }

def _serialize_models(value: Any) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, (list, tuple)):
        return json.dumps([str(v).strip() for v in value if str(v).strip()], ensure_ascii=False)
    if isinstance(value, str):
        stripped = value.strip()
        return stripped or None
    return None

def _serialize_loras(value: Any) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, (list, tuple, dict)):
        return json.dumps(value, ensure_ascii=False)
    if isinstance(value, str):
        stripped = value.strip()
        return stripped or None
    return None

def _deserialize_loras(value: Any) -> Optional[Any]:
    if value is None:
        return None
    if isinstance(value, (list, tuple, dict)):
        return value
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return None
        try:
            parsed = json.loads(stripped)
        except json.JSONDecodeError:
            return None
        if isinstance(parsed, dict):
            return [parsed]
        return parsed
    return None

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

def upsert_video(abs_video: str, abs_thumb: str, meta: Optional[Dict[str, Any]] = None) -> None:
    ensure_videos_table()
    rel_v = _to_rel(abs_video)
    rel_t = _to_rel(abs_thumb)
    date_part = find_date_in_parts(Path(abs_video).parts) or ''
    mtime = os.path.getmtime(abs_video) if os.path.exists(abs_video) else 0.0
    size = os.path.getsize(abs_video) if os.path.exists(abs_video) else 0
    meta_values = _extract_meta(meta, thumb_path=abs_thumb)
    sound_flag = detect_video_sound(Path(abs_video))
    sound_value = "y" if sound_flag else None
    conn = _connect()
    cur = conn.cursor()
    cur.execute(
        '''
        INSERT INTO videos (
            rel_video,
            rel_thumb,
            date,
            mtime,
            size,
            prompt,
            negative,
            sampler,
            steps,
            cfg,
            cfg_text,
            seed,
            width,
            height,
            model_checkpoint,
            models,
            loras,
            vae_name,
            sound
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(rel_video) DO UPDATE SET
            rel_thumb=excluded.rel_thumb,
            date=excluded.date,
            mtime=excluded.mtime,
            size=excluded.size,
            prompt=excluded.prompt,
            negative=excluded.negative,
            sampler=excluded.sampler,
            steps=excluded.steps,
            cfg=excluded.cfg,
            cfg_text=excluded.cfg_text,
            seed=excluded.seed,
            width=excluded.width,
            height=excluded.height,
            model_checkpoint=excluded.model_checkpoint,
            models=excluded.models,
            loras=excluded.loras,
            vae_name=excluded.vae_name,
            sound=excluded.sound
        ''',
        (
            rel_v,
            rel_t,
            date_part,
            mtime,
            size,
            meta_values.get("prompt"),
            meta_values.get("negative"),
            meta_values.get("sampler"),
            meta_values.get("steps"),
            meta_values.get("cfg"),
            meta_values.get("cfg_text"),
            meta_values.get("seed"),
            meta_values.get("width"),
            meta_values.get("height"),
            meta_values.get("model_checkpoint"),
            _serialize_models(meta_values.get("models")),
            _serialize_loras(meta_values.get("loras")),
            meta_values.get("vae_name"),
            sound_value,
        )
    )
    conn.commit()
    conn.close()

def bulk_upsert_from_dest() -> int:
    ensure_videos_table()
    count = 0
    skip = {os.path.join(DEST, 'Trash'), os.path.join(DEST, 'failed')}
    for root, dirs, files in os.walk(DEST):
        dirs[:] = [d for d in dirs if os.path.join(root, d) not in skip]
        for f in files:
            low = f.lower()
            if "(video)" in low and any(low.endswith(ext) for ext in VIDEO_EXTS):
                video_abs = os.path.join(root, f)
                pair_png = os.path.splitext(video_abs)[0] + ".png"
                thumb_source = pair_png if os.path.exists(pair_png) else video_abs
                meta = extract_prompt_from_file(video_abs)
                if not meta and os.path.exists(pair_png):
                    meta = extract_prompt_from_file(pair_png)
                upsert_video(video_abs, thumb_source, meta)
                count += 1
    return count

def query_videos(
    page: int = 1,
    limit: int = 60,
    sort_order: str = "desc",
    query: str = "",
    match_mode: str = "and",
) -> List[Dict[str, Any]]:
    perf_enabled = PERF_LOGS
    overall_start = time.perf_counter() if perf_enabled else 0.0
    filter_ms = 0.0
    query_ms = 0.0
    serialize_ms = 0.0

    ensure_videos_table()
    limit = max(1, int(limit))
    offset = max(0, (int(page) - 1) * limit)
    order = "DESC" if str(sort_order).lower().startswith("d") else "ASC"
    filter_start = time.perf_counter() if perf_enabled else 0.0
    keywords = _normalize_keywords(query or "")

    conn = _connect()
    cur = conn.cursor()
    sql = (
        "SELECT rel_video, rel_thumb, date, mtime, size, prompt, negative, sampler, steps, cfg, cfg_text, seed, width, height, "
        "model_checkpoint, models, loras, vae_name, sound "
        "FROM videos"
    )
    params: List[Any] = []
    if keywords:
        clauses = []
        for kw in keywords:
            clauses.append("(COALESCE(prompt, '') LIKE ? OR COALESCE(negative, '') LIKE ?)")
            params.extend([f"%{kw}%", f"%{kw}%"])
        joiner = " OR " if str(match_mode).lower() == "or" else " AND "
        sql += " WHERE " + joiner.join(clauses)
    sql += f" ORDER BY mtime {order} LIMIT ? OFFSET ?"
    params.extend([limit, offset])
    if perf_enabled:
        filter_ms = (time.perf_counter() - filter_start) * 1000
    query_start = time.perf_counter() if perf_enabled else 0.0
    cur.execute(sql, params)
    rows = cur.fetchall()
    if perf_enabled:
        query_ms = (time.perf_counter() - query_start) * 1000
    conn.close()
    items: List[Dict[str, Any]] = []
    serialize_start = time.perf_counter() if perf_enabled else 0.0
    for (
        rel_v,
        rel_t,
        date_part,
        mtime,
        size,
        prompt,
        negative,
        sampler,
        steps,
        cfg,
        cfg_text,
        seed,
        width,
        height,
        model_checkpoint,
        models,
        loras,
        vae_name,
        sound,
    ) in rows:
        thumb_rel = f"{DEST_FOLDER_NAME}/{rel_t}" if rel_t else f"{DEST_FOLDER_NAME}/{rel_v}"
        decoded_loras = _deserialize_loras(loras)
        decoded_models = _deserialize_models(models)
        cfg_value = cfg if cfg is not None else (cfg_text or None)
        meta = {
            "prompt": prompt or "",
            "negative": negative or "",
            "sampler": sampler or "",
            "steps": steps,
            "cfg": cfg_value,
            "seed": seed,
            "width": width,
            "height": height,
            "model_checkpoint": model_checkpoint or "",
            "models": decoded_models,
            "loras": decoded_loras,
            "vae_name": vae_name or "",
        }
        items.append({
            "video_rel": f"{DEST_FOLDER_NAME}/{rel_v}",
            "thumb_rel": thumb_rel,
            "rel_thumb": thumb_rel,
            "date": date_part,
            "mtime": mtime,
            "size": size,
            "prompt": prompt or "",
            "negative": negative or "",
            "sampler": sampler or "",
            "steps": steps,
            "cfg": cfg_value,
            "seed": seed,
            "width": width,
            "height": height,
            "model_checkpoint": model_checkpoint or "",
            "models": decoded_models,
            "loras": decoded_loras,
            "vae_name": vae_name or "",
            "sound": sound or "",
            "meta": meta,
        })
    if perf_enabled:
        serialize_ms = (time.perf_counter() - serialize_start) * 1000
        total_ms = (time.perf_counter() - overall_start) * 1000
        logger.info(
            "PERF DB query_videos filter_ms=%.2f query_ms=%.2f serialize_ms=%.2f total_ms=%.2f "
            "limit=%s page=%s result_count=%s include_total=%s",
            filter_ms,
            query_ms,
            serialize_ms,
            total_ms,
            limit,
            page,
            len(items),
            False,
        )
    return items


def get_video_by_rel(rel_video: str) -> Optional[Dict[str, Any]]:
    """단일 영상 메타데이터를 상대 경로(DEST 기준)로 조회한다."""
    ensure_videos_table()
    normalized = _strip_rel_prefixes((rel_video or "").strip())

    conn = _connect()
    cur = conn.cursor()
    cur.execute(
        'SELECT rel_video, rel_thumb, date, mtime, size, prompt, negative, sampler, steps, cfg, cfg_text, seed, width, height, model_checkpoint, models, loras, vae_name, sound FROM videos WHERE rel_video = ?',
        (normalized,),
    )
    row = cur.fetchone()
    conn.close()
    if not row:
        return None

    (
        rel_v,
        rel_t,
        date_part,
        mtime,
        size,
        prompt,
        negative,
        sampler,
        steps,
        cfg,
        cfg_text,
        seed,
        width,
        height,
        model_checkpoint,
        models,
        loras,
        vae_name,
        sound,
    ) = row
    thumb_rel = f"{DEST_FOLDER_NAME}/{rel_t}" if rel_t else f"{DEST_FOLDER_NAME}/{rel_v}"
    decoded_loras = _deserialize_loras(loras)
    decoded_models = _deserialize_models(models)
    cfg_value = cfg if cfg is not None else (cfg_text or None)
    meta = {
        "prompt": prompt or "",
        "negative": negative or "",
        "sampler": sampler or "",
        "steps": steps,
        "cfg": cfg_value,
        "seed": seed,
        "width": width,
        "height": height,
        "model_checkpoint": model_checkpoint or "",
        "models": decoded_models,
        "loras": decoded_loras,
        "vae_name": vae_name or "",
    }
    return {
        "video_rel": f"{DEST_FOLDER_NAME}/{rel_v}",
        "thumb_rel": thumb_rel,
        "rel_thumb": thumb_rel,
        "date": date_part,
        "mtime": mtime,
        "size": size,
        "prompt": prompt or "",
        "negative": negative or "",
        "sampler": sampler or "",
        "steps": steps,
        "cfg": cfg_value,
        "seed": seed,
        "width": width,
        "height": height,
        "model_checkpoint": model_checkpoint or "",
        "models": decoded_models,
        "loras": decoded_loras,
        "vae_name": vae_name or "",
        "sound": sound or "",
        "meta": meta,
    }

def remove_video_from_db(rel_video: str) -> None:
    ensure_videos_table()
    rel = _strip_rel_prefixes((rel_video or "").strip())
    if not rel:
        return
    conn = _connect()
    cur = conn.cursor()
    delete_item_tags("video", rel, conn=conn)
    delete_item_ratings("video", rel, conn=conn)
    cur.execute(
        "DELETE FROM collection_items WHERE media_path = ? AND media_type = 'video'",
        (rel,),
    )
    cur.execute('DELETE FROM videos WHERE rel_video = ?', (rel,))
    conn.commit()
    conn.close()

from __future__ import annotations

import logging
import sqlite3
from typing import Any, Dict, List, Optional

from flask import Blueprint, jsonify, request

from settings import DB_PATH
from core.booru.booru_dict import ensure_booru_tables, normalize_booru_tag
from core.booru.booru_item_tags import (
    get_manual_tags,
    list_item_tag_sources,
    normalize_booru_tags,
    replace_item_tags,
)
from core.tagging.wd14_tagger import AUTO_WD14_SOURCE, auto_tag_rel_path
from core.db.search_utils import normalize_media_path

bp = Blueprint("booru", __name__)
logger = logging.getLogger(__name__)

_CATEGORY_MAP = {0: "general", 1: "artist", 3: "copyright", 4: "character", 5: "meta"}
_CATEGORY_NAMES = {"general", "artist", "copyright", "character", "meta"}
MANUAL_SOURCE = "manual"
AUTO_PREFIX = "auto:"
_RATING_SOURCE = MANUAL_SOURCE
_SAFE_AUTO_TAG_ERRORS = {
    "이미지 경로가 올바르지 않습니다.",
    "영상 페어링 이미지는 자동 태깅에서 제외됩니다.",
    "WD14 모델 경로가 설정되지 않았습니다.",
    "onnxruntime이 설치되어 있지 않습니다.",
    "WD14 태그 CSV 파일을 찾을 수 없습니다.",
    "WD14 태거 세션이 준비되지 않았습니다.",
    "WD14 모델 출력이 비어 있습니다.",
}


def _normalize_category_filter(raw: Optional[str]) -> Optional[str]:
    if raw is None:
        return None
    text = str(raw).strip().lower()
    if not text or text in {"all", "any"}:
        return None
    try:
        code = int(text)
    except (TypeError, ValueError):
        code = None
    if code is not None and code in _CATEGORY_MAP:
        return _CATEGORY_MAP[code]
    return text if text in _CATEGORY_NAMES else None


def _parse_limit(raw: Any, default: int = 30, max_limit: int = 200) -> int:
    try:
        value = int(raw)
    except (TypeError, ValueError):
        value = default
    value = max(1, value)
    return min(max_limit, value)


def _normalize_item_key(media_type: str, media_path: str) -> tuple[str, str]:
    media = (media_type or "").strip().lower() or "image"
    path = normalize_media_path(media_path or "")
    return media, path


def _safe_auto_tag_error(exc: Exception) -> str:
    message = str(exc).strip()
    if message in _SAFE_AUTO_TAG_ERRORS:
        return message
    return "자동 태깅을 실행하지 못했습니다."


def _fetch_item_tag_items(
    cur: sqlite3.Cursor,
    media: str,
    path: str,
    *,
    sources: Optional[List[str]] = None,
) -> List[Dict[str, Any]]:
    if not sources:
        return []
    placeholders = ",".join(["?"] * len(sources))
    params: List[Any] = [media, path, *sources]
    cur.execute(
        f"""
        SELECT
          t.tag,
          COALESCE(d.category, 'general') AS category,
          COALESCE(d.post_count, 0) AS post_count,
          t.source
        FROM booru_item_tags t
        LEFT JOIN booru_dict d ON d.tag = t.tag
        WHERE t.media_type=? AND t.media_path=? AND t.source IN ({placeholders})
        ORDER BY
          CASE COALESCE(d.category, 'general')
            WHEN 'copyright' THEN 0
            WHEN 'character' THEN 1
            WHEN 'artist' THEN 2
            WHEN 'general' THEN 3
            WHEN 'meta' THEN 4
            ELSE 5
          END,
          COALESCE(d.post_count, 0) DESC,
          t.tag ASC
        """,
        params,
    )
    rows = cur.fetchall()
    return [
        {
            "tag": row[0],
            "category": row[1] or "general",
            "post_count": int(row[2] or 0),
            "source": row[3] or MANUAL_SOURCE,
        }
        for row in rows
        if row and row[0]
    ]


def _parse_tag_sources(
    raw: Optional[str],
    available_sources: List[str],
) -> List[str]:
    if not available_sources:
        return []
    if raw is None:
        return available_sources
    text = str(raw).strip().lower()
    if not text or text == "all":
        return available_sources
    requested = [chunk.strip() for chunk in text.split(",") if chunk.strip()]
    selected: set[str] = set()
    for entry in requested:
        if entry == "manual":
            if MANUAL_SOURCE in available_sources:
                selected.add(MANUAL_SOURCE)
            continue
        if entry == "auto":
            selected.update(source for source in available_sources if source.startswith(AUTO_PREFIX))
            continue
        if entry in available_sources:
            selected.add(entry)
    if not selected:
        return []
    return [source for source in available_sources if source in selected]


def _fetch_item_rating(
    cur: sqlite3.Cursor,
    media: str,
    path: str,
    *,
    source: str = _RATING_SOURCE,
) -> Optional[Dict[str, Any]]:
    # Prefer manual rating when present. Otherwise, fall back to the most recently
    # updated rating from any other source (e.g. WD auto tagging sources).
    cur.execute(
        """
        SELECT rating, source
        FROM booru_item_rating
        WHERE media_type=? AND media_path=?
        ORDER BY
          CASE WHEN source=? THEN 0 ELSE 1 END,
          datetime(updated_at) DESC,
          datetime(created_at) DESC
        LIMIT 1
        """,
        (media, path, source),
    )
    row = cur.fetchone()
    if not row:
        return None
    try:
        rating_value = int(row[0])
    except (TypeError, ValueError):
        return None
    return {"value": rating_value, "source": row[1] or source}


@bp.get("/api/booru/tags")
def api_booru_tags():
    q = (request.args.get("q") or "").strip()
    if not q:
        return jsonify({"items": []})
    q_norm = normalize_booru_tag(q)
    if not q_norm:
        return jsonify({"items": []})

    category = _normalize_category_filter(request.args.get("category"))
    limit = _parse_limit(request.args.get("limit"), default=30, max_limit=200)

    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    try:
        ensure_booru_tables(cur=cur, conn=conn)
        sql = "SELECT tag, category, post_count FROM booru_dict WHERE tag LIKE ?"
        params: List[Any] = [f"{q_norm}%"]
        if category:
            sql += " AND category = ?"
            params.append(category)
        sql += " ORDER BY post_count DESC, tag ASC LIMIT ?"
        params.append(limit)
        cur.execute(sql, params)
        rows = cur.fetchall()
    finally:
        conn.close()

    items = [
        {
            "tag": row[0],
            "category": row[1] or "general",
            "post_count": int(row[2] or 0),
        }
        for row in rows
        if row and row[0]
    ]
    return jsonify({"items": items})


@bp.get("/api/booru/item-tags")
def api_booru_item_tags_get():
    media = (request.args.get("media") or "image").strip().lower() or "image"
    path = (request.args.get("path") or "").strip()
    if not path:
        return jsonify({"error": "path is required"}), 400
    media_norm, path_norm = _normalize_item_key(media, path)
    if not path_norm:
        return jsonify({"error": "path is required"}), 400

    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    try:
        ensure_booru_tables(cur=cur, conn=conn)
        manual_tags = get_manual_tags(media_norm, path_norm, conn=conn)
        sources = list_item_tag_sources(media_norm, path_norm, conn=conn)
        sources_filtered = _parse_tag_sources(request.args.get("sources"), sources)
        items = _fetch_item_tag_items(cur, media_norm, path_norm, sources=sources_filtered)
        rating = _fetch_item_rating(cur, media_norm, path_norm)
    finally:
        conn.close()

    for item in items:
        item["editable"] = (item.get("source") or MANUAL_SOURCE) == MANUAL_SOURCE

    return jsonify(
        {
            "manual_tags": manual_tags,
            "items": items,
            "sources": sources,
            "rating": rating,
        }
    )


@bp.post("/api/booru/item-tags")
def api_booru_item_tags_save():
    payload: Dict[str, Any] = request.get_json(silent=True) or {}
    media = (payload.get("media") or "image").strip().lower() or "image"
    path = (payload.get("path") or "").strip()
    tags = payload.get("tags")
    if not path:
        return jsonify({"error": "path is required"}), 400
    if tags is None:
        tags = []
    if not isinstance(tags, list):
        return jsonify({"error": "tags must be a list"}), 400
    media_norm, path_norm = _normalize_item_key(media, path)
    if not path_norm:
        return jsonify({"error": "path is required"}), 400

    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    try:
        ensure_booru_tables(cur=cur, conn=conn)
        norm_tags = replace_item_tags(media_norm, path_norm, tags, conn=conn)
        sources = list_item_tag_sources(media_norm, path_norm, conn=conn)
        items = _fetch_item_tag_items(cur, media_norm, path_norm, sources=sources)
    finally:
        conn.close()
    for item in items:
        item["editable"] = (item.get("source") or MANUAL_SOURCE) == MANUAL_SOURCE
    return jsonify({"ok": True, "manual_tags": norm_tags, "items": items, "sources": sources})


@bp.post("/api/booru/item-tags/batch")
def api_booru_item_tags_batch():
    payload: Dict[str, Any] = request.get_json(silent=True) or {}
    items = payload.get("items")
    tags = payload.get("tags")
    if not isinstance(items, list):
        return jsonify({"error": "items must be a list"}), 400
    if tags is None:
        tags = []
    if not isinstance(tags, list):
        return jsonify({"error": "tags must be a list"}), 400

    norm_tags = normalize_booru_tags(tags)
    if not norm_tags:
        return jsonify({"error": "tags is empty"}), 400

    updated = 0
    skipped = 0
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    try:
        ensure_booru_tables(cur=cur, conn=conn)
        for item in items:
            if not isinstance(item, dict):
                skipped += 1
                continue
            media = (item.get("media") or "image").strip().lower() or "image"
            path = (item.get("path") or "").strip()
            media_norm, path_norm = _normalize_item_key(media, path)
            if not path_norm:
                skipped += 1
                continue
            existing = get_manual_tags(media_norm, path_norm, conn=conn)
            merged = normalize_booru_tags([*existing, *norm_tags])
            if set(merged) == set(existing):
                skipped += 1
                continue
            replace_item_tags(media_norm, path_norm, merged, conn=conn)
            updated += 1
    finally:
        conn.close()

    return jsonify({"ok": True, "updated": updated, "skipped": skipped, "tags": norm_tags})


@bp.post("/api/booru/item-tags/batch-remove")
def api_booru_item_tags_batch_remove():
    payload: Dict[str, Any] = request.get_json(silent=True) or {}
    items = payload.get("items")
    tags = payload.get("tags")
    if not isinstance(items, list):
        return jsonify({"error": "items must be a list"}), 400
    if tags is None:
        tags = []
    if not isinstance(tags, list):
        return jsonify({"error": "tags must be a list"}), 400

    norm_tags = normalize_booru_tags(tags)
    if not norm_tags:
        return jsonify({"error": "tags is empty"}), 400

    updated = 0
    skipped = 0
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    try:
        ensure_booru_tables(cur=cur, conn=conn)
        for item in items:
            if not isinstance(item, dict):
                skipped += 1
                continue
            media = (item.get("media") or "image").strip().lower() or "image"
            path = (item.get("path") or "").strip()
            media_norm, path_norm = _normalize_item_key(media, path)
            if not path_norm:
                skipped += 1
                continue
            existing = get_manual_tags(media_norm, path_norm, conn=conn)
            next_tags = [tag for tag in existing if tag not in norm_tags]
            if set(next_tags) == set(existing):
                skipped += 1
                continue
            replace_item_tags(media_norm, path_norm, next_tags, conn=conn)
            updated += 1
    finally:
        conn.close()

    return jsonify({"ok": True, "updated": updated, "skipped": skipped, "tags": norm_tags})


@bp.post("/api/booru/auto-tag")
def api_booru_auto_tag():
    payload: Dict[str, Any] = request.get_json(silent=True) or {}
    media = (payload.get("media") or "image").strip().lower() or "image"
    path = (payload.get("path") or "").strip()
    if not path:
        return jsonify({"error": "path is required"}), 400
    media_norm, path_norm = _normalize_item_key(media, path)
    if not path_norm:
        return jsonify({"error": "path is required"}), 400
    if media_norm != "image":
        return jsonify({"error": "영상은 자동 태깅 대상이 아닙니다."}), 400

    try:
        tags, rating_code = auto_tag_rel_path(path_norm)
    except Exception as exc:
        logger.exception("자동 태깅 실패: %s", exc)
        return jsonify({"error": _safe_auto_tag_error(exc)}), 400

    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    try:
        ensure_booru_tables(cur=cur, conn=conn)
        replace_item_tags(media_norm, path_norm, tags, source=AUTO_WD14_SOURCE, conn=conn)
        if rating_code is None:
            cur.execute(
                "DELETE FROM booru_item_rating WHERE media_type=? AND media_path=? AND source=?",
                (media_norm, path_norm, AUTO_WD14_SOURCE),
            )
        else:
            cur.execute(
                """
                INSERT INTO booru_item_rating (media_type, media_path, rating, source)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(media_type, media_path, source)
                DO UPDATE SET rating=excluded.rating, updated_at=CURRENT_TIMESTAMP
                """,
                (media_norm, path_norm, rating_code, AUTO_WD14_SOURCE),
            )
        conn.commit()
        sources = list_item_tag_sources(media_norm, path_norm, conn=conn)
        items = _fetch_item_tag_items(cur, media_norm, path_norm, sources=sources)
        rating = _fetch_item_rating(cur, media_norm, path_norm)
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    for item in items:
        item["editable"] = (item.get("source") or MANUAL_SOURCE) == MANUAL_SOURCE
    return jsonify({"ok": True, "items": items, "sources": sources, "rating": rating})


@bp.get("/api/booru/item-rating")
def api_booru_item_rating_get():
    media = (request.args.get("media") or "image").strip().lower() or "image"
    path = (request.args.get("path") or "").strip()
    if not path:
        return jsonify({"error": "path is required"}), 400
    media_norm, path_norm = _normalize_item_key(media, path)
    if not path_norm:
        return jsonify({"error": "path is required"}), 400

    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    try:
        ensure_booru_tables(cur=cur, conn=conn)
        rating = _fetch_item_rating(cur, media_norm, path_norm)
    finally:
        conn.close()

    return jsonify({"rating": rating})


@bp.post("/api/booru/item-rating")
def api_booru_item_rating_save():
    payload: Dict[str, Any] = request.get_json(silent=True) or {}
    media = (payload.get("media") or "image").strip().lower() or "image"
    path = (payload.get("path") or "").strip()
    if not path:
        return jsonify({"error": "path is required"}), 400
    media_norm, path_norm = _normalize_item_key(media, path)
    if not path_norm:
        return jsonify({"error": "path is required"}), 400

    rating_raw = payload.get("rating")
    rating_value: Optional[int]
    if rating_raw in ("", None):
        rating_value = None
    else:
        try:
            rating_value = int(rating_raw)
        except (TypeError, ValueError):
            return jsonify({"error": "rating must be an integer or null"}), 400
        if rating_value not in {0, 1, 2, 3}:
            return jsonify({"error": "rating must be 0-3 or null"}), 400

    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    try:
        ensure_booru_tables(cur=cur, conn=conn)
        if rating_value is None:
            cur.execute(
                "DELETE FROM booru_item_rating WHERE media_type=? AND media_path=? AND source=?",
                (media_norm, path_norm, _RATING_SOURCE),
            )
        else:
            cur.execute(
                """
                INSERT INTO booru_item_rating (media_type, media_path, rating, source)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(media_type, media_path, source)
                DO UPDATE SET rating=excluded.rating, updated_at=CURRENT_TIMESTAMP
                """,
                (media_norm, path_norm, rating_value, _RATING_SOURCE),
            )
        conn.commit()
        rating = _fetch_item_rating(cur, media_norm, path_norm)
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    return jsonify({"ok": True, "rating": rating})

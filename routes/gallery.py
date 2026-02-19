from __future__ import annotations
import base64
import json
import logging
import re
import os, platform, subprocess, threading, time, secrets, string, shutil, sqlite3, random, zipfile
from collections import deque
from io import BytesIO
from pathlib import Path
from queue import Queue
from typing import Optional, List, Dict
from mimetypes import guess_type
from PIL import Image, ImageSequence

import settings as _settings
from flask import Blueprint, render_template, request, jsonify, send_file, after_this_request, redirect, url_for

from settings import (
    SOURCE,
    DEST,
    INDEX_DIR,
    DEST_FOLDER_NAME,
    DRAFTS_FOLDER_NAME,
    DRAFTS_IN_DATE_DIRNAME,
    DB_PATH,
    GALLERY_CACHE_TTL_SECONDS,
    FFMPEG_PATH,
    USE_OFFSET_PAGINATION,
    INTEGRITY_MISSING_SAMPLES_LIMIT,
    INTEGRITY_DIAGNOSTICS_LIMIT,
    SEARCH_TOTAL_CACHE_TTL_SECONDS,
    BOORU_TAG_SHOW_MANUAL,
    BOORU_TAG_SHOW_AUTO,
    BOORU_TAG_SHOW_WD,
)
from core.db.search_utils import (
    add_item_to_collection,
    build_collection_tree,
    build_model_category_tree,
    create_collection,
    create_model_category,
    delete_collection,
    delete_model_category,
    ensure_image_tables,
    count_collection_items,
    get_collection,
    get_collection_children,
    get_collection_items,
    get_collections_by_paths,
    get_dataset_image_count,
    get_all_models,
    get_all_tags_with_count,
    get_collection_tree,
    get_model_category,
    get_model_category_children,
    get_model_category_items,
    get_model_category_models,
    get_search_total_count_with_meta,
    is_large_dataset,
    list_collections,
    list_model_categories,
    normalize_media_path,
    query_collection_videos,
    remove_item_from_collection,
    remove_items_from_collection,
    remove_model_from_category,
    rename_collection,
    rename_model_category,
    assign_model_to_category,
    search_images,
    search_images_cursor,
    _deserialize_models,
    should_skip_total_count,
)
from core.db.phash_relations import ensure_phash_relations_table, ensure_phash_group_tables
from core.media.thumbs import (
    THUMB_CACHE_TTL_SECONDS,
    build_thumb_cache_path,
    build_thumb_fallback_candidates,
    generate_thumbnail,
    normalize_thumb_rel_path,
    thumb_cache_is_fresh,
)
from core.media.fftools import resolve_ffmpeg
from core.media.video_index import ensure_videos_table, get_video_by_rel, query_videos, videos_count, VIDEO_EXTS
from core.booru.booru_item_tags import (
    get_booru_category_presence_counts,
    get_booru_rating_counts,
    get_booru_rating_media_count,
    get_booru_tags_with_counts,
)
from core.tagging.wd14_tagger import is_video_pair_image

bp = Blueprint("gallery", __name__)
_DEST_ABS = os.path.abspath(DEST)
_CACHE_TTL_SECONDS = max(0, int(GALLERY_CACHE_TTL_SECONDS or 0))
_CACHE_LOCK = threading.Lock()
_MODELS_CACHE: Dict[str, object] = {"value": None, "expires_at": 0.0}
_COLLECTIONS_CACHE: Dict[str, object] = {"value": None, "expires_at": 0.0}
_MODEL_CATEGORIES_CACHE: Dict[str, object] = {"value": None, "expires_at": 0.0}
_THUMB_QUEUE: "Queue[tuple[str, str]]" = Queue()
_THUMB_QUEUE_LOCK = threading.Lock()
_THUMB_QUEUE_SET: set[str] = set()
_THUMB_WORKER_STARTED = False
_THUMB_PLACEHOLDER_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMBAQEG3t0AAAAASUVORK5CYII="
)

logger = logging.getLogger(__name__)


def _make_random_name(length: int = 12) -> str:
    alphabet = string.ascii_letters + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(length))


def _cache_valid(cache_entry: Dict[str, object], now: float) -> bool:
    return cache_entry.get("value") is not None and float(cache_entry.get("expires_at", 0.0)) > now


def _invalidate_models_cache() -> None:
    with _CACHE_LOCK:
        _MODELS_CACHE["value"] = None
        _MODELS_CACHE["expires_at"] = 0.0


def _invalidate_collections_cache() -> None:
    with _CACHE_LOCK:
        _COLLECTIONS_CACHE["value"] = None
        _COLLECTIONS_CACHE["expires_at"] = 0.0


def _invalidate_model_categories_cache() -> None:
    with _CACHE_LOCK:
        _MODEL_CATEGORIES_CACHE["value"] = None
        _MODEL_CATEGORIES_CACHE["expires_at"] = 0.0


def _get_cached_models() -> List[str]:
    if _CACHE_TTL_SECONDS <= 0:
        return get_all_models()
    now = time.time()
    with _CACHE_LOCK:
        if _cache_valid(_MODELS_CACHE, now):
            return list(_MODELS_CACHE["value"])
    models = get_all_models()
    with _CACHE_LOCK:
        _MODELS_CACHE["value"] = list(models)
        _MODELS_CACHE["expires_at"] = now + _CACHE_TTL_SECONDS
    return models


def _thumb_worker() -> None:
    while True:
        abs_path, thumb_path = _THUMB_QUEUE.get()
        try:
            if not thumb_cache_is_fresh(thumb_path, abs_path):
                generate_thumbnail(abs_path, thumb_path)
        except Exception as exc:
            logger.warning("썸네일 비동기 생성 실패: %s", abs_path, exc_info=exc)
        finally:
            with _THUMB_QUEUE_LOCK:
                _THUMB_QUEUE_SET.discard(thumb_path)
            _THUMB_QUEUE.task_done()


def _start_thumb_worker() -> None:
    global _THUMB_WORKER_STARTED
    if _THUMB_WORKER_STARTED:
        return
    _THUMB_WORKER_STARTED = True
    threading.Thread(target=_thumb_worker, daemon=True).start()


def _enqueue_thumbnail(abs_path: str, normalized_rel: str) -> str:
    thumb_path = build_thumb_cache_path(normalized_rel)
    with _THUMB_QUEUE_LOCK:
        if thumb_path in _THUMB_QUEUE_SET:
            return thumb_path
        _THUMB_QUEUE_SET.add(thumb_path)
        _THUMB_QUEUE.put((abs_path, thumb_path))
    _start_thumb_worker()
    return thumb_path


def _collect_collection_totals(tree: List[Dict[str, object]]) -> Dict[int, int]:
    totals: Dict[int, int] = {}
    stack = list(tree or [])
    while stack:
        node = stack.pop()
        if not isinstance(node, dict):
            continue
        cid = node.get("id")
        if isinstance(cid, int):
            total_count = node.get("total_item_count", node.get("item_count", 0))
            totals[cid] = int(total_count or 0)
        children = node.get("children") or []
        if isinstance(children, list):
            stack.extend(children)
    return totals


def _build_collections_cache() -> Dict[str, object]:
    collections = list_collections()
    tree = build_collection_tree(collections)
    totals_by_id = _collect_collection_totals(tree)
    for col in collections:
        cid = col.get("id")
        if isinstance(cid, int):
            col["total_item_count"] = totals_by_id.get(cid, col.get("item_count", 0))
    options = _flatten_collection_tree(tree)
    labels = {opt.get("id"): opt.get("label") for opt in options}
    return {
        "collections": collections,
        "tree": tree,
        "options": options,
        "labels": labels,
    }


def _build_model_categories_cache() -> Dict[str, object]:
    categories = list_model_categories()
    tree = build_model_category_tree(categories)
    options = _flatten_collection_tree(tree)
    labels = {opt.get("id"): opt.get("label") for opt in options}
    return {
        "categories": categories,
        "tree": tree,
        "options": options,
        "labels": labels,
    }


def _get_cached_collections() -> Dict[str, object]:
    if _CACHE_TTL_SECONDS <= 0:
        return _build_collections_cache()
    now = time.time()
    with _CACHE_LOCK:
        if _cache_valid(_COLLECTIONS_CACHE, now):
            return dict(_COLLECTIONS_CACHE["value"])
    payload = _build_collections_cache()
    with _CACHE_LOCK:
        _COLLECTIONS_CACHE["value"] = dict(payload)
        _COLLECTIONS_CACHE["expires_at"] = now + _CACHE_TTL_SECONDS
    return payload


def _get_cached_model_categories() -> Dict[str, object]:
    if _CACHE_TTL_SECONDS <= 0:
        return _build_model_categories_cache()
    now = time.time()
    with _CACHE_LOCK:
        if _cache_valid(_MODEL_CATEGORIES_CACHE, now):
            return dict(_MODEL_CATEGORIES_CACHE["value"])
    payload = _build_model_categories_cache()
    with _CACHE_LOCK:
        _MODEL_CATEGORIES_CACHE["value"] = dict(payload)
        _MODEL_CATEGORIES_CACHE["expires_at"] = now + _CACHE_TTL_SECONDS
    return payload


@bp.record_once
def _clear_duplicate_download(state):
    endpoint = f"{bp.name}.download_video"
    app = state.app

    if endpoint in app.view_functions:
        app.view_functions.pop(endpoint, None)

    rules = list(app.url_map.iter_rules())
    for rule in rules:
        if rule.endpoint != endpoint:
            continue
        try:
            app.url_map._rules.remove(rule)
        except ValueError:
            pass
        endpoint_rules = app.url_map._rules_by_endpoint.get(endpoint)
        if endpoint_rules and rule in endpoint_rules:
            endpoint_rules.remove(rule)
            if not endpoint_rules:
                app.url_map._rules_by_endpoint.pop(endpoint, None)


def _resolve_media_path(rel_path: Optional[str]) -> Optional[str]:
    normalized = normalize_thumb_rel_path(rel_path)
    if not normalized:
        return None

    abs_path = os.path.abspath(os.path.join(_DEST_ABS, normalized))

    try:
        common_root = os.path.commonpath([abs_path, _DEST_ABS])
    except ValueError:
        return None

    if common_root != _DEST_ABS:
        return None

    if not os.path.isfile(abs_path):
        return None

    return abs_path


def _is_gif_path(path: str) -> bool:
    return os.path.splitext(path)[1].lower() == ".gif"


def _ensure_exiftool_available() -> str:
    configured = (getattr(_settings, "EXIFTOOL_PATH", "") or "").strip()
    exiftool_path = configured if configured and os.path.isfile(configured) else shutil.which("exiftool")
    if not exiftool_path:
        raise RuntimeError("exiftool이 설치되어 있지 않습니다.")
    return exiftool_path


def _resolve_ffmpeg_path() -> Optional[str]:
    try:
        return str(resolve_ffmpeg(_settings))
    except Exception:
        return shutil.which("ffmpeg")


def _strip_gif_metadata(src_path: str, dest_path: str) -> None:
    exiftool_path = _ensure_exiftool_available()
    result = subprocess.run(
        [exiftool_path, "-all=", "-o", dest_path, src_path],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    if result.returncode != 0:
        details = (result.stderr or result.stdout or "").strip()
        if not details:
            details = "알 수 없는 오류"
        raise RuntimeError(f"ExifTool 실행 실패: {details}")
    if not os.path.isfile(dest_path):
        raise RuntimeError("ExifTool 출력 파일을 찾을 수 없습니다.")


def _strip_video_metadata(src_path: str, dest_path: str) -> Optional[str]:
    ffmpeg_path = _resolve_ffmpeg_path()
    if not ffmpeg_path:
        return "ffmpeg 미설치"

    cmd = [
        ffmpeg_path, "-y",
        "-i", src_path,
        "-map_metadata", "-1",
        "-c", "copy",
        dest_path,
    ]
    result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace")
    if result.returncode != 0 or not os.path.exists(dest_path):
        if os.path.exists(dest_path):
            try:
                os.remove(dest_path)
            except OSError:
                pass
        return "ffmpeg 처리 실패"
    return None


def _parse_scale_value(value: object) -> Optional[int]:
    if value is None:
        return None
    try:
        scale = int(value)
    except (TypeError, ValueError):
        return None
    if scale <= 1:
        return None
    return scale


def _parse_ratio_value(value: object) -> Optional[float]:
    if value is None:
        return None
    try:
        ratio = float(value)
    except (TypeError, ValueError):
        return None
    if ratio <= 0 or ratio >= 1:
        return None
    return ratio


def _calculate_resized_dimensions(
    size: tuple[int, int],
    scale: Optional[int],
    ratio: Optional[float],
) -> Optional[tuple[int, int]]:
    width, height = size
    if scale:
        return (max(1, width // scale), max(1, height // scale))
    if ratio:
        return (max(1, int(round(width * ratio))), max(1, int(round(height * ratio))))
    return None


def _save_resized_gif(
    src_path: str,
    dest_path: str,
    scale: Optional[int],
    ratio: Optional[float],
) -> None:
    with Image.open(src_path) as img:
        new_size = _calculate_resized_dimensions(img.size, scale, ratio)
        frame_durations = []
        frames = []
        base_duration = int(img.info.get("duration", 100))
        for frame in ImageSequence.Iterator(img):
            duration = int(frame.info.get("duration", base_duration))
            frame_rgba = frame.convert("RGBA")
            if new_size and frame_rgba.size != new_size:
                frame_rgba = frame_rgba.resize(new_size, resample=Image.LANCZOS)
            frames.append(frame_rgba)
            frame_durations.append(duration)

        if not frames:
            raise ValueError("GIF 프레임을 찾을 수 없습니다.")

        loop = int(img.info.get("loop", 0))
        disposal = int(img.info.get("disposal", 2))

        palette_frame = frames[0].convert("P", palette=Image.ADAPTIVE)
        palette_frames = [palette_frame]
        for frame in frames[1:]:
            palette_frames.append(frame.quantize(palette=palette_frame))

        save_kwargs = {
            "save_all": True,
            "append_images": palette_frames[1:],
            "duration": frame_durations,
            "loop": loop,
            "disposal": disposal,
        }
        if "transparency" in img.info:
            save_kwargs["transparency"] = img.info["transparency"]

        palette_frames[0].save(dest_path, **save_kwargs)

# ---------- helpers (for merged image+video results) ----------
def _abs_from_rel(rel: str) -> str:
    rel2 = str(rel).replace("\\", "/")
    for prefix in (f"{DEST_FOLDER_NAME}/", "Sorted_by_Date/"):
        if prefix and rel2.startswith(prefix):
            rel2 = rel2[len(prefix):]
    return os.path.join(DEST, rel2)


def _strip_dest_prefix(rel_path: str) -> str:
    prefix = f"{DEST_FOLDER_NAME}/" if DEST_FOLDER_NAME else ""
    if prefix and rel_path.startswith(prefix):
        return rel_path[len(prefix):]
    return rel_path


def _video_candidates_from_image(rel_path: str) -> List[str]:
    normalized = normalize_media_path(rel_path)
    if not normalized:
        return []
    base = os.path.splitext(normalized)[0]
    base_variants = {base}
    trimmed = re.sub(r"\s*\(video\)", "", base, flags=re.IGNORECASE).rstrip()
    if trimmed and trimmed != base:
        base_variants.add(trimmed)
    bases: set[str] = set()
    for candidate in base_variants:
        bases.add(candidate)
        stripped = _strip_dest_prefix(candidate)
        if stripped != candidate:
            bases.add(stripped)
    candidates = []
    seen: set[str] = set()
    for base_path in bases:
        base_variants = [base_path]
        low = base_path.lower()
        if low.endswith("-audio"):
            trimmed_audio = base_path[:-6]
            if trimmed_audio and trimmed_audio != base_path:
                base_variants.append(trimmed_audio)
        else:
            base_variants.append(f"{base_path}-audio")
        for variant in base_variants:
            for ext in VIDEO_EXTS:
                candidate = f"{variant}{ext}"
                if candidate in seen:
                    continue
                seen.add(candidate)
                candidates.append(candidate)
    return candidates


def _parse_model_params(raw_values) -> list:
    values = []
    for raw in raw_values or []:
        if not raw:
            continue
        for token in str(raw).split(','):
            name = token.strip()
            if name and name.lower() != "undefined" and name not in values:
                values.append(name)
    return values


def _normalize_filter_logic(value: Optional[str], default: str = "and") -> str:
    logic = str(value or "").strip().lower()
    if logic == "or":
        return "or"
    return "and" if default != "or" else "or"

def _normalize_tag_source(value: Optional[str]) -> str:
    raw = str(value or "").strip().lower()
    if raw in {"booru", "tag", "tags"}:
        return "booru"
    return "prompt"

def _is_draft_media(media: str) -> bool:
    media_val = (media or "").lower()
    return media_val in {"draft", "drafts", "draft-only"}


def _normalize_media_param(media: str | None, default: str = "all") -> str:
    media_val = (media or default).lower()
    if _is_draft_media(media_val):
        # Lite build: dedicated Drafts page/API is removed.
        return "images"
    return media_val

def _flatten_collection_tree(nodes, prefix=None, depth=0):
    prefix = prefix or []
    flattened = []
    for node in nodes:
        path = prefix + [node.get("name") or ""]
        flattened.append(
            {
                "id": node.get("id"),
                "name": node.get("name"),
                "label": " / ".join([p for p in path if p]),
                "depth": depth,
            }
        )
        children = node.get("children") or []
        if children:
            flattened.extend(_flatten_collection_tree(children, path, depth + 1))
    return flattened


def _attach_collections(results, collection_labels=None):
    paths = [r.get("file") for r in results if r.get("file")]
    mapping = get_collections_by_paths(paths)
    for r in results:
        key = normalize_media_path(r.get("file") or "")
        if key:
            collections = []
            for col in mapping.get(key, []):
                label = None
                if collection_labels is not None:
                    label = collection_labels.get(col.get("id"))
                collections.append(
                    {
                        "id": col.get("id"),
                        "name": col.get("name"),
                        "parent_id": col.get("parent_id"),
                        "label": label or col.get("name"),
                    }
                )
            r["collections"] = collections
        else:
            r.setdefault("collections", [])
    return results


def _parse_parent_id(raw_value: Optional[str]) -> Optional[int]:
    if raw_value is None:
        return None
    raw_value = str(raw_value).strip()
    if not raw_value:
        return None
    try:
        pid = int(raw_value)
    except (TypeError, ValueError):
        return None
    return pid if pid > 0 else None


def _resolve_model_filters(
    selected_models: List[str],
    model_category_id: Optional[int],
    *,
    subtree_cache: Optional[Dict[int, List[int]]] = None,
) -> List[str]:
    if model_category_id is None:
        return list(selected_models)
    category_models = get_model_category_models(
        model_category_id,
        subtree_cache=subtree_cache,
    )
    if selected_models:
        allowed = set(category_models)
        return [m for m in selected_models if m in allowed]
    return category_models

def _video_to_result(v):
    def _clean_text(val):
        if val is None:
            return None
        if isinstance(val, str):
            val = val.strip()
            return val or None
        return val

    def _normalize_loras(value):
        if isinstance(value, (list, tuple)):
            return list(value)
        if isinstance(value, dict):
            return [value]
        return []

    def _normalize_models(value):
        if isinstance(value, (list, tuple)):
            return [str(v).strip() for v in value if str(v).strip()]
        if isinstance(value, str) and value.strip():
            return [value.strip()]
        return []

    if isinstance(v, str):
        db_meta = get_video_by_rel(v)
        v = {"rel_video": v, **(db_meta or {})}
    rel_video = v.get("rel_video") or v.get("video_rel") or v.get("video") or v.get("path") or ""
    if not rel_video.startswith("Sorted_by_Date/") and not rel_video.startswith(f"{DEST_FOLDER_NAME}/"):
        rel_video = f"{DEST_FOLDER_NAME}/{rel_video}"
    rel_thumb = v.get("rel_thumb") or v.get("thumb_rel") or rel_video
    if not rel_thumb.startswith("Sorted_by_Date/") and not rel_thumb.startswith(f"{DEST_FOLDER_NAME}/"):
        rel_thumb = f"{DEST_FOLDER_NAME}/{rel_thumb}"
    if not _resolve_media_path(rel_thumb):
        rel_thumb = rel_video
    ts = 0.0
    try:
        ts = os.path.getmtime(_abs_from_rel(rel_video))
    except Exception:
        pass
    meta = v.get("meta") or {}
    prompt = v.get("prompt") or meta.get("prompt") or ""
    negative = v.get("negative") or meta.get("negative") or ""
    sampler = v.get("sampler") or meta.get("sampler") or ""
    cfg = v.get("cfg") if v.get("cfg") is not None else meta.get("cfg")
    seed = v.get("seed") if v.get("seed") is not None else meta.get("seed")
    width = v.get("width") if v.get("width") is not None else meta.get("width") or 0
    height = v.get("height") if v.get("height") is not None else meta.get("height") or 0
    model = _clean_text(v.get("model") or meta.get("model") or meta.get("model_name") or meta.get("model_checkpoint"))
    created = _clean_text(v.get("date") or v.get("created") or meta.get("date") or meta.get("created"))
    model_checkpoint = _clean_text(v.get("model_checkpoint") or meta.get("model_checkpoint"))
    vae_name = _clean_text(v.get("vae_name") or meta.get("vae_name"))
    models = _normalize_models(v.get("models") if v.get("models") is not None else meta.get("models"))
    if not models and model_checkpoint:
        models = [model_checkpoint]
    loras_raw = v.get("loras") if v.get("loras") is not None else meta.get("loras")
    loras = _normalize_loras(loras_raw)
    result = {
        "media":"video",
        "img": rel_thumb,
        "rel_thumb": rel_thumb,
        "file": rel_video,
        "sound": v.get("sound") or "",
        "ts": ts,
        "prompt": prompt,
        "positive": prompt,
        "negative": negative,
        "sampler": sampler,
        "cfg": cfg,
        "seed": seed,
        "width": width,
        "height": height,
        "model": model,
        "model_checkpoint": model_checkpoint,
        "models": models,
        "vae_name": vae_name,
        "date": created,
        "created": created,
        "loras": loras,
    }
    if meta:
        result["meta"] = meta
    return result

def _image_to_result(it):
    rel_img = it.get("path") or it.get("rel_path") or it.get("file") or ""
    if not rel_img.startswith("Sorted_by_Date/") and not rel_img.startswith(f"{DEST_FOLDER_NAME}/"):
        rel_img = f"{DEST_FOLDER_NAME}/{rel_img}"
    ts = it.get("ts") or 0.0
    if not ts:
        try:
            ts = os.path.getmtime(_abs_from_rel(rel_img))
        except Exception:
            pass
    model = (it.get("model") or "").strip() or None
    models = []
    models_raw = it.get("models")
    if isinstance(models_raw, (list, tuple)):
        models = [str(v).strip() for v in models_raw if str(v).strip()]
    elif isinstance(models_raw, str) and models_raw.strip():
        models = [models_raw.strip()]
    meta = it.get("meta") or {}
    if not model:
        model = (meta.get("model") or meta.get("model_name") or "").strip() or None
    if not models:
        models_raw = meta.get("models")
        if isinstance(models_raw, (list, tuple)):
            models = [str(v).strip() for v in models_raw if str(v).strip()]
    date_val = it.get("date") or it.get("created") or meta.get("created") or meta.get("date")
    if isinstance(date_val, str):
        date_val = date_val.strip() or None
    return {
        "media": "image",
        "img": rel_img,
        "file": rel_img,
        "ts": ts,
        "positive": it.get("positive"),
        "negative": it.get("negative"),
        "width": it.get("width") or 0,
        "height": it.get("height") or 0,
        "seed": it.get("seed") or "",
        "sampler": it.get("sampler") or "",
        "cfg": it.get("cfg") or 0,
        "loras": list(it.get("loras") or []),
        "collections": list(it.get("collections") or []),
        "model": model,
        "models": models,
        "date": date_val,
        "created": date_val,
    }


def _compact_result(item: Dict[str, object]) -> Dict[str, object]:
    return {
        "media": item.get("media"),
        "file": item.get("file"),
        "img": item.get("img") or item.get("rel_thumb") or item.get("thumb_rel"),
        "sound": item.get("sound"),
        "ts": item.get("ts") or 0,
        "width": item.get("width") or 0,
        "height": item.get("height") or 0,
        "collections": list(item.get("collections") or []),
        "compact": True,
    }


def _normalize_video_rel_path(path: str) -> str:
    normalized = (path or "").replace("\\", "/").strip()
    if not normalized:
        return ""
    prefixes = [p for p in ("Sorted_by_Date/", f"{DEST_FOLDER_NAME}/") if p]
    draft_prefix = f"{DRAFTS_FOLDER_NAME}/" if DRAFTS_FOLDER_NAME else ""
    changed = True
    while changed:
        changed = False
        lower_val = normalized.lower()
        for prefix in prefixes:
            prefix_lower = prefix.lower()
            if lower_val.startswith(prefix_lower):
                normalized = normalized[len(prefix):]
                changed = True
                break
        if changed:
            continue
        if draft_prefix and normalized.lower().startswith((draft_prefix + draft_prefix).lower()):
            normalized = normalized[len(draft_prefix):]
            changed = True
    return normalized


def _phash_to_int(value: Optional[str]) -> Optional[int]:
    if not value:
        return None
    try:
        return int(str(value), 16)
    except (TypeError, ValueError):
        return None


def _hamming_distance(a: int, b: int) -> int:
    return (a ^ b).bit_count()


PHASH_RELATION_MAX_DISTANCE = 12


def _fetch_group_items(
    cur: sqlite3.Cursor,
    *,
    base_media: Optional[str],
    base_path: Optional[str],
    distance: int,
    include_images: bool,
    include_videos: bool,
    include_video_pairs: bool,
    limit: int,
) -> Optional[List[Dict[str, object]]]:
    if not base_media or not base_path:
        return None
    ensure_phash_group_tables(cur=cur)
    cur.execute(
        "SELECT group_id FROM phash_group_items WHERE media_type = ? AND media_path = ?",
        (base_media, base_path),
    )
    row = cur.fetchone()
    if not row and base_media == "image":
        cur.execute(
            "SELECT group_id FROM phash_group_items WHERE media_type = ? AND media_path = ?",
            ("pair", base_path),
        )
        row = cur.fetchone()
    if not row:
        return None
    group_id = row[0]
    media_types: list[str] = []
    if include_images:
        media_types.append("image")
    if include_videos:
        media_types.append("video")
    if include_video_pairs:
        media_types.append("pair")
    if not media_types:
        return []
    placeholders = ",".join("?" for _ in media_types)
    params: list[object] = [group_id, distance, *media_types]
    cur.execute(
        f'''
        SELECT media_type, media_path, distance
        FROM phash_group_items
        WHERE group_id = ? AND distance <= ? AND media_type IN ({placeholders})
        ''',
        params,
    )
    rows = cur.fetchall()
    if not rows:
        return []
    distance_map: Dict[str, int] = {}
    image_paths: list[str] = []
    video_paths: list[str] = []
    pair_paths: list[str] = []
    for media_type, media_path, dist in rows:
        if media_path == base_path:
            continue
        key = f"{media_type}::{media_path}"
        distance_map[key] = int(dist)
        if media_type == "image":
            image_paths.append(media_path)
        elif media_type == "video":
            video_paths.append(media_path)
        else:
            pair_paths.append(media_path)

    items: List[Dict[str, object]] = []
    if image_paths:
        placeholders = ",".join("?" for _ in image_paths)
        cur.execute(
            f'''
            SELECT file, date, model, models, positive, negative, sampler, seed, steps, cfg,
                   width, height, scheduler
            FROM images
            WHERE file IN ({placeholders})
            ''',
            image_paths,
        )
        for row in cur.fetchall():
            item = _image_to_result(dict(row))
            item["_distance"] = distance_map.get(f"image::{row['file']}", 0)
            items.append(item)

    if video_paths:
        placeholders = ",".join("?" for _ in video_paths)
        cur.execute(
            f'''
            SELECT rel_video, rel_thumb, date, mtime, size, prompt, negative, sampler, cfg, seed,
                   width, height, model_checkpoint, models, loras, vae_name, sound
            FROM videos
            WHERE rel_video IN ({placeholders})
            ''',
            video_paths,
        )
        for row in cur.fetchall():
            item = _video_to_result(dict(row))
            item["_distance"] = distance_map.get(f"video::{row['rel_video']}", 0)
            items.append(item)

    for path in pair_paths:
        item = _image_to_result({"path": path})
        item["_paired"] = True
        item["_distance"] = distance_map.get(f"pair::{path}", 0)
        items.append(item)

    items.sort(key=lambda it: (it.get("_distance", 0), it.get("date") or ""))
    if limit and len(items) > limit:
        return items[:limit]
    return items


def _collect_distinct_phashes(cur: sqlite3.Cursor) -> List[str]:
    phashes: set[str] = set()
    cur.execute("SELECT DISTINCT phash FROM images WHERE phash IS NOT NULL AND phash != ''")
    phashes.update(row[0] for row in cur.fetchall() if row and row[0])
    cur.execute("SELECT DISTINCT phash FROM videos WHERE phash IS NOT NULL AND phash != ''")
    phashes.update(row[0] for row in cur.fetchall() if row and row[0])
    return list(phashes)


def _ensure_phash_relations_for_base(
    cur: sqlite3.Cursor,
    conn: sqlite3.Connection,
    base_phash: str,
    base_int: int,
    max_distance: int,
) -> None:
    ensure_phash_relations_table(conn=conn, cur=cur)
    cur.execute(
        "SELECT 1 FROM phash_relations WHERE base_phash = ? LIMIT 1",
        (base_phash,),
    )
    if cur.fetchone():
        return
    phash_values = _collect_distinct_phashes(cur)
    if base_phash not in phash_values:
        phash_values.append(base_phash)
    rows: list[tuple[str, str, int]] = []
    for other in phash_values:
        other_int = _phash_to_int(other)
        if other_int is None:
            continue
        dist = _hamming_distance(base_int, other_int)
        if dist <= max_distance:
            rows.append((base_phash, other, dist))
    if rows:
        cur.executemany(
            "INSERT OR REPLACE INTO phash_relations (base_phash, other_phash, distance) VALUES (?, ?, ?)",
            rows,
        )
        conn.commit()


def _deserialize_models_value(value: object) -> List[str]:
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



def _parse_loras_value(raw: Optional[str]) -> List[Dict[str, object]]:
    lora_entries: List[Dict[str, object]] = []
    for token in (raw or "").split(","):
        if not token:
            continue
        name_raw, weight_raw = (token.split("::", 1) + [""])[:2]
        name = (name_raw or "").strip()
        weight = None
        if weight_raw != "":
            try:
                weight = float(weight_raw)
            except (TypeError, ValueError):
                weight = None
        if name or weight is not None:
            lora_entries.append({"name": name, "weight": weight})
    return lora_entries


def _calc_total_pages(total_count: int, limit: int) -> int:
    limit = max(1, int(limit))
    return max(1, (int(total_count) + limit - 1) // limit)


def _parse_bool(value: Optional[str]) -> Optional[bool]:
    if value is None:
        return None
    if str(value).strip().lower() in {"1", "true", "yes", "y", "on"}:
        return True
    if str(value).strip().lower() in {"0", "false", "no", "n", "off"}:
        return False
    return None


def _parse_cursor(value: Optional[str]) -> Optional[tuple[Optional[str], Optional[str], Optional[int]]]:
    if not value:
        return None
    try:
        payload = json.loads(value)
    except json.JSONDecodeError:
        return None
    if isinstance(payload, dict):
        date_val = payload.get("date")
        file_val = payload.get("file")
        id_val = payload.get("id")
    elif isinstance(payload, (list, tuple)) and len(payload) == 3:
        date_val, file_val, id_val = payload
    else:
        return None
    try:
        id_val = int(id_val) if id_val is not None else None
    except (TypeError, ValueError):
        id_val = None
    return (date_val, file_val, id_val)


def _cursor_tuple_to_payload(
    cursor: Optional[tuple[Optional[str], Optional[str], Optional[int]]],
) -> Optional[Dict[str, object]]:
    if cursor is None:
        return None
    date_val, file_val, id_val = cursor
    if date_val is None and file_val is None and id_val is None:
        return None
    return {"date": date_val, "file": file_val, "id": id_val}


def _parse_collection_ids(args: request.args.__class__) -> List[int]:
    raw_values: List[str] = []
    for item in args.getlist("collection_id"):
        if item:
            raw_values.append(item)
    legacy_value = (args.get("collection") or "").strip()
    if legacy_value:
        raw_values.append(legacy_value)
    if not raw_values:
        single = (args.get("collection_id") or "").strip()
        if single:
            raw_values.append(single)
    tokens: List[str] = []
    for raw in raw_values:
        tokens.extend([part for part in re.split(r"[,\s]+", str(raw)) if part])
    result: List[int] = []
    seen = set()
    for token in tokens:
        if not token.isdigit():
            continue
        cid = int(token)
        if cid in seen:
            continue
        seen.add(cid)
        result.append(cid)
    return result


def _merge_all_media(
    *,
    query: str,
    match_mode: str,
    sort_order: str,
    limit: int,
    page: int,
    model,
    model_match: str,
    sampler: str,
    seed: Optional[int],
    steps: Optional[int],
    collection_ids: Optional[List[int]],
    media: str = "all",
    compact: bool = False,
    include_total: bool = True,
    collection_subtree_cache: Optional[Dict[int, List[int]]] = None,
    collection_match: str = "and",
    tag_source: str = "prompt",
) -> dict:
    reverse = str(sort_order).lower().startswith("d")
    per_page = max(1, int(limit))
    target_page = max(1, int(page))
    media_mode = _normalize_media_param(media, default="all")
    draft_mode = "exclude"
    include_videos = tag_source != "booru" and media_mode != "images"
    image_data = search_images(
        query=query,
        match_mode=match_mode,
        sort_order=sort_order,
        limit=per_page,
        page=target_page,
        model=model,
        model_match=model_match,
        sampler=sampler,
        seed=seed,
        steps=steps,
        draft_mode=draft_mode,
        collection_ids=collection_ids,
        compact=compact,
        include_total=include_total,
        collection_subtree_cache=collection_subtree_cache,
        collection_match=collection_match,
        tag_source=tag_source,
    )
    images_total = image_data.get("total_count")
    image_results = deque(_image_to_result(r) for r in image_data.get("results", []))

    video_results = deque()
    videos_total = None
    if include_videos:
        if collection_ids:
            video_fetch = lambda page_num: query_collection_videos(
                page=page_num,
                limit=per_page,
                sort_order=sort_order,
                collection_ids=collection_ids,
                collection_subtree_cache=collection_subtree_cache,
                collection_match=collection_match,
            )
            if include_total:
                videos_total = count_collection_items(
                    media_type="video",
                    collection_ids=collection_ids,
                    collection_subtree_cache=collection_subtree_cache,
                    collection_match=collection_match,
                )
        else:
            video_fetch = lambda page_num: query_videos(
                page=page_num,
                limit=per_page,
                sort_order=sort_order,
                query=query,
                match_mode=match_mode,
            )
            if include_total:
                videos_total = int(videos_count(query=query, match_mode=match_mode))

        video_results = deque(_video_to_result(v) for v in video_fetch(target_page))

    merged_candidates = list(image_results) + list(video_results)
    merged = sorted(merged_candidates, key=lambda item: item.get("ts", 0), reverse=reverse)[
        :per_page
    ]

    total_count = None
    total_pages = None
    if images_total is not None and videos_total is not None:
        total_count = int(images_total) + int(videos_total)
        image_pages = _calc_total_pages(images_total, per_page) if images_total is not None else 1
        video_pages = _calc_total_pages(videos_total, per_page) if videos_total is not None else 1
        total_pages = max(image_pages, video_pages)
    return {
        "results": list(merged),
        "total_count": total_count,
        "total_pages": total_pages,
        "videos_total": videos_total,
    }


# ---------- pages ----------
@bp.get("/")
def index():
    action = request.args.get("action", "search")
    query = request.args.get("q", "").lower()
    sort_order = request.args.get("sort", "desc")
    match_mode = request.args.get("match", "and")
    tag_source = _normalize_tag_source(request.args.get("tag_source"))
    model_match_mode = _normalize_filter_logic(request.args.get("model_match", "and"))
    collection_match_mode = _normalize_filter_logic(request.args.get("collection_match", "and"))
    limit = int(request.args.get("limit", 100))
    page = int(request.args.get("page", 1))
    include_total_flag = _parse_bool(request.args.get("include_total"))
    include_total = (page > 1) if include_total_flag is None else include_total_flag
    selected_models = _parse_model_params(request.args.getlist("model"))
    selected_sampler = request.args.get("sampler", "")
    if selected_sampler == "undefined":
        selected_sampler = ""
    seed_param = (request.args.get("seed", "") or "").strip()
    seed_val = int(seed_param) if seed_param.isdigit() else None
    steps_param = (request.args.get("steps", "") or "").strip()
    steps_val = int(steps_param) if steps_param.isdigit() else None
    media = request.args.get("media", "all")
    media_val = _normalize_media_param(media, default="all")
    media = media_val
    draft_mode = "only" if _is_draft_media(media_val) else "exclude"
    cursor = _parse_cursor(request.args.get("cursor"))
    use_offset_flag = _parse_bool(request.args.get("use_offset"))
    use_offset = USE_OFFSET_PAGINATION if use_offset_flag is None else use_offset_flag
    collection_ids = _parse_collection_ids(request.args)
    if not collection_ids:
        collection_ids = []
    model_category_param = (request.args.get("model_category_id") or request.args.get("model_category") or "").strip()
    model_category_id = int(model_category_param) if model_category_param.isdigit() else None
    collection_subtree_cache: Dict[int, List[int]] = {}
    model_category_subtree_cache: Dict[int, List[int]] = {}
    search_mode = f"{tag_source}_{match_mode}"

    if action == "cleanup":
        from core.ops.full_refresh import full_refresh
        full_refresh()
        _invalidate_models_cache()
        from flask import redirect, url_for
        return redirect(url_for("gallery.index"))

    collections_cache = _get_cached_collections()
    collections_data = collections_cache["collections"]
    collection_tree = collections_cache["tree"]
    collection_options = collections_cache["options"]
    collection_labels = collections_cache["labels"]
    selected_collection = None
    selected_collection_summary = ""
    selected_collections = []
    if collection_ids:
        collection_map = {c.get("id"): c for c in collections_data}
        selected_collections = [collection_map.get(cid) for cid in collection_ids if cid in collection_map]
        selected_collection = selected_collections[0] if len(selected_collections) == 1 else None
        labels = []
        for cid in collection_ids:
            label = collection_labels.get(cid)
            if not label:
                label = collection_map.get(cid, {}).get("name")
            if label:
                labels.append(label)
        if labels:
            if len(labels) == 1:
                selected_collection_summary = labels[0]
            elif len(labels) == 2:
                selected_collection_summary = " · ".join(labels)
            else:
                selected_collection_summary = f"{labels[0]} 외 {len(labels) - 1}개"

    model_categories_cache = _get_cached_model_categories()
    model_category_options = model_categories_cache["options"]
    selected_model_category = None
    if model_category_id:
        for cat in model_categories_cache["categories"]:
            if cat.get("id") == model_category_id:
                selected_model_category = cat
                break

    resolved_models = _resolve_model_filters(
        selected_models,
        model_category_id,
        subtree_cache=model_category_subtree_cache,
    )
    if model_category_id is not None and not resolved_models:
        resolved_models = ["__model_category_empty__"]

    if media_val in {"images"} or _is_draft_media(media_val):
        data = search_images(
            query=query,
            match_mode=match_mode,
            sort_order=sort_order,
            limit=limit,
            page=page,
            model=resolved_models,
            model_match=model_match_mode,
            sampler=selected_sampler,
            seed=seed_val,
            steps=steps_val,
            draft_mode=draft_mode,
            collection_ids=collection_ids or None,
            cursor=cursor,
            use_offset=use_offset,
            include_total=include_total,
            collection_subtree_cache=collection_subtree_cache,
            collection_match=collection_match_mode,
            tag_source=tag_source,
        )
        results = _attach_collections([_image_to_result(r) for r in data["results"]], collection_labels)
        total_count = data["total_count"]
        total_pages = data["total_pages"]
        if _is_draft_media(media_val):
            videos_total = 0
        elif include_total and tag_source != "booru":
            videos_total = (
                count_collection_items(
                    media_type="video",
                    collection_ids=collection_ids or None,
                    collection_subtree_cache=collection_subtree_cache,
                    collection_match=collection_match_mode,
                )
                if collection_ids
                else int(videos_count(query=query, match_mode=match_mode))
            )
        elif tag_source == "booru":
            videos_total = 0
        else:
            videos_total = None

    elif media_val == "videos":
        if tag_source == "booru":
            results = []
            total_count = 0
            total_pages = 1
            videos_total = 0
        elif collection_ids:
            total_count = count_collection_items(
                media_type="video",
                collection_ids=collection_ids or None,
                collection_subtree_cache=collection_subtree_cache,
                collection_match=collection_match_mode,
            )
            items = query_collection_videos(
                page=page,
                limit=limit,
                sort_order=sort_order,
                collection_ids=collection_ids or None,
                collection_subtree_cache=collection_subtree_cache,
                collection_match=collection_match_mode,
            )
        else:
            total_count = int(videos_count(query=query, match_mode=match_mode))
            items = query_videos(
                page=page,
                limit=limit,
                sort_order=sort_order,
                query=query,
                match_mode=match_mode,
            )
        if tag_source != "booru":
            results = _attach_collections([_video_to_result(v) for v in items], collection_labels)
            total_pages = _calc_total_pages(total_count, limit)
            videos_total = total_count

    else:  # all
        merged = _merge_all_media(
            query=query,
            match_mode=match_mode,
            sort_order=sort_order,
            limit=limit,
            page=page,
            model=resolved_models,
            model_match=model_match_mode,
            sampler=selected_sampler,
            seed=seed_val,
            steps=steps_val,
            collection_ids=collection_ids or None,
            media=media_val,
            include_total=include_total,
            collection_subtree_cache=collection_subtree_cache,
            collection_match=collection_match_mode,
            tag_source=tag_source,
        )
        results = _attach_collections(merged["results"], collection_labels)
        total_count = merged["total_count"]
        total_pages = merged["total_pages"]
        videos_total = merged["videos_total"]

    large_dataset = is_large_dataset()

    return render_template("index.html",
        results=results,
        query=query, sort=sort_order, match=match_mode, tag_source=tag_source, search_mode=search_mode,
        limit=limit, page=page, total_pages=total_pages, total_results=total_count,
        videos_total=videos_total,
        models=_get_cached_models(),
        selected_models=selected_models,
        selected_model_match=model_match_mode,
        selected_sampler=selected_sampler,
        seed=seed_val,
        steps=steps_val,
        collections=collections_data,
        collection_tree=collection_tree,
        collection_options=collection_options,
        collection_labels=collection_labels,
        selected_collection_ids=collection_ids,
        selected_collection=selected_collection,
        selected_collection_summary=selected_collection_summary,
        selected_collection_match=collection_match_mode,
        model_category_options=model_category_options,
        selected_model_category_id=model_category_id,
        selected_model_category=selected_model_category,
        current_source=SOURCE,
        current_dest=DEST,
        current_index=INDEX_DIR,
        current_ffmpeg=FFMPEG_PATH,
        media=media_val,
        integrity_missing_samples_limit=INTEGRITY_MISSING_SAMPLES_LIMIT,
        integrity_diagnostics_limit=INTEGRITY_DIAGNOSTICS_LIMIT,
        large_dataset=large_dataset,
        booru_tag_display={
            "show_manual": BOORU_TAG_SHOW_MANUAL,
            "show_auto": BOORU_TAG_SHOW_AUTO,
            "show_wd": BOORU_TAG_SHOW_WD,
        },
    )

@bp.get("/api/search")
def api_search():
    query = request.args.get("q", "").lower()
    sort_order = request.args.get("sort", "desc")
    match_mode = request.args.get("match", "and")
    tag_source = _normalize_tag_source(request.args.get("tag_source"))
    model_match_mode = _normalize_filter_logic(request.args.get("model_match", "and"))
    collection_match_mode = _normalize_filter_logic(request.args.get("collection_match", "and"))
    limit = int(request.args.get("limit", 50))
    page = int(request.args.get("page", 1))
    include_total_flag = _parse_bool(request.args.get("include_total"))
    include_total = False if include_total_flag is None else include_total_flag
    selected_models = _parse_model_params(request.args.getlist("model"))
    selected_sampler = request.args.get("sampler", "")
    if selected_sampler == "undefined":
        selected_sampler = ""
    seed_param = (request.args.get("seed", "") or "").strip()
    seed_val = int(seed_param) if seed_param.isdigit() else None
    steps_param = (request.args.get("steps", "") or "").strip()
    steps_val = int(steps_param) if steps_param.isdigit() else None
    media = request.args.get("media", "all")
    media_val = _normalize_media_param(media, default="all")
    draft_mode = "only" if _is_draft_media(media_val) else "exclude"
    compact_flag = _parse_bool(request.args.get("compact"))
    compact = compact_flag is True
    cursor = _parse_cursor(request.args.get("cursor"))
    use_offset_flag = _parse_bool(request.args.get("use_offset"))
    use_offset = USE_OFFSET_PAGINATION if use_offset_flag is None else use_offset_flag
    collection_ids = _parse_collection_ids(request.args)
    if not collection_ids:
        collection_ids = []
    model_category_param = (request.args.get("model_category_id") or request.args.get("model_category") or "").strip()
    model_category_id = int(model_category_param) if model_category_param.isdigit() else None
    collection_subtree_cache: Dict[int, List[int]] = {}
    model_category_subtree_cache: Dict[int, List[int]] = {}

    resolved_models = _resolve_model_filters(
        selected_models,
        model_category_id,
        subtree_cache=model_category_subtree_cache,
    )
    if model_category_id is not None and not resolved_models:
        resolved_models = ["__model_category_empty__"]

    if media_val in {"images"} or _is_draft_media(media_val):
        data = search_images(query=query, match_mode=match_mode, sort_order=sort_order,
                             limit=limit, page=page, model=resolved_models,
                             model_match=model_match_mode,
                             sampler=selected_sampler, seed=seed_val, steps=steps_val, draft_mode=draft_mode,
                             collection_ids=collection_ids or None,
                             cursor=cursor,
                             use_offset=use_offset,
                             compact=compact,
                             include_total=include_total,
                             collection_subtree_cache=collection_subtree_cache,
                             collection_match=collection_match_mode,
                             tag_source=tag_source)
        results = [_image_to_result(r) for r in data["results"]]
        total_count = data["total_count"]
        total_pages = data["total_pages"]
        if _is_draft_media(media_val):
            videos_total = 0
        elif include_total and tag_source != "booru":
            videos_total = (
                count_collection_items(
                    media_type="video",
                    collection_ids=collection_ids or None,
                    collection_subtree_cache=collection_subtree_cache,
                    collection_match=collection_match_mode,
                )
                if collection_ids
                else int(videos_count(query=query, match_mode=match_mode))
            )
        elif tag_source == "booru":
            videos_total = 0
        else:
            videos_total = None

    elif media_val == "videos":
        if tag_source == "booru":
            items = []
            total_count = 0 if include_total else None
        elif collection_ids:
            items = query_collection_videos(
                page=page,
                limit=limit,
                sort_order=sort_order,
                collection_ids=collection_ids or None,
                collection_subtree_cache=collection_subtree_cache,
                collection_match=collection_match_mode,
            )
            total_count = (
                count_collection_items(
                    media_type="video",
                    collection_ids=collection_ids or None,
                    collection_subtree_cache=collection_subtree_cache,
                    collection_match=collection_match_mode,
                )
                if include_total
                else None
            )
        else:
            items = query_videos(
                page=page,
                limit=limit,
                sort_order=sort_order,
                query=query,
                match_mode=match_mode,
            )
            total_count = int(videos_count(query=query, match_mode=match_mode)) if include_total else None
        results = _attach_collections([_video_to_result(v) for v in items])
        total_pages = _calc_total_pages(total_count, limit) if total_count is not None else None
        videos_total = total_count

    else:
        merged = _merge_all_media(
            query=query,
            match_mode=match_mode,
            sort_order=sort_order,
            limit=limit,
            page=page,
            model=resolved_models,
            model_match=model_match_mode,
            sampler=selected_sampler,
            seed=seed_val,
            steps=steps_val,
            collection_ids=collection_ids or None,
            media=media_val,
            compact=compact,
            include_total=include_total,
            collection_subtree_cache=collection_subtree_cache,
            collection_match=collection_match_mode,
            tag_source=tag_source,
        )
        results = _attach_collections(merged["results"])
        total_count = merged["total_count"]
        total_pages = merged["total_pages"]
        videos_total = merged["videos_total"]

    if compact:
        results = [_compact_result(item) for item in results]

    prev_cursor_payload = None
    next_cursor_payload = None
    cursor_map = None
    if media_val in {"images"} or _is_draft_media(media_val):
        next_cursor_payload = data.get("next_cursor")
        prev_cursor_payload = _cursor_tuple_to_payload(cursor)
        cursor_map = {}
        if page > 1 and prev_cursor_payload is not None:
            cursor_map[str(page - 1)] = prev_cursor_payload
        if next_cursor_payload is not None:
            cursor_map[str(page)] = next_cursor_payload
        if not cursor_map:
            cursor_map = None

    return jsonify({
        "results": results,
        "total_results": total_count,
        "total_pages": total_pages,
        "page": page, "query": query, "match": match_mode, "sort": sort_order, "tag_source": tag_source,
        "limit": limit, "models": selected_models, "media": media_val,
        "model_match": model_match_mode,
        "sampler": selected_sampler, "seed": seed_val, "steps": steps_val,
        "collection_id": collection_ids[0] if collection_ids else None,
        "collection_ids": collection_ids,
        "collection_match": collection_match_mode,
        "model_category_id": model_category_id,
        "videos_total": videos_total,
        "next_cursor": next_cursor_payload,
        "prev_cursor": prev_cursor_payload,
        "cursor_map": cursor_map,
        "use_offset": use_offset if media_val in {"images"} or _is_draft_media(media_val) else True,
        "compact": compact,
    })


@bp.get("/api/search_total")
def api_search_total():
    query = request.args.get("q", "").lower()
    sort_order = request.args.get("sort", "desc")
    match_mode = request.args.get("match", "and")
    tag_source = _normalize_tag_source(request.args.get("tag_source"))
    model_match_mode = _normalize_filter_logic(request.args.get("model_match", "and"))
    collection_match_mode = _normalize_filter_logic(request.args.get("collection_match", "and"))
    limit = int(request.args.get("limit", 50))
    page = int(request.args.get("page", 1))
    selected_models = _parse_model_params(request.args.getlist("model"))
    selected_sampler = request.args.get("sampler", "")
    if selected_sampler == "undefined":
        selected_sampler = ""
    seed_param = (request.args.get("seed", "") or "").strip()
    seed_val = int(seed_param) if seed_param.isdigit() else None
    steps_param = (request.args.get("steps", "") or "").strip()
    steps_val = int(steps_param) if steps_param.isdigit() else None
    media = request.args.get("media", "all")
    media_val = _normalize_media_param(media, default="all")
    collection_ids = _parse_collection_ids(request.args)
    if not collection_ids:
        collection_ids = []
    model_category_param = (request.args.get("model_category_id") or request.args.get("model_category") or "").strip()
    model_category_id = int(model_category_param) if model_category_param.isdigit() else None
    collection_subtree_cache: Dict[int, List[int]] = {}
    model_category_subtree_cache: Dict[int, List[int]] = {}

    resolved_models = _resolve_model_filters(
        selected_models,
        model_category_id,
        subtree_cache=model_category_subtree_cache,
    )
    if model_category_id is not None and not resolved_models:
        resolved_models = ["__model_category_empty__"]

    total_count = None
    total_pages = None
    videos_total = None
    cache_hit = False
    skip_reason = None
    total_state = "computed"
    draft_mode = "only" if _is_draft_media(media_val) else "exclude"

    if media_val in {"images"} or _is_draft_media(media_val):
        meta = get_search_total_count_with_meta(
            query=query,
            match_mode=match_mode,
            model=resolved_models,
            model_match=model_match_mode,
            sampler=selected_sampler,
            seed=seed_val,
            steps=steps_val,
            draft_mode=draft_mode,
            collection_ids=collection_ids or None,
            collection_subtree_cache=collection_subtree_cache,
            collection_match=collection_match_mode,
            allow_defer=True,
            tag_source=tag_source,
        )
        total_count = meta["total"]
        cache_hit = bool(meta.get("cache_hit"))
        skip_reason = meta.get("skip_reason")
        total_state = "skipped" if meta.get("skipped") else ("cached" if cache_hit else "computed")
        total_pages = _calc_total_pages(total_count, limit) if total_count is not None else None
        videos_total = 0
    elif media_val == "videos":
        if tag_source == "booru":
            total_count = 0
            total_pages = _calc_total_pages(total_count, limit)
            videos_total = total_count
            return jsonify({
                "total_results": total_count,
                "total_pages": total_pages,
                "videos_total": videos_total,
                "page": page,
                "limit": limit,
                "media": media_val,
                "cache_hit": cache_hit,
                "cache_ttl_seconds": SEARCH_TOTAL_CACHE_TTL_SECONDS,
                "total_state": total_state,
                "skip_reason": skip_reason,
            })
        if should_skip_total_count(
            query=query,
            collection_ids=collection_ids or None,
            draft_mode=draft_mode,
        ):
            total_state = "skipped"
            skip_reason = "large_dataset_empty_query"
        else:
            if collection_ids:
                total_count = count_collection_items(
                    media_type="video",
                    collection_ids=collection_ids or None,
                    collection_subtree_cache=collection_subtree_cache,
                    collection_match=collection_match_mode,
                )
            else:
                total_count = int(videos_count(query=query, match_mode=match_mode))
            total_pages = _calc_total_pages(total_count, limit) if total_count is not None else None
            videos_total = total_count
    else:
        meta = get_search_total_count_with_meta(
            query=query,
            match_mode=match_mode,
            model=resolved_models,
            model_match=model_match_mode,
            sampler=selected_sampler,
            seed=seed_val,
            steps=steps_val,
            draft_mode=draft_mode,
            collection_ids=collection_ids or None,
            collection_subtree_cache=collection_subtree_cache,
            collection_match=collection_match_mode,
            allow_defer=True,
            tag_source=tag_source,
        )
        images_total = meta["total"]
        cache_hit = bool(meta.get("cache_hit"))
        skip_reason = meta.get("skip_reason")
        if meta.get("skipped"):
            total_state = "skipped"
        elif tag_source == "booru":
            total_state = "cached" if cache_hit else "computed"
            total_count = images_total
            total_pages = _calc_total_pages(total_count, limit) if total_count is not None else None
            videos_total = 0
        else:
            total_state = "cached" if cache_hit else "computed"
            if collection_ids:
                videos_total = count_collection_items(
                    media_type="video",
                    collection_ids=collection_ids or None,
                    collection_subtree_cache=collection_subtree_cache,
                    collection_match=collection_match_mode,
                )
            else:
                videos_total = int(videos_count(query=query, match_mode=match_mode))
            if images_total is not None and videos_total is not None:
                total_count = int(images_total) + int(videos_total)
                total_pages = _calc_total_pages(total_count, limit) if total_count else 1

    return jsonify({
        "total_results": total_count,
        "total_pages": total_pages,
        "videos_total": videos_total,
        "page": page,
        "limit": limit,
        "media": media_val,
        "cache_hit": cache_hit,
        "cache_ttl_seconds": SEARCH_TOTAL_CACHE_TTL_SECONDS,
        "total_state": total_state,
        "skip_reason": skip_reason,
    })


@bp.get("/api/search_cursor")
def api_search_cursor():
    query = request.args.get("q", "").lower()
    sort_order = request.args.get("sort", "desc")
    match_mode = request.args.get("match", "and")
    tag_source = _normalize_tag_source(request.args.get("tag_source"))
    model_match_mode = _normalize_filter_logic(request.args.get("model_match", "and"))
    collection_match_mode = _normalize_filter_logic(request.args.get("collection_match", "and"))
    limit = int(request.args.get("limit", 50))
    page = int(request.args.get("page", 1))
    selected_models = _parse_model_params(request.args.getlist("model"))
    selected_sampler = request.args.get("sampler", "")
    if selected_sampler == "undefined":
        selected_sampler = ""
    seed_param = (request.args.get("seed", "") or "").strip()
    seed_val = int(seed_param) if seed_param.isdigit() else None
    steps_param = (request.args.get("steps", "") or "").strip()
    steps_val = int(steps_param) if steps_param.isdigit() else None
    media = request.args.get("media", "all")
    media_val = _normalize_media_param(media, default="all")
    collection_ids = _parse_collection_ids(request.args)
    if not collection_ids:
        collection_ids = []
    model_category_param = (request.args.get("model_category_id") or request.args.get("model_category") or "").strip()
    model_category_id = int(model_category_param) if model_category_param.isdigit() else None
    collection_subtree_cache: Dict[int, List[int]] = {}
    model_category_subtree_cache: Dict[int, List[int]] = {}

    if media_val not in {"images"} and not _is_draft_media(media_val):
        return jsonify({"error": "이미지 검색에서만 커서 계산이 가능합니다."}), 400

    resolved_models = _resolve_model_filters(
        selected_models,
        model_category_id,
        subtree_cache=model_category_subtree_cache,
    )
    if model_category_id is not None and not resolved_models:
        resolved_models = ["__model_category_empty__"]

    draft_mode = "only" if _is_draft_media(media_val) else "exclude"
    cursor_page = max(1, page)
    if cursor_page <= 1:
        return jsonify({"page": cursor_page, "cursor": None})

    data = search_images_cursor(
        query=query,
        match_mode=match_mode,
        sort_order=sort_order,
        limit=limit,
        page=cursor_page,
        model=resolved_models,
        model_match=model_match_mode,
        sampler=selected_sampler,
        seed=seed_val,
        steps=steps_val,
        draft_mode=draft_mode,
        collection_ids=collection_ids or None,
        collection_subtree_cache=collection_subtree_cache,
        collection_match=collection_match_mode,
        tag_source=tag_source,
    )

    return jsonify({
        "page": cursor_page,
        "cursor": data.get("next_cursor"),
    })


@bp.get("/api/detail")
def api_detail():
    rel_path = request.args.get("path")
    normalized = normalize_media_path(rel_path or "")
    if not normalized:
        return jsonify({"error": "경로가 올바르지 않습니다."}), 400

    ensure_image_tables()
    ensure_videos_table()

    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute(
        '''
        SELECT images.id, images.file, images.date, images.model, images.models, images.positive, images.negative,
               images.sampler, images.seed, images.steps, images.cfg, images.width, images.height, images.scheduler,
               GROUP_CONCAT(DISTINCT l.name || '::' || COALESCE(l.strength, '')) as loras
        FROM images
        LEFT JOIN loras l ON l.image_id = images.id
        WHERE images.file = ?
        GROUP BY images.id
        ''',
        (normalized,),
    )
    row = cur.fetchone()
    conn.close()

    if row:
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
            loras_val,
        ) = row
        base = {
            "id": image_id,
            "file": file,
            "date": date,
            "model": model_val,
            "models": _deserialize_models_value(models_raw),
            "positive": positive,
            "negative": negative,
            "sampler": sampler_val,
            "seed": seed_val,
            "steps": steps_val,
            "cfg": cfg_val,
            "width": width_val,
            "height": height_val,
            "scheduler": scheduler_val,
            "loras": _parse_loras_value(loras_val),
        }
        detail_item = _image_to_result(base)
        return jsonify({"item": detail_item})

    video = get_video_by_rel(normalized)
    if video:
        detail_item = _video_to_result(video)
        return jsonify({"item": detail_item})

    return jsonify({"error": "항목을 찾을 수 없습니다."}), 404


@bp.get("/api/related")
def api_related():
    rel_path = request.args.get("path") or ""
    if not rel_path:
        return jsonify({"error": "경로가 올바르지 않습니다."}), 400

    include_images_raw = (request.args.get("include_images") or "1").strip().lower()
    include_images = include_images_raw not in {"0", "false", "no"}
    include_videos_raw = (request.args.get("include_videos") or "1").strip().lower()
    include_videos = include_videos_raw not in {"0", "false", "no"}
    include_pairs_raw = (request.args.get("include_video_pairs") or "0").strip().lower()
    include_video_pairs = include_pairs_raw in {"1", "true", "yes", "y", "on"}
    distance_raw = (request.args.get("distance") or "0").strip()
    limit_raw = (request.args.get("limit") or "48").strip()
    try:
        distance = max(0, int(distance_raw))
    except ValueError:
        distance = 0
    try:
        limit = max(1, min(200, int(limit_raw)))
    except ValueError:
        limit = 48

    normalized = normalize_media_path(rel_path or "")
    video_rel = _normalize_video_rel_path(rel_path)

    ensure_image_tables()
    ensure_videos_table()

    base_phash = None
    base_media = None
    base_image_key = None
    base_video_key = None

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    if normalized:
        cur.execute("SELECT file, phash FROM images WHERE file = ?", (normalized,))
        row = cur.fetchone()
        if row and row["phash"]:
            base_phash = row["phash"]
            base_media = "image"
            base_image_key = row["file"]

    if not base_phash and video_rel:
        cur.execute(
            "SELECT rel_video, rel_thumb, phash FROM videos WHERE rel_video = ? OR rel_thumb = ?",
            (video_rel, video_rel),
        )
        row = cur.fetchone()
        if row and row["phash"]:
            base_phash = row["phash"]
            base_media = "video"
            base_video_key = row["rel_video"]

    if not base_phash:
        conn.close()
        return jsonify(
            {
                "base": {"path": normalized or video_rel, "media": base_media},
                "items": [],
                "distance": distance,
                "reason": "phash_missing",
            }
        )

    base_int = _phash_to_int(base_phash)
    if base_int is None:
        conn.close()
        return jsonify(
            {
                "base": {"path": normalized or video_rel, "media": base_media},
                "items": [],
                "distance": distance,
                "reason": "phash_invalid",
            }
        )

    if not include_images and not include_videos and not include_video_pairs:
        conn.close()
        return jsonify(
            {
                "base": {"path": normalized or video_rel, "media": base_media, "phash": base_phash},
                "items": [],
                "distance": distance,
                "reason": "filters_off",
            }
        )

    group_items = _fetch_group_items(
        cur,
        base_media=base_media,
        base_path=base_image_key if base_media == "image" else base_video_key,
        distance=distance,
        include_images=include_images,
        include_videos=include_videos,
        include_video_pairs=include_video_pairs,
        limit=limit,
    )
    if group_items is not None:
        conn.close()
        return jsonify(
            {
                "base": {"path": normalized or video_rel, "media": base_media, "phash": base_phash},
                "items": group_items,
                "distance": distance,
                "source": "group",
            }
        )

    candidates: list[tuple[int, str, Dict[str, object]]] = []
    fetch_videos = include_videos or include_video_pairs
    paired_thumb_set: set[str] = set()
    if include_images and not include_video_pairs:
        cur.execute("SELECT rel_thumb FROM videos WHERE rel_thumb IS NOT NULL AND rel_thumb != ''")
        for row in cur.fetchall():
            rel_thumb = row["rel_thumb"]
            if not rel_thumb:
                continue
            thumb_norm = normalize_media_path(rel_thumb)
            if thumb_norm:
                paired_thumb_set.add(thumb_norm)

    if distance <= 0:
        if include_images:
            image_sql = (
                '''
                SELECT file, date, model, models, positive, negative, sampler, seed, steps, cfg,
                       width, height, scheduler
                FROM images
                WHERE phash = ?
                '''
            )
            image_params: list[object] = [base_phash]
            if not include_video_pairs:
                image_sql += (
                    " AND NOT EXISTS("
                    "SELECT 1 FROM videos v "
                    "WHERE LOWER(v.rel_thumb) = LOWER(images.file) "
                    "OR LOWER(v.rel_thumb) = LOWER(REPLACE(images.file, ? || '/', '')) "
                    "OR LOWER(REPLACE(v.rel_thumb, ? || '/', '')) = LOWER(images.file)"
                    ")"
                )
                image_params.extend([DEST_FOLDER_NAME, DEST_FOLDER_NAME])
            cur.execute(image_sql, image_params)
            for row in cur.fetchall():
                if base_image_key and row["file"] == base_image_key:
                    continue
                candidates.append((0, "image", dict(row)))

        if fetch_videos:
            cur.execute(
                '''
                SELECT rel_video, rel_thumb, date, mtime, size, prompt, negative, sampler, cfg, seed,
                       width, height, model_checkpoint, models, loras, vae_name, sound
                FROM videos
                WHERE phash = ?
                ''',
                (base_phash,),
            )
            for row in cur.fetchall():
                if base_video_key and row["rel_video"] == base_video_key:
                    continue
                if include_videos:
                    candidates.append((0, "video", dict(row)))
                if include_video_pairs:
                    candidates.append((0, "pair", dict(row)))
    else:
        cache_distance = max(distance, PHASH_RELATION_MAX_DISTANCE)
        _ensure_phash_relations_for_base(cur, conn, base_phash, base_int, cache_distance)
        if include_images:
            image_sql = (
                '''
                SELECT images.file, images.date, images.model, images.models, images.positive, images.negative,
                       images.sampler, images.seed, images.steps, images.cfg, images.width, images.height,
                       images.scheduler, rel.distance AS rel_distance
                FROM images
                JOIN phash_relations rel ON rel.other_phash = images.phash
                WHERE rel.base_phash = ? AND rel.distance <= ?
                '''
            )
            image_params: list[object] = [base_phash, distance]
            if not include_video_pairs:
                image_sql += (
                    " AND NOT EXISTS("
                    "SELECT 1 FROM videos v "
                    "WHERE LOWER(v.rel_thumb) = LOWER(images.file) "
                    "OR LOWER(v.rel_thumb) = LOWER(REPLACE(images.file, ? || '/', '')) "
                    "OR LOWER(REPLACE(v.rel_thumb, ? || '/', '')) = LOWER(images.file)"
                    ")"
                )
                image_params.extend([DEST_FOLDER_NAME, DEST_FOLDER_NAME])
            cur.execute(image_sql, image_params)
            for row in cur:
                if base_image_key and row["file"] == base_image_key:
                    continue
                dist = row["rel_distance"]
                data = dict(row)
                data.pop("rel_distance", None)
                candidates.append((dist, "image", data))

        if fetch_videos:
            video_sql = (
                '''
                SELECT videos.rel_video, videos.rel_thumb, videos.date, videos.mtime, videos.size, videos.prompt,
                       videos.negative, videos.sampler, videos.cfg, videos.seed, videos.width, videos.height,
                       videos.model_checkpoint, videos.models, videos.loras, videos.vae_name, videos.sound,
                       rel.distance AS rel_distance
                FROM videos
                JOIN phash_relations rel ON rel.other_phash = videos.phash
                WHERE rel.base_phash = ? AND rel.distance <= ?
                '''
            )
            cur.execute(video_sql, (base_phash, distance))
            for row in cur:
                if base_video_key and row["rel_video"] == base_video_key:
                    continue
                dist = row["rel_distance"]
                data = dict(row)
                data.pop("rel_distance", None)
                if include_videos:
                    candidates.append((dist, "video", data))
                if include_video_pairs:
                    candidates.append((dist, "pair", data))

    conn.close()

    candidates.sort(key=lambda item: (item[0], item[2].get("date") or ""))
    items: List[Dict[str, object]] = []
    seen_paths: set[str] = set()
    for dist, media, row in candidates:
        if media == "pair" and not include_video_pairs:
            continue
        if media == "image":
            item = _image_to_result(row)
        elif media == "video":
            item = _video_to_result(row)
        else:
            rel_thumb = row.get("rel_thumb") or row.get("rel_video") or ""
            if not rel_thumb:
                continue
            item = _image_to_result({"path": rel_thumb})
            item["_paired"] = True
            item["_paired_from"] = row.get("rel_video") or ""
        item_path = normalize_media_path(item.get("file") or item.get("img") or "")
        if not include_video_pairs:
            if item.get("_paired"):
                continue
            if paired_thumb_set and item.get("media") == "image" and item_path in paired_thumb_set:
                continue
        if base_image_key and item_path == base_image_key:
            continue
        if item_path and item_path in seen_paths:
            continue
        if item_path:
            seen_paths.add(item_path)
        item["_distance"] = dist
        items.append(item)
        if len(items) >= limit:
            break

    return jsonify(
        {
            "base": {"path": normalized or video_rel, "media": base_media, "phash": base_phash},
            "items": items,
            "distance": distance,
        }
    )


@bp.get("/api/paired_media")
def api_paired_media():
    path = (request.args.get("path") or "").strip()
    if not path:
        return jsonify({"error": "path is required"}), 400

    media = (request.args.get("media") or "").strip().lower()
    normalized = normalize_media_path(path)
    if not normalized:
        return jsonify({"error": "path is invalid"}), 400

    media_type = media
    if media_type not in {"image", "video"}:
        ext = os.path.splitext(normalized)[1].lower()
        media_type = "video" if ext in VIDEO_EXTS else "image"

    if media_type == "video":
        video = get_video_by_rel(normalized)
        if not video:
            return jsonify({"pair": None})
        rel_thumb = video.get("thumb_rel") or video.get("rel_thumb")
        if not rel_thumb:
            return jsonify({"pair": None})
        pair_item = _image_to_result({"path": rel_thumb})
        return jsonify({"pair": pair_item, "pair_type": "image"})

    for candidate in _video_candidates_from_image(normalized):
        video = get_video_by_rel(candidate)
        if not video:
            continue
        pair_item = _video_to_result(video)
        return jsonify({"pair": pair_item, "pair_type": "video"})

    return jsonify({"pair": None})


@bp.get("/api/random_media")
def api_random_media():
    preferred = _normalize_media_param(request.args.get("media"), default="all")
    draft_mode = "only" if _is_draft_media(preferred) else "exclude"
    allow_images = preferred in {"all", "image", "images", "img"}
    allow_videos = preferred in {"all", "video", "videos", "vid"}

    ensure_image_tables()
    ensure_videos_table()

    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    img_count = 0
    vid_count = 0
    # Draft classification:
    # - Legacy layout: DEST/Drafts/YYYY-MM-DD/...
    # - New layout: DEST/<DEST_CONTENT_SUBDIR>/YYYY-MM-DD/drafts/...
    # Use LIKE patterns to cover both.
    drafts_name = (DRAFTS_IN_DATE_DIRNAME or "drafts").strip().strip("/\\") or "drafts"
    draft_like_patterns: list[str] = [f"%/{drafts_name.lower()}/%"]
    if DRAFTS_FOLDER_NAME:
        legacy = DRAFTS_FOLDER_NAME.lower().rstrip('/')
        draft_like_patterns.append(legacy + '/%')
        if DEST_FOLDER_NAME:
            draft_like_patterns.append(f"{DEST_FOLDER_NAME.lower().rstrip('/')}/{legacy}/%")
    # de-duplicate while preserving order
    seen = set()
    draft_like_patterns = [p for p in draft_like_patterns if not (p in seen or seen.add(p))]
    def _draft_clause():
        if not draft_like_patterns:
            return ("", [])
        if draft_mode == "exclude":
            sql_parts = []
            params: List[str] = []
            for pat in draft_like_patterns:
                sql_parts.append("LOWER(file) NOT LIKE ?")
                params.append(pat)
            return (" WHERE " + " AND ".join(sql_parts), params)
        if draft_mode == "only":
            ors = ["LOWER(file) LIKE ?" for _ in draft_like_patterns]
            return (" WHERE (" + " OR ".join(ors) + ")", list(draft_like_patterns))
        return ("", [])

    if allow_images:
        clause_sql, clause_params = _draft_clause()
        cur.execute(f"SELECT COUNT(*) FROM images{clause_sql}", clause_params)
        img_count = cur.fetchone()[0] or 0
    if allow_videos:
        cur.execute("SELECT COUNT(*) FROM videos")
        vid_count = cur.fetchone()[0] or 0

    choices = []
    if img_count:
        choices.append(("image", img_count))
    if vid_count:
        choices.append(("video", vid_count))

    if not choices:
        conn.close()
        return jsonify({"error": "추천할 콘텐츠가 없습니다."}), 404

    pick_media = choices[0][0]
    if len(choices) > 1:
        total = sum(weight for _, weight in choices)
        pivot = random.randint(1, total)
        cumulative = 0
        for media_type, weight in choices:
            cumulative += weight
            if pivot <= cumulative:
                pick_media = media_type
                break

    result = None
    if pick_media == "image":
        clause_sql, clause_params = _draft_clause()

        def _pick_random_image():
            attempts = 6
            batch_size = 8
            for _ in range(attempts):
                cur.execute(
                    f'''
                    SELECT images.id, images.file, images.positive, images.negative,
                           images.width, images.height, images.seed, images.sampler, images.cfg,
                           images.model, images.models, images.model_checkpoint,
                           GROUP_CONCAT(DISTINCT l.name || '::' || COALESCE(l.strength, '')) as loras
                    FROM images
                    LEFT JOIN loras l ON l.image_id = images.id
                    {clause_sql}
                    GROUP BY images.id
                    ORDER BY RANDOM()
                    LIMIT {batch_size}
                    ''',
                    clause_params,
                )
                rows = cur.fetchall()
                for candidate in rows:
                    candidate_path = candidate[1]
                    if not candidate_path:
                        continue
                    if is_video_pair_image(Path(_abs_from_rel(candidate_path))):
                        continue
                    return candidate
            return None

        row = _pick_random_image()
        if row:
            (
                image_id,
                file,
                positive,
                negative,
                width,
                height,
                seed_val,
                sampler_val,
                cfg_val,
                model_val,
                models_raw,
                model_checkpoint,
                loras_val,
            ) = row
            models_list = _deserialize_models(models_raw)
            model = (model_val or "").strip() or None
            if not model and models_list:
                model = models_list[0]
            if not model and model_checkpoint:
                model = str(model_checkpoint).strip() or None
            if model and not models_list:
                models_list = [model]
            lora_entries = []
            for token in (loras_val or "").split(","):
                if not token:
                    continue
                name_raw, weight_raw = (token.split("::", 1) + [""])[:2]
                name = (name_raw or "").strip()
                weight = None
                if weight_raw != "":
                    try:
                        weight = float(weight_raw)
                    except (TypeError, ValueError):
                        weight = None
                if name or weight is not None:
                    lora_entries.append({"name": name, "weight": weight})

            base = {
                "id": image_id,
                "file": file,
                "positive": positive,
                "negative": negative,
                "width": width,
                "height": height,
                "seed": seed_val,
                "sampler": sampler_val,
                "cfg": cfg_val,
                "model": model,
                "models": models_list,
                "loras": lora_entries,
            }
            result = _attach_collections([_image_to_result(base)])[0]

    else:
        cur.execute("SELECT rel_video, rel_thumb FROM videos ORDER BY RANDOM() LIMIT 1")
        row = cur.fetchone()
        if row:
            rel_video, rel_thumb = row
            base = {"rel_video": rel_video, "rel_thumb": rel_thumb}
            result = _attach_collections([_video_to_result(base)])[0]

    conn.close()

    if not result:
        return jsonify({"error": "랜덤 추천에 실패했습니다."}), 404

    return jsonify({"item": result})

@bp.get("/collections")
def collections_page():
    collections_cache = _get_cached_collections()
    return render_template(
        "collections.html",
        collections=collections_cache["collections"],
        collection_tree=collections_cache["tree"],
        collection_options=collections_cache["options"],
    )


@bp.get("/model_categories")
def model_categories_page():
    return redirect(url_for("gallery.index"), code=303)


@bp.post("/collections")
def collections_create_form():
    name = (request.form.get("name") or "").strip()
    parent_id = _parse_parent_id(request.form.get("parent_id"))
    if not name:
        collections_cache = _get_cached_collections()
        return render_template(
            "collections.html",
            collections=collections_cache["collections"],
            collection_tree=collections_cache["tree"],
            collection_options=collections_cache["options"],
            error_message="컬렉션 이름을 입력하세요.",
        ), 400
    try:
        cid = create_collection(name, parent_id)
    except Exception as exc:
        collections_cache = _get_cached_collections()
        return render_template(
            "collections.html",
            collections=collections_cache["collections"],
            collection_tree=collections_cache["tree"],
            collection_options=collections_cache["options"],
            error_message=str(exc),
        ), 400
    _invalidate_collections_cache()
    if request.is_json:
        return jsonify({"id": cid, "name": name, "parent_id": parent_id})
    collections_cache = _get_cached_collections()
    return render_template(
        "collections.html",
        collections=collections_cache["collections"],
        collection_tree=collections_cache["tree"],
        collection_options=collections_cache["options"],
        created_id=cid,
    )


@bp.post("/model_categories")
def model_categories_create_form():
    return redirect(url_for("gallery.index"), code=303)


@bp.get("/collections/<int:collection_id>")
def collection_detail_page(collection_id: int):
    collection = get_collection(collection_id)
    if not collection:
        return ("컬렉션을 찾을 수 없습니다.", 404)
    items = get_collection_items(collection_id)
    collections_cache = _get_cached_collections()
    children = get_collection_children(collection_id)
    return render_template(
        "collections.html",
        collections=collections_cache["collections"],
        collection_tree=collections_cache["tree"],
        collection_options=collections_cache["options"],
        current_collection=collection,
        current_children=children,
        items=items,
    )


@bp.get("/model_categories/<int:category_id>")
def model_category_detail_page(category_id: int):
    return redirect(url_for("gallery.index"), code=303)


@bp.get("/api/collections")
def api_collections():
    return jsonify(_get_cached_collections()["collections"])


@bp.post("/api/collections")
def api_create_collection():
    data = request.get_json(silent=True) or request.form
    name = (data.get("name") or "").strip()
    parent_id = _parse_parent_id(data.get("parent_id")) if "parent_id" in data else None
    if not name:
        return jsonify({"error": "이름은 필수입니다."}), 400
    try:
        cid = create_collection(name, parent_id)
    except Exception as exc:
        return jsonify({"error": str(exc)}), 400
    _invalidate_collections_cache()
    return jsonify({"id": cid, "name": name, "parent_id": parent_id}), 201


@bp.patch("/api/collections/<int:collection_id>")
def api_rename_collection(collection_id: int):
    data = request.get_json(silent=True) or request.form
    new_name = (data.get("name") or data.get("new_name") or "").strip()
    update_parent = "parent_id" in data
    parent_id = _parse_parent_id(data.get("parent_id")) if update_parent else None
    if not new_name:
        return jsonify({"error": "새 이름을 입력하세요."}), 400
    try:
        if not rename_collection(collection_id, new_name, parent_id=parent_id, update_parent=update_parent):
            return jsonify({"error": "컬렉션을 찾을 수 없습니다."}), 404
    except Exception as exc:
        return jsonify({"error": str(exc)}), 400
    _invalidate_collections_cache()
    return jsonify({"id": collection_id, "name": new_name, "parent_id": parent_id if update_parent else None})


@bp.delete("/api/collections/<int:collection_id>")
def api_delete_collection(collection_id: int):
    if not delete_collection(collection_id):
        return jsonify({"error": "컬렉션을 찾을 수 없습니다."}), 404
    _invalidate_collections_cache()
    return jsonify({"status": "deleted", "id": collection_id})


@bp.get("/api/collections/<int:collection_id>")
def api_get_collection(collection_id: int):
    collection = get_collection(collection_id)
    if not collection:
        return jsonify({"error": "컬렉션을 찾을 수 없습니다."}), 404
    items = get_collection_items(collection_id)
    return jsonify({"collection": collection, "items": items})


@bp.get("/api/collections/<int:collection_id>/children")
def api_get_collection_children(collection_id: int):
    if collection_id == 0:
        return jsonify(get_collection_children(None))
    collection = get_collection(collection_id)
    if not collection:
        return jsonify({"error": "컬렉션을 찾을 수 없습니다."}), 404
    return jsonify(get_collection_children(collection_id))


@bp.get("/api/collections/tree")
def api_collection_tree():
    return jsonify(_get_cached_collections()["tree"])


@bp.post("/api/collections/<int:collection_id>/items")
def api_add_collection_item(collection_id: int):
    data = request.get_json(silent=True) or request.form
    path = (data.get("path") or data.get("media_path") or "").strip()
    media_type = (data.get("media_type") or data.get("type") or "image").strip()
    if not path:
        return jsonify({"error": "미디어 경로를 입력하세요."}), 400
    if add_item_to_collection(collection_id, path, media_type):
        return jsonify({"status": "added", "collection_id": collection_id, "media_path": path, "media_type": media_type})
    return jsonify({"error": "추가할 수 없습니다."}), 400


@bp.delete("/api/collections/<int:collection_id>/items")
def api_remove_collection_item(collection_id: int):
    data = request.get_json(silent=True) or request.form or {}
    raw_paths: List[str] = []
    if "paths" in data and isinstance(data.get("paths"), list):
        raw_paths = [str(p) for p in data.get("paths")]
    elif "path" in data or "media_path" in data:
        raw_paths = [data.get("path") or data.get("media_path")]
    elif request.args.get("path"):
        raw_paths = [request.args.get("path")]

    paths = [p.strip() for p in raw_paths if isinstance(p, str) and p.strip()]
    if not paths:
        return jsonify({"error": "미디어 경로를 입력하세요."}), 400

    if len(paths) == 1:
        path = paths[0]
        if remove_item_from_collection(collection_id, path):
            return jsonify({"status": "removed", "collection_id": collection_id, "media_path": path})
        return jsonify({"error": "삭제할 항목을 찾을 수 없습니다."}), 404

    summary = remove_items_from_collection(collection_id, paths)
    if summary["removed_count"] <= 0:
        return jsonify({"error": "삭제할 항목을 찾을 수 없습니다."}), 404
    return jsonify({
        "status": "removed",
        "collection_id": collection_id,
        "removed_count": summary["removed_count"],
        "removed_paths": summary.get("removed_paths", []),
        "missing_paths": summary.get("missing_paths", []),
        "invalid_count": summary.get("invalid_count", 0),
    })


@bp.get("/api/model_categories")
def api_model_categories():
    return jsonify(_get_cached_model_categories()["categories"])


@bp.post("/api/model_categories")
def api_create_model_category():
    data = request.get_json(silent=True) or request.form
    name = (data.get("name") or "").strip()
    parent_id = _parse_parent_id(data.get("parent_id")) if "parent_id" in data else None
    if not name:
        return jsonify({"error": "이름은 필수입니다."}), 400
    try:
        cid = create_model_category(name, parent_id)
    except Exception as exc:
        return jsonify({"error": str(exc)}), 400
    _invalidate_model_categories_cache()
    return jsonify({"id": cid, "name": name, "parent_id": parent_id}), 201


@bp.patch("/api/model_categories/<int:category_id>")
def api_rename_model_category(category_id: int):
    data = request.get_json(silent=True) or request.form
    new_name = (data.get("name") or data.get("new_name") or "").strip()
    update_parent = "parent_id" in data
    parent_id = _parse_parent_id(data.get("parent_id")) if update_parent else None
    if not new_name:
        return jsonify({"error": "새 이름을 입력하세요."}), 400
    try:
        if not rename_model_category(category_id, new_name, parent_id=parent_id, update_parent=update_parent):
            return jsonify({"error": "카테고리를 찾을 수 없습니다."}), 404
    except Exception as exc:
        return jsonify({"error": str(exc)}), 400
    _invalidate_model_categories_cache()
    return jsonify({"id": category_id, "name": new_name, "parent_id": parent_id if update_parent else None})


@bp.delete("/api/model_categories/<int:category_id>")
def api_delete_model_category(category_id: int):
    if not delete_model_category(category_id):
        return jsonify({"error": "카테고리를 찾을 수 없습니다."}), 404
    _invalidate_model_categories_cache()
    return jsonify({"status": "deleted", "id": category_id})


@bp.get("/api/model_categories/<int:category_id>")
def api_get_model_category(category_id: int):
    category = get_model_category(category_id)
    if not category:
        return jsonify({"error": "카테고리를 찾을 수 없습니다."}), 404
    items = get_model_category_items(category_id)
    return jsonify({"category": category, "items": items})


@bp.get("/api/model_categories/<int:category_id>/children")
def api_get_model_category_children(category_id: int):
    if category_id == 0:
        return jsonify(get_model_category_children(None))
    category = get_model_category(category_id)
    if not category:
        return jsonify({"error": "카테고리를 찾을 수 없습니다."}), 404
    return jsonify(get_model_category_children(category_id))


@bp.get("/api/model_categories/tree")
def api_model_category_tree():
    return jsonify(_get_cached_model_categories()["tree"])


@bp.post("/api/model_categories/<int:category_id>/models")
def api_add_model_category_model(category_id: int):
    data = request.get_json(silent=True) or request.form
    model_name = (data.get("model_name") or data.get("model") or "").strip()
    if not model_name:
        return jsonify({"error": "모델 이름을 입력하세요."}), 400
    try:
        if assign_model_to_category(model_name, category_id):
            _invalidate_model_categories_cache()
            return jsonify({"status": "added", "category_id": category_id, "model_name": model_name})
    except Exception as exc:
        return jsonify({"error": str(exc)}), 400
    return jsonify({"error": "추가할 수 없습니다."}), 400


@bp.delete("/api/model_categories/<int:category_id>/models")
def api_remove_model_category_model(category_id: int):
    data = request.get_json(silent=True) or request.form or {}
    model_name = (data.get("model_name") or data.get("model") or "").strip()
    if not model_name:
        model_name = (request.args.get("model_name") or request.args.get("model") or "").strip()
    if not model_name:
        return jsonify({"error": "모델 이름을 입력하세요."}), 400
    if remove_model_from_category(category_id, model_name):
        _invalidate_model_categories_cache()
        return jsonify({"status": "removed", "category_id": category_id, "model_name": model_name})
    return jsonify({"error": "삭제할 항목을 찾을 수 없습니다."}), 404


@bp.get("/img")
def get_image():
    abs_path = _resolve_media_path(request.args.get("path"))
    if not abs_path:
        return ("이미지 경로가 잘못되었습니다.", 400)
    if os.path.isfile(abs_path):
        mime, _ = guess_type(abs_path)
        response = send_file(abs_path, mimetype=mime or "image/png", conditional=True, etag=True)
        response.cache_control.public = True
        response.cache_control.max_age = 60 * 60 * 24
        return response
    return (f"이미지 파일을 찾을 수 없습니다: {abs_path}", 404)


@bp.get("/thumb")
def get_thumbnail():
    rel_path = request.args.get("path")
    normalized = normalize_thumb_rel_path(rel_path)
    if not normalized:
        return ("이미지 경로가 잘못되었습니다.", 400)

    abs_path = _resolve_media_path(rel_path)
    if not abs_path:
        return ("이미지 파일을 찾을 수 없습니다.", 404)

    mime, _ = guess_type(abs_path)
    ext = os.path.splitext(abs_path)[1].lower()
    is_image_like = (mime or "").startswith("image")
    is_video_like = (mime or "").startswith("video") or ext in VIDEO_EXTS
    if not (is_image_like or is_video_like):
        return ("지원하지 않는 파일 형식입니다.", 400)

    thumb_path = build_thumb_cache_path(normalized)
    if thumb_cache_is_fresh(thumb_path, abs_path):
        response = send_file(thumb_path, mimetype="image/png", conditional=True, etag=True)
        response.cache_control.public = True
        response.cache_control.max_age = THUMB_CACHE_TTL_SECONDS
        return response

    if os.path.isfile(thumb_path):
        _enqueue_thumbnail(abs_path, normalized)
        response = send_file(thumb_path, mimetype="image/png", conditional=True, etag=True)
        response.cache_control.public = True
        response.cache_control.max_age = 60
        response.headers["X-Thumb-Cache"] = "stale"
        return response

    for candidate in build_thumb_fallback_candidates(normalized):
        if not os.path.isfile(candidate):
            continue
        _enqueue_thumbnail(abs_path, normalized)
        candidate_mime, _ = guess_type(candidate)
        response = send_file(candidate, mimetype=candidate_mime or "image/png", conditional=True, etag=True)
        response.cache_control.public = True
        response.cache_control.max_age = 60
        response.headers["X-Thumb-Cache"] = "fallback"
        return response

    _enqueue_thumbnail(abs_path, normalized)
    response = send_file(BytesIO(_THUMB_PLACEHOLDER_PNG), mimetype="image/png")
    response.status_code = 202
    response.cache_control.no_store = True
    response.headers["Retry-After"] = "1"
    response.headers["X-Thumb-Cache"] = "miss"
    return response

@bp.get("/file")
def get_file():
    abs_path = _resolve_media_path(request.args.get("path"))
    if not abs_path:
        return ("파일 경로가 잘못되었습니다.", 400)
    if os.path.isfile(abs_path):
        mime, _ = guess_type(abs_path)
        response = send_file(abs_path, mimetype=mime or "application/octet-stream", conditional=True, etag=True)
        response.cache_control.public = True
        response.cache_control.max_age = 60 * 60 * 24
        return response
    return (f"파일을 찾을 수 없습니다: {abs_path}", 404)

@bp.get("/download_video")
def download_video():
    abs_path = _resolve_media_path(request.args.get("path"))
    if not abs_path:
        return ("영상 경로가 잘못되었습니다.", 400)
    if not os.path.isfile(abs_path):
        return (f"영상 파일을 찾을 수 없습니다: {abs_path}", 404)

    mime, _ = guess_type(abs_path)
    is_video_like = (mime or "").startswith("video") or (mime or "") == "image/gif"
    if not is_video_like:
        return send_file(abs_path, mimetype=mime or "application/octet-stream")

    rand = ''.join(secrets.choice(string.ascii_letters + string.digits) for _ in range(10))
    ext = os.path.splitext(abs_path)[1] or ".mp4"
    download_name = f"{rand}{ext}"

    def block_download(reason: str):
        warning_code = "download_blocked"
        payload = {"error": "정책상 다운로드 불가", "reason": reason, "code": warning_code}
        response = jsonify(payload)
        response.status_code = 403
        response.headers["X-Download-Warning"] = warning_code
        response.headers["X-Download-Warnings"] = warning_code
        return response

    if (mime or "") == "image/gif":
        temp_dir = os.path.join(DEST, "_cleaned_videos")
        os.makedirs(temp_dir, exist_ok=True)
        new_path = os.path.join(temp_dir, download_name)
        try:
            _strip_gif_metadata(abs_path, new_path)
        except Exception as exc:
            if os.path.exists(new_path):
                try:
                    os.remove(new_path)
                except OSError:
                    pass
            return block_download(f"GIF 메타데이터 제거 실패 ({exc})")

        @after_this_request
        def cleanup_gif(response):
            def delayed_delete(path):
                time.sleep(1)
                try:
                    if os.path.exists(path):
                        os.remove(path)
                except Exception:
                    pass
            threading.Thread(target=delayed_delete, args=(new_path,), daemon=True).start()
            return response

        return send_file(
            new_path,
            mimetype=mime or "application/octet-stream",
            as_attachment=True,
            download_name=download_name,
        )

    ffmpeg_path = _resolve_ffmpeg_path()
    if not ffmpeg_path:
        return block_download("ffmpeg 미설치")

    temp_dir = os.path.join(DEST, "_cleaned_videos")
    os.makedirs(temp_dir, exist_ok=True)

    new_path = os.path.join(temp_dir, download_name)

    cmd = [
        ffmpeg_path, "-y",
        "-i", abs_path,
        "-map_metadata", "-1",
        "-c", "copy",
        new_path,
    ]
    result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace")
    if result.returncode != 0 or not os.path.exists(new_path):
        err = result.stderr.strip() if result.stderr else ""
        print(f"❌ ffmpeg 메타데이터 제거 실패: {err}")
        if os.path.exists(new_path):
            try:
                os.remove(new_path)
            except OSError:
                pass
        return block_download("ffmpeg 처리 실패")

    @after_this_request
    def cleanup(response):
        def delayed_delete(path):
            time.sleep(1)
            try:
                if platform.system() == "Windows":
                    try:
                        subprocess.run(
                            ["powershell", "-Command", f'Remove-Item -Path "{path}" -Stream Zone.Identifier'],
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE
                        )
                    except Exception:
                        pass
                if os.path.exists(path):
                    os.remove(path)
            except Exception:
                pass
        threading.Thread(target=delayed_delete, args=(new_path,), daemon=True).start()
        return response

    return send_file(
        new_path,
        mimetype=mime or "application/octet-stream",
        as_attachment=True,
        download_name=download_name,
    )


@bp.post("/api/download_batch")
def download_batch():
    data = request.get_json(silent=True) or {}
    raw_paths = data.get("paths") or []
    paths = [str(p).strip() for p in raw_paths if isinstance(p, str) and str(p).strip()]
    scale = _parse_scale_value(data.get("scale"))
    ratio = _parse_ratio_value(data.get("ratio"))
    if not paths:
        return jsonify({"error": "다운로드할 항목을 선택하세요."}), 400

    temp_dir = os.path.join(DEST, "_batch_downloads", f"tmp_{_make_random_name(8)}")
    os.makedirs(temp_dir, exist_ok=True)

    prepared = []
    errors = []
    used_names = set()

    for rel_path in paths:
        abs_path = _resolve_media_path(rel_path)
        if not abs_path:
            errors.append(f"잘못된 경로: {rel_path}")
            continue

        base_name = os.path.basename(abs_path)
        rand_name = _make_random_name(12)
        while rand_name in used_names:
            rand_name = _make_random_name(12)
        used_names.add(rand_name)

        mime, _ = guess_type(abs_path)
        if (mime or "").startswith("image"):
            if (mime or "") == "image/gif" or _is_gif_path(abs_path):
                ext = os.path.splitext(abs_path)[1] or ".gif"
                download_name = f"{rand_name}{ext}"
                target_path = os.path.join(temp_dir, download_name)
                try:
                    _strip_gif_metadata(abs_path, target_path)
                    prepared.append((target_path, download_name))
                except Exception as exc:
                    errors.append(f"{base_name}: GIF 메타데이터 제거 실패 ({exc})")
            else:
                download_name = f"{rand_name}.png"
                target_path = os.path.join(temp_dir, download_name)
                try:
                    with Image.open(abs_path) as img:
                        resized = img
                        new_size = _calculate_resized_dimensions(img.size, scale, ratio)
                        if new_size and new_size != img.size:
                            resized = img.resize(new_size, resample=Image.LANCZOS)
                        target_mode = "RGBA" if "A" in resized.getbands() else "RGB"
                        cleaned = resized.convert(target_mode)
                        cleaned.save(target_path, "PNG")
                    prepared.append((target_path, download_name))
                except Exception as exc:
                    errors.append(f"{base_name}: EXIF 제거 실패 ({exc})")
            continue

        ext = os.path.splitext(abs_path)[1] or ".dat"
        download_name = f"{rand_name}{ext}"
        target_path = os.path.join(temp_dir, download_name)
        if (mime or "").startswith("video"):
            reason = _strip_video_metadata(abs_path, target_path)
            if reason:
                errors.append(f"{base_name}: 영상 메타데이터 제거 실패 ({reason})")
            else:
                prepared.append((target_path, download_name))
        else:
            errors.append(f"{base_name}: 메타데이터 제거 미지원")

    if errors:
        shutil.rmtree(temp_dir, ignore_errors=True)
        return jsonify({"error": "다운로드할 항목을 준비하지 못했습니다.", "details": errors}), 400

    if not prepared:
        shutil.rmtree(temp_dir, ignore_errors=True)
        return jsonify({"error": "다운로드할 항목을 준비하지 못했습니다.", "details": errors}), 400

    # 단일 항목이면 ZIP 대신 바로 반환
    if len(prepared) == 1:
        file_path, download_name = prepared[0]

        @after_this_request
        def cleanup_single(response):
            try:
                shutil.rmtree(temp_dir, ignore_errors=True)
            except Exception:
                pass
            return response

        response = send_file(
            file_path,
            mimetype="application/octet-stream",
            as_attachment=True,
            download_name=download_name,
        )
        response.headers["X-Download-Count"] = "1"
        response.headers["X-Download-Mode"] = "single"
        return response

    zip_name = f"batch_{_make_random_name(8)}.zip"
    zip_path = os.path.join(temp_dir, zip_name)
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for file_path, arc_name in prepared:
            zf.write(file_path, arcname=arc_name)

    @after_this_request
    def cleanup(response):
        try:
            shutil.rmtree(temp_dir, ignore_errors=True)
        except Exception:
            pass
        return response

    response = send_file(zip_path, as_attachment=True, download_name=zip_name, mimetype="application/zip")
    response.headers["X-Download-Count"] = str(len(prepared))
    response.headers["X-Download-Mode"] = "strip"
    return response


@bp.post("/api/download_scaled")
def download_scaled():
    data = request.get_json(silent=True) or {}
    abs_path = _resolve_media_path(data.get("path"))
    if not abs_path:
        return jsonify({"error": "경로가 잘못되었습니다."}), 400
    if not os.path.isfile(abs_path):
        return jsonify({"error": "파일을 찾을 수 없습니다."}), 404

    mime, _ = guess_type(abs_path)
    if not (mime or "").startswith("image"):
        if (mime or "").startswith("video"):
            temp_dir = os.path.join(DEST, "_cleaned_videos")
            os.makedirs(temp_dir, exist_ok=True)
            ext = os.path.splitext(abs_path)[1] or ".mp4"
            download_name = os.path.basename(abs_path) or f"{_make_random_name(10)}{ext}"
            cleaned_path = os.path.join(temp_dir, f"{_make_random_name(12)}{ext}")
            reason = _strip_video_metadata(abs_path, cleaned_path)
            if reason:
                if os.path.exists(cleaned_path):
                    try:
                        os.remove(cleaned_path)
                    except OSError:
                        pass
                return jsonify({"error": f"정책상 다운로드 불가: {reason}"}), 403

            @after_this_request
            def cleanup_video(response):
                def delayed_delete(path):
                    time.sleep(1)
                    try:
                        if os.path.exists(path):
                            os.remove(path)
                    except Exception:
                        pass
                threading.Thread(target=delayed_delete, args=(cleaned_path,), daemon=True).start()
                return response

            return send_file(
                cleaned_path,
                mimetype=mime or "application/octet-stream",
                as_attachment=True,
                download_name=download_name,
            )

        return jsonify({"error": "정책상 다운로드 불가: 메타데이터 제거 미지원"}), 415

    scale = _parse_scale_value(data.get("scale"))
    ratio = _parse_ratio_value(data.get("ratio"))
    new_name_input = (data.get("name") or "").strip()
    new_name = os.path.basename(new_name_input)
    if new_name in ("", ".", ".."):
        new_name = ""

    if _is_gif_path(abs_path):
        if new_name:
            download_name = new_name
            if not os.path.splitext(download_name)[1]:
                download_name = f"{download_name}.gif"
        else:
            download_name = f"{_make_random_name(10)}.gif"
        temp_dir = os.path.join(DEST, "_cleaned")
        os.makedirs(temp_dir, exist_ok=True)
        cleaned_path = os.path.join(temp_dir, download_name)
        try:
            _save_resized_gif(abs_path, cleaned_path, scale, ratio)
        except Exception as exc:
            message = str(exc).strip()
            detail = f": {message}" if message else ""
            return (f"GIF 리사이즈에 실패했습니다{detail}", 500)

        @after_this_request
        def cleanup_gif(response):
            def delayed_delete(path):
                time.sleep(1)
                try:
                    if os.path.exists(path):
                        os.remove(path)
                except Exception:
                    pass
            threading.Thread(target=delayed_delete, args=(cleaned_path,), daemon=True).start()
            return response

        return send_file(
            cleaned_path,
            mimetype="image/gif",
            as_attachment=True,
            download_name=download_name,
        )

    if not new_name:
        new_name = f"{_make_random_name(10)}.png"

    temp_dir = os.path.join(DEST, "_cleaned")
    os.makedirs(temp_dir, exist_ok=True)
    new_path = os.path.join(temp_dir, new_name)

    with Image.open(abs_path) as img:
        resized = img
        new_size = _calculate_resized_dimensions(img.size, scale, ratio)
        if new_size and new_size != img.size:
            resized = img.resize(new_size, resample=Image.LANCZOS)
        target_mode = "RGBA" if "A" in resized.getbands() else "RGB"
        cleaned = resized.convert(target_mode)
        cleaned.save(new_path, "PNG")

    @after_this_request
    def cleanup(response):
        def delayed_delete(path):
            time.sleep(1)
            try:
                if platform.system() == "Windows":
                    try:
                        subprocess.run(
                            ["powershell", "-Command", f'Remove-Item -Path "{path}" -Stream Zone.Identifier'],
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE
                        )
                    except Exception:
                        pass
                if os.path.exists(path):
                    os.remove(path)
            except Exception:
                pass
        threading.Thread(target=delayed_delete, args=(new_path,), daemon=True).start()
        return response

    return send_file(new_path, as_attachment=True, download_name=new_name)

@bp.get("/exif")
def get_exif():
    abs_path = _resolve_media_path(request.args.get("path"))
    if not abs_path:
        return ("경로가 잘못되었습니다.", 400)
    if not os.path.isfile(abs_path):
        return (f"파일을 찾을 수 없습니다: {abs_path}", 404)
    exiftool_path = _ensure_exiftool_available()
    r = subprocess.run([exiftool_path, abs_path], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if r.returncode != 0:
        return (f"ExifTool 오류: {r.stderr}", 500)
    return f"<pre>{r.stdout}</pre>"

@bp.get("/prompts")
def prompts_page():
    tags = get_all_tags_with_count()
    return render_template("prompts.html", tags=tags)


@bp.get("/tags")
def tags_page():
    items = get_booru_tags_with_counts()
    rating_counts = get_booru_rating_counts()
    total_images = get_dataset_image_count()
    category_presence = get_booru_category_presence_counts()
    rating_present = get_booru_rating_media_count()
    rating_labels = {
        0: "rating:general",
        1: "rating:sensitive",
        2: "rating:questionable",
        3: "rating:explicit",
    }
    rating_items = [
        {"tag": rating_labels[key], "category": "rating", "count": count}
        for key, count in sorted(rating_counts.items())
        if key in rating_labels and count > 0
    ]
    combined = [*items, *rating_items]
    groups: Dict[str, List[Dict[str, object]]] = {}
    for item in combined:
        category = (item.get("category") or "general").lower()
        groups.setdefault(category, []).append(item)

    def _sort_items(values: List[Dict[str, object]]) -> List[Dict[str, object]]:
        return sorted(values, key=lambda entry: (-int(entry.get("count") or 0), str(entry.get("tag") or "")))

    ordered_categories = ["rating", "copyright", "character", "artist", "general", "meta"]
    tag_groups = []
    for category in ordered_categories:
        tag_groups.append(
            {
                "category": category,
                "label": category.capitalize(),
                "items": _sort_items(groups.get(category, [])),
            }
        )
    extra_categories = sorted([cat for cat in groups.keys() if cat not in ordered_categories])
    for category in extra_categories:
        tag_groups.append(
            {
                "category": category,
                "label": category.capitalize(),
                "items": _sort_items(groups.get(category, [])),
            }
        )

    all_categories = [*ordered_categories, *extra_categories]
    missing_counts: Dict[str, int] = {}
    for category in all_categories:
        if category == "rating":
            missing = total_images - rating_present
        else:
            missing = total_images - category_presence.get(category, 0)
        missing_counts[category] = max(int(missing or 0), 0)

    for group in tag_groups:
        category = group.get("category") or ""
        group["missing_count"] = missing_counts.get(category, total_images)
        group["empty_label"] = "없음"

    return render_template("tags.html", tag_groups=tag_groups)

@bp.get("/autocomplete")
def autocomplete():
    from core.db.search_utils import autocomplete_tags
    q = (request.args.get("q") or "").strip()
    if not q: return jsonify([])
    return jsonify(autocomplete_tags(q, limit=10))

@bp.get("/remove_exif")
def remove_exif():
    abs_path = _resolve_media_path(request.args.get("path"))
    new_name_input = (request.args.get("name") or "").strip()
    scale = _parse_scale_value(request.args.get("scale"))
    if not abs_path:
        return ("경로가 잘못되었습니다.", 400)
    if not os.path.isfile(abs_path):
        return (f"파일을 찾을 수 없습니다: {abs_path}", 404)

    new_name = os.path.basename(new_name_input)
    if new_name in ("", ".", ".."):
        new_name = ""

    if _is_gif_path(abs_path):
        temp_dir = os.path.join(DEST, "_cleaned")
        os.makedirs(temp_dir, exist_ok=True)
        if new_name:
            download_name = new_name
            if not os.path.splitext(download_name)[1]:
                download_name = f"{download_name}.gif"
        else:
            download_name = f"{_make_random_name(10)}.gif"
        temp_name = f"{_make_random_name(12)}.gif"
        temp_path = os.path.join(temp_dir, temp_name)
        try:
            _strip_gif_metadata(abs_path, temp_path)
        except Exception as exc:
            return (f"GIF 메타데이터 제거 실패: {exc}", 500)

        @after_this_request
        def cleanup(response):
            def delayed_delete(path):
                time.sleep(1)
                try:
                    if platform.system() == "Windows":
                        try:
                            subprocess.run(
                                ["powershell", "-Command", f'Remove-Item -Path "{path}" -Stream Zone.Identifier'],
                                stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE
                            )
                        except Exception:
                            pass
                    if os.path.exists(path):
                        os.remove(path)
                except Exception:
                    pass
            threading.Thread(target=delayed_delete, args=(temp_path,), daemon=True).start()
            return response

        return send_file(
            temp_path,
            mimetype="image/gif",
            as_attachment=True,
            download_name=download_name,
        )

    temp_dir = os.path.join(DEST, "_cleaned")
    os.makedirs(temp_dir, exist_ok=True)

    if not new_name:
        rand = ''.join(secrets.choice(string.ascii_letters + string.digits) for _ in range(10))
        new_name = f"{rand}.png"

    new_path = os.path.join(temp_dir, new_name)
    try:
        with Image.open(abs_path) as img:
            resized = img
            new_size = _calculate_resized_dimensions(img.size, scale, None)
            if new_size and new_size != img.size:
                resized = img.resize(new_size, resample=Image.LANCZOS)
            target_mode = "RGBA" if "A" in resized.getbands() else "RGB"
            cleaned = resized.convert(target_mode)
            cleaned.save(new_path, "PNG")
    except Exception as exc:
        return (f"EXIF 제거 실패: {exc}", 500)

    @after_this_request
    def cleanup(response):
        def delayed_delete(path):
            time.sleep(1)
            try:
                if platform.system() == "Windows":
                    try:
                        subprocess.run(
                            ["powershell", "-Command", f'Remove-Item -Path "{path}" -Stream Zone.Identifier'],
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE
                        )
                    except Exception:
                        pass
                if os.path.exists(path):
                    os.remove(path)
            except Exception:
                pass
        threading.Thread(target=delayed_delete, args=(new_path,), daemon=True).start()
        return response

    return send_file(new_path, as_attachment=True, download_name=new_name)

@bp.get("/favicon.ico")
def favicon_blank():
    from flask import Response
    return Response(status=204)

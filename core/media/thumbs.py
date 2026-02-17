from __future__ import annotations

import logging
import os
import secrets
import string
import time
import subprocess
from pathlib import Path
from typing import Optional
from urllib.parse import unquote

from PIL import Image

import settings as _settings
from core.media.fftools import resolve_ffmpeg

from settings import DEST, DEST_FOLDER_NAME, DRAFTS_FOLDER_NAME

THUMB_SIZE_PX = 320
THUMB_CACHE_TTL_SECONDS = 60 * 60 * 24 * 7
THUMB_CACHE_DIR = os.path.join(DEST, "_thumbs")

VIDEO_EXTS = (".mp4", ".webm", ".mov", ".avi", ".mkv")

logger = logging.getLogger(__name__)


def _make_random_name(length: int = 12) -> str:
    alphabet = string.ascii_letters + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(length))


def strip_known_prefixes(path: str) -> str:
    base_prefixes = [p for p in ("Sorted_by_Date/", f"{DEST_FOLDER_NAME}/") if p]
    draft_prefix = f"{DRAFTS_FOLDER_NAME}/" if DRAFTS_FOLDER_NAME else ""
    changed = True
    while changed:
        changed = False
        for prefix in base_prefixes:
            if path.startswith(prefix):
                path = path[len(prefix):]
                changed = True
        if draft_prefix and path.startswith(f"{draft_prefix}{draft_prefix}"):
            path = path[len(draft_prefix):]
            changed = True
    return path


def _coerce_dest_relative(path: str) -> Optional[str]:
    if not path:
        return None
    dest_root = os.path.abspath(DEST)
    abs_path = os.path.abspath(os.path.normpath(path))
    try:
        common = os.path.commonpath([abs_path, dest_root])
    except ValueError:
        return None
    if common != dest_root:
        return None
    return os.path.relpath(abs_path, dest_root).replace("\\", "/")


def normalize_thumb_rel_path(rel_path: Optional[str]) -> Optional[str]:
    if not rel_path:
        return None

    decoded = unquote(rel_path).replace("\\", "/").strip()
    stripped = strip_known_prefixes(decoded).strip()
    if not stripped:
        return None

    drive, _ = os.path.splitdrive(stripped)
    if drive or stripped.startswith("/") or stripped.startswith("//"):
        coerced = _coerce_dest_relative(stripped)
        if not coerced:
            return None
        stripped = coerced

    normalized = os.path.normpath(stripped).replace("\\", "/").lstrip("/")

    if not normalized or normalized == ".":
        return None
    if normalized == ".." or normalized.startswith("../") or os.path.isabs(normalized):
        return None
    return normalized


def build_thumb_cache_path(normalized_rel_path: str) -> str:
    rel_dir = os.path.dirname(normalized_rel_path)
    base = os.path.splitext(os.path.basename(normalized_rel_path))[0]
    filename = f"{base}_{THUMB_SIZE_PX}.png"
    return os.path.join(THUMB_CACHE_DIR, rel_dir, filename)


def build_thumb_fallback_candidates(normalized_rel_path: str) -> list[str]:
    rel_dir = os.path.dirname(normalized_rel_path)
    base = os.path.splitext(os.path.basename(normalized_rel_path))[0]
    ext = os.path.splitext(normalized_rel_path)[1]
    candidates: list[str] = []
    if ext:
        candidates.append(os.path.join(THUMB_CACHE_DIR, rel_dir, f"{base}{ext}"))
    candidates.append(os.path.join(THUMB_CACHE_DIR, rel_dir, f"{base}.png"))
    seen: set[str] = set()
    ordered: list[str] = []
    for path in candidates:
        if path in seen:
            continue
        seen.add(path)
        ordered.append(path)
    return ordered


def thumb_cache_is_fresh(thumb_path: str, source_path: str) -> bool:
    if not os.path.isfile(thumb_path):
        return False
    try:
        thumb_mtime = os.path.getmtime(thumb_path)
        source_mtime = os.path.getmtime(source_path)
    except OSError:
        return False
    if thumb_mtime < source_mtime:
        return False
    if THUMB_CACHE_TTL_SECONDS <= 0:
        return True
    return (time.time() - thumb_mtime) <= THUMB_CACHE_TTL_SECONDS


def _is_video_source(path: str) -> bool:
    return os.path.splitext(path)[1].lower() in VIDEO_EXTS


def _generate_image_thumbnail(source_path: str, thumb_path: str) -> None:
    with Image.open(source_path) as img:
        if getattr(img, "is_animated", False):
            try:
                img.seek(0)
            except EOFError:
                pass
        converted = img.convert("RGBA") if "A" in img.getbands() else img.convert("RGB")
        converted.thumbnail((THUMB_SIZE_PX, THUMB_SIZE_PX), Image.LANCZOS)
        tmp_path = f"{thumb_path}.{_make_random_name(6)}.tmp"
        converted.save(tmp_path, "PNG")
        os.replace(tmp_path, thumb_path)


def generate_thumbnail(source_path: str, thumb_path: str) -> None:
    os.makedirs(os.path.dirname(thumb_path), exist_ok=True)

    if _is_video_source(source_path):
        ffmpeg = resolve_ffmpeg(_settings)
        # Keep temp file as PNG so ffmpeg chooses the right muxer.
        tmp_path = f"{thumb_path}.{_make_random_name(6)}.tmp.png"
        cmd = [
            str(ffmpeg),
            "-y",
            "-loglevel",
            "error",
            "-ss",
            "0.2",
            "-i",
            source_path,
            "-frames:v",
            "1",
            "-vf",
            f"scale={THUMB_SIZE_PX}:-2",
            tmp_path,
        ]
        result = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        if result.returncode != 0 or not os.path.isfile(tmp_path):
            details = (result.stderr or result.stdout or "").strip() or "ffmpeg thumbnail failed"
            try:
                if os.path.exists(tmp_path):
                    os.remove(tmp_path)
            except OSError:
                pass
            # Fallback to paired PNG if available (e.g., ComfyUI video meta PNG).
            pair_png = os.path.splitext(source_path)[0] + ".png"
            if os.path.isfile(pair_png):
                try:
                    _generate_image_thumbnail(pair_png, thumb_path)
                    return
                except Exception:
                    pass
            raise RuntimeError(details)
        os.replace(tmp_path, thumb_path)
        return

    _generate_image_thumbnail(source_path, thumb_path)


def build_thumbnail_cache(source_path: str) -> None:
    try:
        rel_path = os.path.relpath(source_path, DEST)
        normalized = normalize_thumb_rel_path(rel_path)
        if not normalized:
            return
        thumb_path = build_thumb_cache_path(normalized)
        if thumb_cache_is_fresh(thumb_path, source_path):
            return
        generate_thumbnail(source_path, thumb_path)
    except Exception as exc:
        logger.warning("⚠️ 썸네일 캐시 생성 실패: %s", source_path, exc_info=exc)

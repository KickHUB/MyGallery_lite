from __future__ import annotations

import re
from pathlib import Path
from typing import Iterable, Optional

import settings

# Shared date folder matcher.
DATE_FOLDER_PATTERN = re.compile(r"\d{4}-\d{2}-\d{2}")


def find_date_in_parts(parts: Iterable[str]) -> Optional[str]:
    """Return the first YYYY-MM-DD segment found in *parts*."""
    for part in parts:
        if DATE_FOLDER_PATTERN.fullmatch(str(part)):
            return str(part)
    return None


def get_content_root(dest_root: Path | str | None = None) -> Path:
    """Return the directory that directly contains date folders.

    New layout prefers: DEST/<DEST_CONTENT_SUBDIR>/YYYY-MM-DD/...
    Legacy layout:       DEST/YYYY-MM-DD/...

    The function is backward compatible:
    - If DEST/<subdir> exists and contains date folders, it wins.
    - Else if DEST contains date folders, use DEST.
    - Else if DEST/<subdir> exists (even empty), use it (for freshly migrated layouts).
    - Else fall back to DEST.
    """

    root = Path(dest_root or settings.DEST)
    subdir = (getattr(settings, "DEST_CONTENT_SUBDIR", "") or "").strip().strip("\\/")
    if not subdir:
        return root

    candidate = root / subdir

    def _has_date_folders(p: Path) -> bool:
        try:
            return any(
                child.is_dir() and DATE_FOLDER_PATTERN.fullmatch(child.name)
                for child in p.iterdir()
            )
        except Exception:
            return False

    if candidate.is_dir() and _has_date_folders(candidate):
        return candidate
    if root.is_dir() and _has_date_folders(root):
        return root
    if candidate.exists():
        return candidate
    return root


def get_date_root(dest_root: Path | str, date_str: str) -> Path:
    """Return the root folder for a given date (YYYY-MM-DD)."""
    return get_content_root(dest_root) / date_str


def _first_existing(base: Path, candidates: Iterable[str]) -> Optional[Path]:
    for name in candidates:
        if not name:
            continue
        p = base / name
        if p.is_dir():
            return p
    return None


def get_media_root(
    dest_root: Path | str,
    date_str: str,
    kind: str,
    *,
    create: bool = False,
) -> Path:
    """Return a directory where *kind* media should live for a date.

    The function supports both legacy and new layouts.

    kind: one of 'images', 'videos', 'audios', 'drafts'
    """

    dest_root = Path(dest_root)
    date_root = get_date_root(dest_root, date_str)

    kind_key = (kind or "").strip().lower()
    images_name = getattr(settings, "IMAGES_DIRNAME", "images") or "images"
    videos_name = getattr(settings, "VIDEOS_DIRNAME", "videos") or "videos"
    audios_name = getattr(settings, "AUDIOS_DIRNAME", "audios") or "audios"
    drafts_name = getattr(settings, "DRAFTS_IN_DATE_DIRNAME", "drafts") or "drafts"

    if kind_key == "images":
        # Prefer explicit images subfolder if present; otherwise legacy root.
        target = _first_existing(date_root, [images_name, "Images"])
        if target is None:
            # When creating, default to the new layout (date_root/<images_name>).
            target = (date_root / images_name) if create else date_root
    elif kind_key == "videos":
        target = _first_existing(date_root, [videos_name, "Videos"])
        if target is None:
            # When creating, default to the new layout (date_root/<videos_name>).
            # Legacy callers without create=True will still get date_root.
            target = (date_root / videos_name) if create else date_root
    elif kind_key == "audios":
        target = _first_existing(date_root, [audios_name, "Audios", "Audio"])
        if target is None:
            target = (date_root / audios_name) if create else date_root
    elif kind_key == "drafts":
        # New layout: date_root/drafts; Legacy layout: DEST/Drafts/YYYY-MM-DD
        target = _first_existing(date_root, [drafts_name, "Drafts"])
        if target is None:
            legacy_root = dest_root / (getattr(settings, "DRAFTS_FOLDER_NAME", "Drafts") or "Drafts") / date_str
            # When creating, prefer the new layout (date_root/<drafts_name>) even if legacy exists.
            if (not create) and legacy_root.is_dir():
                target = legacy_root
            else:
                target = (date_root / drafts_name)

    else:
        target = date_root

    if create:
        target.mkdir(parents=True, exist_ok=True)
    return target


def rel_under_dest(dest_root: Path | str, abs_path: Path | str) -> str:
    """Compute DB-relative path key as '<DEST_FOLDER_NAME>/<relative_to_DEST>'."""

    dest_root = Path(dest_root)
    abs_path = Path(abs_path)
    try:
        rel = abs_path.relative_to(dest_root).as_posix()
    except Exception:
        rel = abs_path.as_posix()
    dest_name = Path(dest_root).name
    return f"{dest_name}/{rel}".replace("\\", "/")


def extract_date_from_path(path: str, default: str = "unknown") -> str:
    parts = str(path).replace("\\", "/").split("/")
    found = find_date_in_parts(parts)
    return found or default

from __future__ import annotations

import logging
import os
import shutil
import sys
from pathlib import Path
from typing import Optional, Tuple

logger = logging.getLogger(__name__)


def _is_windows() -> bool:
    return os.name == "nt" or sys.platform.startswith("win")


def _exe_name(base: str) -> str:
    base = (base or "").strip()
    if not base:
        return base
    if _is_windows() and not base.lower().endswith('.exe'):
        return f"{base}.exe"
    return base


def _as_existing_path(raw: Optional[str]) -> Optional[Path]:
    if not raw:
        return None
    try:
        p = Path(str(raw)).expanduser()
    except Exception:
        return None
    if p.is_file():
        return p
    return None


def _from_same_dir(ffmpeg_path: Optional[Path], tool: str) -> Optional[Path]:
    if not ffmpeg_path:
        return None
    cand = ffmpeg_path.parent / _exe_name(tool)
    return cand if cand.is_file() else None


def _project_search(project_root: Path, tool: str) -> Optional[Path]:
    exe = _exe_name(tool)
    patterns = [
        f"ffmpeg/**/bin/{exe}",
        f"ffmpeg-*/bin/{exe}",
        f"ffmpeg/bin/{exe}",
    ]
    for pat in patterns:
        try:
            for hit in project_root.glob(pat):
                if hit.is_file():
                    return hit
        except Exception:
            continue

    # Fallback: scan any bin folder under the project.
    try:
        for hit in project_root.rglob(exe):
            if hit.is_file() and hit.parent.name.lower() == 'bin':
                return hit
    except Exception:
        pass
    return None


def _which(tool: str) -> Optional[Path]:
    exe = _exe_name(tool)
    found = shutil.which(exe) or shutil.which(tool)
    return Path(found) if found else None


def _resolve_one(settings, attr: str, tool: str) -> Path:
    """Resolve an FFmpeg-family tool path.

    Priority:
    1) settings.FF*_PATH + file exists
    2) Derive sibling tool from settings.FFMPEG_PATH
    3) Search project_root/ffmpeg/**/bin
    4) PATH fallback (shutil.which)
    """

    # 1) Explicit env / settings override
    explicit = _as_existing_path(getattr(settings, attr, '') or '')
    if explicit:
        return explicit

    # 2) From FFMPEG folder
    ffmpeg_path = _as_existing_path(getattr(settings, 'FFMPEG_PATH', '') or '')
    if tool == 'ffmpeg' and ffmpeg_path:
        return ffmpeg_path
    derived = _from_same_dir(ffmpeg_path, tool) if tool != 'ffmpeg' else None
    if derived:
        return derived

    # 3) Project search
    project_root = getattr(settings, 'PROJECT_ROOT', None)
    if project_root:
        try:
            pr = Path(project_root)
            if pr.exists():
                found = _project_search(pr, tool)
                if found:
                    return found
        except Exception:
            pass

    # 4) PATH
    found = _which(tool)
    if found:
        return found

    raise FileNotFoundError(
        f"{tool} not found. Set {attr} (or FFMPEG_PATH) in .env/settings, or add it to PATH."
    )


def resolve_ffmpeg(settings) -> Path:
    return _resolve_one(settings, 'FFMPEG_PATH', 'ffmpeg')


def resolve_ffprobe(settings) -> Path:
    return _resolve_one(settings, 'FFPROBE_PATH', 'ffprobe')


def resolve_ffplay(settings) -> Path:
    return _resolve_one(settings, 'FFPLAY_PATH', 'ffplay')


def resolve_all(settings) -> Tuple[Path, Path, Path]:
    return resolve_ffmpeg(settings), resolve_ffprobe(settings), resolve_ffplay(settings)

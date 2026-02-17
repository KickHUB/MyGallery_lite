from __future__ import annotations

import json
import logging
import subprocess
from pathlib import Path
from typing import Any, Dict, Optional

import settings
from core.media.fftools import resolve_ffprobe

logger = logging.getLogger(__name__)


def _pick_comment(tags: Dict[str, Any]) -> Optional[str]:
    """Pick comment/description from ffprobe tags."""

    if not tags:
        return None

    # ffprobe can return mixed-case keys; normalize by lower.
    normalized = {str(k).lower(): v for k, v in tags.items()}
    for key in ("comment", "description"):
        val = normalized.get(key)
        if isinstance(val, str) and val.strip():
            return val.strip()

    # Fallback: scan original keys
    for k, v in tags.items():
        lk = str(k).lower()
        if lk in {"comment", "description"} and isinstance(v, str) and v.strip():
            return v.strip()

    return None


def read_video_comfy_meta(video_path: Path, settings_mod=settings) -> Dict[str, Any]:
    """Read ComfyUI meta stored in a video container tag.

    Expected tag payload (format.tags.comment or description):
    {
      "prompt": "{... comfy prompt graph JSON string ...}",
      "workflow": { ... workflow JSON object ... }
    }

    Returns:
      {
        "comment_raw": str | None,
        "prompt": str | None,
        "workflow": dict | None,
      }
    """

    video_path = Path(video_path)
    result: Dict[str, Any] = {"comment_raw": None, "prompt": None, "workflow": None}

    if not video_path.is_file():
        return result

    ffprobe = resolve_ffprobe(settings_mod)
    cmd = [
        str(ffprobe),
        "-v",
        "error",
        "-print_format",
        "json",
        "-show_format",
        "-show_streams",
        str(video_path),
    ]

    proc = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if proc.returncode != 0:
        logger.debug("ffprobe failed for %s: %s", video_path, (proc.stderr or "").strip())
        return result

    try:
        data = json.loads(proc.stdout or "{}")
    except json.JSONDecodeError:
        return result

    fmt = data.get("format") or {}
    tags = fmt.get("tags") if isinstance(fmt, dict) else {}
    if not isinstance(tags, dict):
        tags = {}

    comment = _pick_comment(tags)
    if not comment:
        return result

    result["comment_raw"] = comment

    try:
        payload = json.loads(comment)
    except json.JSONDecodeError:
        return result

    if not isinstance(payload, dict):
        return result

    prompt = payload.get("prompt")
    workflow = payload.get("workflow")

    if isinstance(prompt, dict):
        # Some producers may embed dict instead of JSON string.
        prompt = json.dumps(prompt, ensure_ascii=False)

    if isinstance(prompt, str) and prompt.strip():
        result["prompt"] = prompt.strip()

    if isinstance(workflow, str):
        try:
            workflow = json.loads(workflow)
        except Exception:
            workflow = None

    if isinstance(workflow, dict):
        result["workflow"] = workflow

    return result


def detect_video_sound(video_path: Path, settings_mod=settings) -> Optional[bool]:
    """Return True if the video has audio streams, False if none, None on failure."""

    video_path = Path(video_path)
    if not video_path.is_file():
        return None

    ffprobe = resolve_ffprobe(settings_mod)
    cmd = [
        str(ffprobe),
        "-v",
        "error",
        "-print_format",
        "json",
        "-show_streams",
        "-select_streams",
        "a",
        str(video_path),
    ]

    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
    except OSError as exc:
        logger.debug("ffprobe 실행 실패: %s (%s)", video_path, exc)
        return None

    if proc.returncode != 0:
        logger.debug("ffprobe 오디오 검사 실패: %s (%s)", video_path, (proc.stderr or "").strip())
        return None

    try:
        data = json.loads(proc.stdout or "{}")
    except json.JSONDecodeError:
        return None

    streams = data.get("streams")
    if not isinstance(streams, list):
        return False

    return any(isinstance(stream, dict) for stream in streams)

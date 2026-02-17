from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path
from typing import Any, Callable, Dict, Optional

import settings as app_settings
from core.media.fftools import resolve_ffmpeg, resolve_ffplay, resolve_ffprobe
from core.utils.env_utils import update_env_vars

from . import portable_tools_setup as portable_setup

PROJECT_ROOT = Path(__file__).resolve().parents[2]
ENV_PATH = PROJECT_ROOT / ".env"

DEFAULT_WD14_MODEL = "wd-swinv2-tagger-v3"

PATH_KEYS = {
    "FFMPEG_PATH",
    "FFPROBE_PATH",
    "FFPLAY_PATH",
    "EXIFTOOL_PATH",
    "WD14_MODEL_PATH",
    "WD14_TAGS_CSV",
}


def _emit_log(log_cb: Optional[Callable[[str], None]], message: str) -> None:
    if callable(log_cb) and message:
        log_cb(message)


def _emit_progress(
    progress_cb: Optional[Callable[[float, str | None, Dict[str, Any] | None], None]],
    progress: float,
    message: str | None = None,
    summary: Dict[str, Any] | None = None,
) -> None:
    if callable(progress_cb):
        progress_cb(progress, message, summary)


def _is_cancelled(cancel_event: Any) -> bool:
    return bool(cancel_event is not None and getattr(cancel_event, "is_set", lambda: False)())


def _pick_wd14_model(model_key: str | None) -> str:
    requested = (model_key or "").strip()
    if requested and requested in portable_setup.WD14_MODELS:
        return requested
    if DEFAULT_WD14_MODEL in portable_setup.WD14_MODELS:
        return DEFAULT_WD14_MODEL
    return next(iter(portable_setup.WD14_MODELS.keys()))


def _apply_runtime_updates(updates: Dict[str, str]) -> None:
    expand_fn = getattr(app_settings, "_expand_path", None)
    for key, raw_value in (updates or {}).items():
        value = "" if raw_value is None else str(raw_value).strip()
        os.environ[key] = value
        if key in PATH_KEYS:
            resolved = value
            if value and callable(expand_fn):
                try:
                    resolved = expand_fn(value)
                except Exception:
                    resolved = value
            setattr(app_settings, key, resolved)
            continue
        setattr(app_settings, key, value)

    # Some modules import WD14_* values directly from settings at import time.
    for module_name in ("core.ops.watcher", "core.ops.full_refresh"):
        mod = sys.modules.get(module_name)
        if not mod:
            continue
        for key, raw_value in (updates or {}).items():
            if not key.startswith("WD14_"):
                continue
            value = "" if raw_value is None else str(raw_value).strip()
            if key in PATH_KEYS and callable(expand_fn):
                try:
                    value = expand_fn(value) if value else value
                except Exception:
                    pass
            if hasattr(mod, key):
                setattr(mod, key, value)

    if any(key.startswith("WD14_") for key in updates):
        try:
            from core.tagging.wd14_tagger import reset_wd14_session

            reset_wd14_session()
        except Exception:
            pass


def run_runtime_asset_install(
    *,
    target: str,
    model_key: str | None = None,
    progress_cb: Optional[Callable[[float, str | None, Dict[str, Any] | None], None]] = None,
    log_cb: Optional[Callable[[str], None]] = None,
    cancel_event: Any = None,
) -> Dict[str, Any]:
    target_norm = (target or "").strip().lower()
    tools_root = PROJECT_ROOT / "tools"
    tools_root.mkdir(parents=True, exist_ok=True)

    if target_norm not in {"ffmpeg", "exiftool", "wd14"}:
        return {"status": "error", "error": f"unsupported target: {target_norm}", "message": "지원하지 않는 설치 대상입니다."}

    if _is_cancelled(cancel_event):
        return {"status": "cancelled", "message": "사용자가 취소했습니다."}

    _emit_progress(progress_cb, 2, "설치 준비 중")

    updates: Dict[str, str] = {}
    summary: Dict[str, Any] = {"target": target_norm}

    try:
        if target_norm == "ffmpeg":
            _emit_log(log_cb, "FFmpeg/FFprobe 번들 설치를 시작합니다.")
            _emit_progress(progress_cb, 10, "FFmpeg/FFprobe 다운로드 및 압축 해제 중")
            updates = portable_setup._install_ffmpeg_bundle(
                repo_root=PROJECT_ROOT,
                tools_root=tools_root,
                want_ffmpeg=True,
                want_ffprobe=True,
            )
            summary["installed"] = "ffmpeg-bundle"

        elif target_norm == "exiftool":
            _emit_log(log_cb, "ExifTool 설치를 시작합니다.")
            _emit_progress(progress_cb, 8, "ExifTool 다운로드 URL 조회 중")
            exiftool_zip_url = portable_setup._resolve_exiftool_zip_url()
            if not exiftool_zip_url:
                return {
                    "status": "error",
                    "error": "exiftool_url_unavailable",
                    "message": "ExifTool 다운로드 URL을 찾지 못했습니다.",
                }
            _emit_log(log_cb, f"ExifTool URL: {exiftool_zip_url}")
            _emit_progress(progress_cb, 18, "ExifTool 다운로드 및 압축 해제 중")
            updates = portable_setup._install_exiftool(
                repo_root=PROJECT_ROOT,
                tools_root=tools_root,
                exiftool_zip_url=exiftool_zip_url,
            )
            summary["installed"] = "exiftool"

        elif target_norm == "wd14":
            selected_model = _pick_wd14_model(model_key)
            summary["model_key"] = selected_model
            _emit_log(log_cb, f"WD14 모델 설치를 시작합니다: {selected_model}")
            _emit_progress(progress_cb, 12, f"WD14 모델 다운로드 중 ({selected_model})")
            updates = portable_setup._install_wd14_model(
                repo_root=PROJECT_ROOT,
                tools_root=tools_root,
                model_key=selected_model,
            )
            summary["installed"] = f"wd14:{selected_model}"

        if _is_cancelled(cancel_event):
            return {"status": "cancelled", "message": "사용자가 취소했습니다."}

        if not updates:
            return {
                "status": "error",
                "error": "no_updates",
                "message": "설치 결과로 반영할 설정이 없습니다.",
            }

        _emit_progress(progress_cb, 88, ".env 파일 갱신 중")
        update_env_vars(updates, env_path=ENV_PATH.as_posix())
        _apply_runtime_updates(updates)

        summary["updated_keys"] = sorted(updates.keys())
        summary["values"] = updates
        _emit_progress(progress_cb, 100, "설치 완료", summary=summary)
        _emit_log(log_cb, f"설치 완료: {', '.join(summary['updated_keys'])}")
        return {"status": "ok", "message": "설치가 완료되었습니다.", "summary": summary}

    except Exception as exc:
        return {"status": "error", "error": str(exc), "message": str(exc)}


def _tool_state_from_resolver(
    key: str,
    resolver: Callable[[Any], Path],
) -> Dict[str, Any]:
    configured = str(getattr(app_settings, key, "") or "").strip()
    resolved = ""
    error = ""
    try:
        resolved = str(resolver(app_settings))
    except Exception as exc:
        error = str(exc)
    path_to_check = resolved or configured
    exists = bool(path_to_check and Path(path_to_check).is_file())
    return {
        "configured": configured,
        "resolved": resolved,
        "exists": exists,
        "error": error,
    }


def _resolve_exiftool_state() -> Dict[str, Any]:
    configured = str(getattr(app_settings, "EXIFTOOL_PATH", "") or "").strip()
    candidates: list[Path] = []
    if configured:
        candidates.append(Path(configured))
    local_name = "exiftool.exe" if os.name == "nt" else "exiftool"
    candidates.append(PROJECT_ROOT / "tools" / "exiftool" / local_name)
    which_hit = shutil.which("exiftool")
    if which_hit:
        candidates.append(Path(which_hit))

    resolved = ""
    for candidate in candidates:
        try:
            if candidate.is_file():
                resolved = candidate.as_posix()
                break
        except Exception:
            continue

    return {
        "configured": configured,
        "resolved": resolved,
        "exists": bool(resolved),
        "error": "" if resolved else "exiftool not found",
    }


def _resolve_wd14_state() -> Dict[str, Any]:
    model_configured = str(getattr(app_settings, "WD14_MODEL_PATH", "") or "").strip()
    tags_configured = str(getattr(app_settings, "WD14_TAGS_CSV", "") or "").strip()

    model_path = Path(model_configured) if model_configured else None
    model_exists = bool(model_path and model_path.is_file())

    tags_path: Optional[Path] = Path(tags_configured) if tags_configured else None
    if not (tags_path and tags_path.is_file()) and model_path:
        for candidate in (model_path.with_suffix(".csv"), model_path.parent / "selected_tags.csv"):
            if candidate.is_file():
                tags_path = candidate
                break
    tags_exists = bool(tags_path and tags_path.is_file())

    model_key = ""
    if model_path:
        parts = [p.lower() for p in model_path.parts]
        if "wd14" in parts:
            idx = parts.index("wd14")
            if idx + 1 < len(model_path.parts):
                model_key = model_path.parts[idx + 1]

    return {
        "model_path": model_path.as_posix() if model_path else "",
        "model_exists": model_exists,
        "tags_csv": tags_path.as_posix() if tags_path else tags_configured,
        "tags_exists": tags_exists,
        "model_key": model_key,
        "available_models": list(portable_setup.WD14_MODELS.keys()),
    }


def get_runtime_assets_meta() -> Dict[str, Any]:
    return {
        "ffmpeg": _tool_state_from_resolver("FFMPEG_PATH", resolve_ffmpeg),
        "ffprobe": _tool_state_from_resolver("FFPROBE_PATH", resolve_ffprobe),
        "ffplay": _tool_state_from_resolver("FFPLAY_PATH", resolve_ffplay),
        "exiftool": _resolve_exiftool_state(),
        "wd14": _resolve_wd14_state(),
    }

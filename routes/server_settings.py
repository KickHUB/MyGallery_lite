from __future__ import annotations

import os
import re
import sqlite3
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List

from flask import Blueprint, jsonify, request

from core.utils.env_utils import parse_env_text, update_env_vars, write_env_text
import settings

bp = Blueprint("server_settings", __name__)

_ENV_PATH = Path(__file__).resolve().parents[1] / ".env"
_ENV_KEY_REGEX = re.compile(r"^[A-Z0-9_]+$")

_DANGER_KEYS = {"SECRET_KEY"}
_REDACTED_VALUE = "__REDACTED__"
_DANGER_ENV_LINE_REGEX = re.compile(
    rf"^(\s*(?:export\s+)?)({'|'.join(re.escape(key) for key in sorted(_DANGER_KEYS))})\s*=.*$",
    re.MULTILINE,
)
_RESTART_REQUIRED_KEYS = {
    "PORT",
    "SECRET_KEY",
    "SOURCE",
    "DEST",
    "DEST_FOLDER_NAME",
    "INDEX",
    "FFMPEG_PATH",
    "FFPROBE_PATH",
    "FFPLAY_PATH",
    "EXIFTOOL_PATH",
    "SEARCH_USE_FTS",
}

_BASE_ENV_GROUPS: List[Dict[str, Any]] = [
    {
        "id": "paths",
        "label": "경로",
        "description": "SOURCE를 지정하면 DEST는 자동으로 SOURCE/DEST_FOLDER_NAME으로 계산됩니다.",
        "fields": [
            {
                "key": "SOURCE",
                "label": "SOURCE",
                "description": "생성 파일이 처음 저장되는 원본 폴더입니다. 이 폴더를 감시해 자동 정리를 수행합니다.",
                "type": "string",
                "picker": {"kind": "dir", "title": "SOURCE 폴더 선택"},
            },
            {
                "key": "DEST_FOLDER_NAME",
                "label": "DEST_FOLDER_NAME",
                "description": "SOURCE 아래 자동 생성될 정리 폴더 이름입니다. 실제 DEST는 SOURCE/DEST_FOLDER_NAME 입니다.",
                "type": "string",
            },
            {
                "key": "INDEX",
                "label": "INDEX",
                "description": "검색용 인덱스/캐시 저장 폴더입니다. 비워두면 기본 경로를 사용합니다.",
                "type": "string",
                "picker": {"kind": "dir", "title": "INDEX 폴더 선택"},
            },
            {
                "key": "FFMPEG_PATH",
                "label": "FFMPEG_PATH",
                "description": "영상 썸네일 생성/메타 처리에 사용하는 ffmpeg 실행 파일(.exe) 경로입니다.",
                "type": "string",
                "picker": {"kind": "file", "title": "ffmpeg 실행 파일 선택"},
            },
            {
                "key": "FFPROBE_PATH",
                "label": "FFPROBE_PATH",
                "description": "영상 메타 정보/오디오 유무 판별에 사용하는 ffprobe 실행 파일(.exe) 경로입니다.",
                "type": "string",
                "picker": {"kind": "file", "title": "ffprobe 실행 파일 선택"},
            },
            {
                "key": "FFPLAY_PATH",
                "label": "FFPLAY_PATH",
                "description": "영상 미리보기 재생에 사용하는 ffplay 실행 파일(.exe) 경로입니다.",
                "type": "string",
                "picker": {"kind": "file", "title": "ffplay 실행 파일 선택"},
            },
            {
                "key": "EXIFTOOL_PATH",
                "label": "EXIFTOOL_PATH",
                "description": "이미지 메타데이터 읽기/삭제에 사용하는 ExifTool 실행 파일(.exe) 경로입니다.",
                "type": "string",
                "picker": {"kind": "file", "title": "ExifTool 실행 파일 선택"},
            },

        ],
    },
    {
        "id": "server",
        "label": "서버",
        "description": "서버 동작/보안 설정",
        "fields": [
            {
                "key": "PORT",
                "label": "PORT",
                "description": "서비스 포트",
                "type": "int",
            },
            {
                "key": "ALLOWED_IPS",
                "label": "ALLOWED_IPS",
                "description": "접속 허용 IP 목록입니다. 쉼표(,)로 구분하며, 로컬호스트는 기본 허용됩니다.",
                "type": "string",
            },
            {
                "key": "SECRET_KEY",
                "label": "SECRET_KEY",
                "description": "세션 서명에 쓰는 보안 키입니다. 외부 노출 금지, 변경 시 기존 세션이 무효화됩니다.",
                "type": "string",
                "danger": True,
            },
        ],
    },
    {
        "id": "booru",
        "label": "Booru",
        "description": "Danbooru 태그 사전 설정",
        "fields": [
            {
                "key": "BOORU_DICT_SOURCE_KIND",
                "label": "BOORU_DICT_SOURCE_KIND",
                "description": "태그 사전 소스 종류를 선택합니다. hf/url/git/local 중 하나입니다.",
                "type": "select",
                "options": [
                    {"value": "hf", "label": "HF preset"},
                    {"value": "url", "label": "Custom URL"},
                    {"value": "git", "label": "Git repo"},
                    {"value": "local", "label": "Local file"},
                ],
            },
            {
                "key": "BOORU_DICT_SOURCE_PRESET",
                "label": "BOORU_DICT_SOURCE_PRESET",
                "description": "HF 프리셋 문자열입니다. 형식: hf:repo@ref:file.csv",
                "type": "string",
            },
            {
                "key": "BOORU_DICT_CACHE_DIR",
                "label": "BOORU_DICT_CACHE_DIR",
                "description": "태그 사전 캐시 경로",
                "type": "string",
                "picker": "dir",
            },
            {
                "key": "BOORU_DICT_SKIP_IF_SAME_SHA256",
                "label": "BOORU_DICT_SKIP_IF_SAME_SHA256",
                "description": "SHA256 동일 시 갱신 생략",
                "type": "bool",
            },
            {
                "key": "BOORU_DICT_CUSTOM_URL",
                "label": "BOORU_DICT_CUSTOM_URL",
                "description": "source kind=url 일 때 사용할 CSV 직접 URL입니다.",
                "type": "string",
            },
            {
                "key": "BOORU_DICT_GIT_URL",
                "label": "BOORU_DICT_GIT_URL",
                "description": "태그 Git repo URL",
                "type": "string",
            },
            {
                "key": "BOORU_DICT_GIT_REF",
                "label": "BOORU_DICT_GIT_REF",
                "description": "브랜치/태그/커밋",
                "type": "string",
            },
            {
                "key": "BOORU_DICT_GIT_FILE",
                "label": "BOORU_DICT_GIT_FILE",
                "description": "Git 저장소 내부 CSV 상대 경로입니다.",
                "type": "string",
            },
            {
                "key": "BOORU_DICT_LOCAL_FILE",
                "label": "BOORU_DICT_LOCAL_FILE",
                "description": "로컬 CSV 파일 경로입니다. source kind=local일 때 사용합니다.",
                "type": "string",
                "picker": "file",
            },
            {
                "key": "BOORU_TAG_SHOW_MANUAL",
                "label": "BOORU_TAG_SHOW_MANUAL",
                "description": "Danbooru 수동 태그 표시",
                "type": "bool",
            },
            {
                "key": "BOORU_TAG_SHOW_AUTO",
                "label": "BOORU_TAG_SHOW_AUTO",
                "description": "Danbooru 자동 태그 표시",
                "type": "bool",
            },
            {
                "key": "BOORU_TAG_SHOW_WD",
                "label": "BOORU_TAG_SHOW_WD",
                "description": "Danbooru 자동 WD 태그 표시",
                "type": "bool",
            },
        ],
    },
    {
        "id": "tags",
        "label": "태그 설정",
        "description": "WD14 자동 태깅 가중치/모델 설정",
        "fields": [
            {
                "key": "WD14_MODEL_PATH",
                "label": "WD14_MODEL_PATH",
                "description": "WD14 ONNX 모델 경로",
                "type": "string",
                "picker": "file",
            },
            {
                "key": "WD14_TAGS_CSV",
                "label": "WD14_TAGS_CSV",
                "description": "WD14 selected_tags.csv 경로 (비워두면 모델 경로 기준 자동 탐색)",
                "type": "string",
                "picker": "file",
            },
            {
                "key": "WD14_AUTO_TAG_ON_REFRESH",
                "label": "WD14_AUTO_TAG_ON_REFRESH",
                "description": "갤러리 분류 시 WD14 자동 태깅 실행",
                "type": "bool",
            },
            {
                "key": "WD14_PROVIDER_MODE",
                "label": "WD14_PROVIDER_MODE",
                "description": "WD14 실행 우선순위 (gpu_first/cpu_first/gpu_only/cpu_only)",
                "type": "select",
                "options": [
                    {"label": "GPU 우선", "value": "gpu_first"},
                    {"label": "CPU 우선", "value": "cpu_first"},
                    {"label": "GPU만 사용", "value": "gpu_only"},
                    {"label": "CPU만 사용", "value": "cpu_only"},
                ],
            },
            {
                "key": "WD14_PROVIDER_LIST",
                "label": "WD14_PROVIDER_LIST",
                "description": "실행 프로바이더 목록(쉼표 구분, 비우면 자동 결정)",
                "type": "string",
            },
            {
                "key": "WD14_THRESHOLD_GENERAL",
                "label": "WD14_THRESHOLD_GENERAL",
                "description": "General 태그 임계값",
                "type": "float",
            },
            {
                "key": "WD14_THRESHOLD_ARTIST",
                "label": "WD14_THRESHOLD_ARTIST",
                "description": "Artist 태그 임계값",
                "type": "float",
            },
            {
                "key": "WD14_THRESHOLD_COPYRIGHT",
                "label": "WD14_THRESHOLD_COPYRIGHT",
                "description": "Copyright 태그 임계값",
                "type": "float",
            },
            {
                "key": "WD14_THRESHOLD_CHARACTER",
                "label": "WD14_THRESHOLD_CHARACTER",
                "description": "Character 태그 임계값",
                "type": "float",
            },
            {
                "key": "WD14_THRESHOLD_META",
                "label": "WD14_THRESHOLD_META",
                "description": "Meta 태그 임계값",
                "type": "float",
            },
            {
                "key": "WD14_THRESHOLD_RATING",
                "label": "WD14_THRESHOLD_RATING",
                "description": "Rating 태그 임계값",
                "type": "float",
            },
        ],
    },
    {
        "id": "hf",
        "label": "Hugging Face",
        "description": "HF 캐시/링크 설정",
        "fields": [
            {
                "key": "HF_HOME",
                "label": "HF_HOME",
                "description": "HF 캐시 경로",
                "type": "string",
                "picker": "dir",
            },
            {
                "key": "HF_HUB_DISABLE_SYMLINKS",
                "label": "HF_HUB_DISABLE_SYMLINKS",
                "description": "심볼릭 링크 비활성화",
                "type": "bool",
            },
            {
                "key": "HF_HUB_DISABLE_HARDLINKS",
                "label": "HF_HUB_DISABLE_HARDLINKS",
                "description": "하드 링크 비활성화",
                "type": "bool",
            },
        ],
    },
    {
        "id": "perf",
        "label": "검색/성능",
        "description": "검색 성능 및 로그",
        "fields": [
            {
                "key": "USE_OFFSET_PAGINATION",
                "label": "USE_OFFSET_PAGINATION",
                "description": "오프셋 페이지네이션 사용",
                "type": "bool",
            },
            {
                "key": "SEARCH_TOTAL_CACHE_TTL_SECONDS",
                "label": "SEARCH_TOTAL_CACHE_TTL_SECONDS",
                "description": "검색 total 캐시 TTL(초)",
                "type": "int",
            },
            {
                "key": "PERF_LOGS",
                "label": "PERF_LOGS",
                "description": "성능 로그 출력",
                "type": "bool",
            },
            {
                "key": "THUMB_LOG_SUMMARY",
                "label": "THUMB_LOG_SUMMARY",
                "description": "썸네일 로그 요약",
                "type": "bool",
            },
            {
                "key": "SEARCH_USE_FTS",
                "label": "SEARCH_USE_FTS",
                "description": "FTS 검색 사용",
                "type": "bool",
            },
            {
                "key": "SPLIT_IMAGE_RELATION_LOADS",
                "label": "SPLIT_IMAGE_RELATION_LOADS",
                "description": "이미지 관계 분리 로드",
                "type": "bool",
            },
        ],
    },
]

_BASE_FIELD_META = {
    field["key"]: field
    for group in _BASE_ENV_GROUPS
    for field in group["fields"]
}


def _parse_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    raw = str(value).strip().lower()
    return raw in {"1", "true", "yes", "y", "on"}


def _is_restart_required(key: str) -> bool:
    if key in _RESTART_REQUIRED_KEYS:
        return True
    return key.startswith("BOORU_DICT_")


def _load_env_text() -> str:
    if _ENV_PATH.exists():
        return _ENV_PATH.read_text(encoding="utf-8")
    return ""


def _safe_parse_env(text: str) -> dict[str, str]:
    try:
        return parse_env_text(text)
    except ValueError:
        return {}


def _serialize_env_value(value: Any) -> str:
    if isinstance(value, bool):
        return "1" if value else "0"
    if value is None:
        return ""
    return str(value)


def _mask_danger_value(key: str, value: Any) -> Any:
    if key not in _DANGER_KEYS:
        return value
    raw = "" if value is None else str(value)
    return _REDACTED_VALUE if raw else ""


def _is_redacted_value(value: Any) -> bool:
    return str(value or "").strip() == _REDACTED_VALUE


def _mask_env_text(text: str) -> str:
    if not text or not _DANGER_KEYS:
        return text or ""
    return _DANGER_ENV_LINE_REGEX.sub(
        lambda m: f"{m.group(1)}{m.group(2)}={_REDACTED_VALUE}",
        text,
    )


def _restore_redacted_env_text(text: str, old_env: dict[str, str]) -> str:
    restored = text or ""
    for key in _DANGER_KEYS:
        pattern = re.compile(
            rf"^(\s*(?:export\s+)?{re.escape(key)}\s*=\s*){re.escape(_REDACTED_VALUE)}\s*$",
            re.MULTILINE,
        )
        restored = pattern.sub(lambda m: f"{m.group(1)}{old_env.get(key, '')}", restored)
    return restored


def _build_env_schema() -> Dict[str, Any]:
    groups = []
    for group in _BASE_ENV_GROUPS:
        fields = []
        for field in group["fields"]:
            key = field["key"]
            fields.append(
                {
                    **field,
                    "restart_required": _is_restart_required(key),
                    "danger": field.get("danger") or key in _DANGER_KEYS,
                }
            )
        groups.append({**group, "fields": fields})
    return {"groups": groups, "danger_keys": sorted(_DANGER_KEYS)}


def _get_value_for_key(key: str, setting_type: str) -> Any:
    env_map = _safe_parse_env(_load_env_text())
    if key in env_map:
        raw = env_map.get(key)
    elif key in os.environ:
        raw = os.environ.get(key)
    else:
        raw = getattr(settings, key, "")
    if setting_type == "int":
        try:
            return int(raw)
        except (TypeError, ValueError):
            return 0
    if setting_type == "bool":
        return _parse_bool(raw)
    if setting_type == "float":
        try:
            return float(raw)
        except (TypeError, ValueError):
            return 0.0
    return "" if raw is None else str(raw)


def _derive_dest_from_source(source_value: Any, dest_folder_name_value: Any) -> str:
    source_raw = "" if source_value is None else str(source_value).strip()
    folder_raw = "" if dest_folder_name_value is None else str(dest_folder_name_value).strip()
    if not source_raw:
        return ""
    folder_name = folder_raw or "Sorted_by_Date"

    expand_fn = getattr(settings, "_expand_path", None)
    if callable(expand_fn):
        try:
            source_resolved = expand_fn(source_raw)
        except Exception:
            source_resolved = source_raw
    else:
        source_resolved = source_raw

    return (Path(source_resolved) / folder_name).as_posix()


def _apply_runtime_setting(key: str, value: Any) -> None:
    if key == "USE_OFFSET_PAGINATION":
        from routes import gallery as gallery_module

        gallery_module.USE_OFFSET_PAGINATION = bool(value)
        return
    if key == "SEARCH_TOTAL_CACHE_TTL_SECONDS":
        from routes import gallery as gallery_module
        from core.db import search_utils as search_utils_module

        ttl_value = int(value)
        gallery_module.SEARCH_TOTAL_CACHE_TTL_SECONDS = ttl_value
        search_utils_module.SEARCH_TOTAL_CACHE_TTL_SECONDS = ttl_value
        search_utils_module._SEARCH_TOTAL_CACHE_TTL_SECONDS = float(ttl_value)
        return
    if key == "PERF_LOGS":
        from core.db import search_utils as search_utils_module
        from core.media import video_index as video_index_module

        enabled = bool(value)
        search_utils_module.PERF_LOGS = enabled
        video_index_module.PERF_LOGS = enabled
        main_module = sys.modules.get("main")
        if main_module:
            setattr(main_module, "PERF_LOGS", enabled)
            configure_logging = getattr(main_module, "_configure_logging", None)
            if callable(configure_logging):
                configure_logging()
        return
    if key == "THUMB_LOG_SUMMARY":
        enabled = bool(value)
        main_module = sys.modules.get("main")
        if main_module:
            setattr(main_module, "THUMB_LOG_SUMMARY", enabled)
            set_summary_enabled = getattr(main_module, "_set_thumb_log_summary_enabled", None)
            if callable(set_summary_enabled):
                set_summary_enabled(enabled)
        return
    if key == "SEARCH_USE_FTS":
        from core.db import search_utils as search_utils_module

        enabled = bool(value)
        search_utils_module.SEARCH_USE_FTS = enabled
        if enabled:
            conn = sqlite3.connect(search_utils_module.DB_PATH)
            try:
                cur = conn.cursor()
                search_utils_module.ensure_fts_tables(cur, conn, rebuild=search_utils_module.FTS_AUTO_BUILD)
            finally:
                conn.close()
        else:
            search_utils_module._fts_search_enabled = False
        return
    if key == "SPLIT_IMAGE_RELATION_LOADS":
        from core.db import search_utils as search_utils_module

        search_utils_module.SPLIT_IMAGE_RELATION_LOADS = bool(value)
        return
    if key.startswith("WD14_"):
        value_str = "" if value is None else str(value)
        if key in {"WD14_MODEL_PATH", "WD14_TAGS_CSV"}:
            expand_fn = getattr(settings, "_expand_path", None)
            if callable(expand_fn) and value_str:
                value_str = expand_fn(value_str)
            setattr(settings, key, value_str)
        else:
            setattr(settings, key, value if not isinstance(value, str) else value_str)
        from core.tagging import wd14_tagger as wd14_tagger_module

        wd14_tagger_module.reset_wd14_session()
        return
    if key in {
        "BOORU_DICT_SOURCE_KIND",
        "BOORU_DICT_SOURCE_PRESET",
        "BOORU_DICT_CACHE_DIR",
        "BOORU_DICT_SKIP_IF_SAME_SHA256",
        "BOORU_DICT_CUSTOM_URL",
        "BOORU_DICT_GIT_URL",
        "BOORU_DICT_GIT_REF",
        "BOORU_DICT_GIT_FILE",
        "BOORU_DICT_LOCAL_FILE",
    }:
        value_str = "" if value is None else str(value).strip()
        if key == "BOORU_DICT_SOURCE_KIND":
            value_str = value_str.lower()
        if key == "BOORU_DICT_LOCAL_FILE":
            expand_fn = getattr(settings, "_expand_path", None)
            if callable(expand_fn) and value_str:
                value_str = expand_fn(value_str)
        setattr(settings, key, value_str)
        return


def _parse_payload_value(key: str, value: Any, setting_type: str, meta: Dict[str, Any] | None = None) -> Any:
    if setting_type == "bool":
        return _parse_bool(value)
    if setting_type == "int":
        try:
            return int(value)
        except (TypeError, ValueError):
            raise ValueError(f"{key} 값이 올바른 숫자가 아닙니다.")
    if setting_type == "float":
        try:
            return float(value)
        except (TypeError, ValueError):
            raise ValueError(f"{key} 값이 올바른 숫자가 아닙니다.")
    if setting_type == "select":
        raw = "" if value is None else str(value).strip()
        options = meta.get("options") if meta else None
        if options:
            allowed = {
                str(opt.get("value")).strip()
                for opt in options
                if isinstance(opt, dict) and opt.get("value") is not None
            }
            if raw and allowed and raw not in allowed:
                raise ValueError(f"{key} 값이 허용된 옵션에 없습니다.")
        return raw
    return "" if value is None else str(value)


def _validate_env_text(text: str) -> dict[str, str]:
    parsed: dict[str, str] = {}
    for idx, line in enumerate(text.splitlines(), start=1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped.lower().startswith("export "):
            stripped = stripped[7:].strip()
        if "=" not in stripped:
            raise ValueError(f"Invalid env line at {idx}: {line}")
        key, value = stripped.split("=", 1)
        key = key.strip()
        if not key or not _ENV_KEY_REGEX.match(key):
            raise ValueError(f"Invalid env line at {idx}: {line}")
        parsed[key] = value
    return parsed


def _collect_schema_values(schema: Dict[str, Any]) -> Dict[str, Any]:
    values: Dict[str, Any] = {}
    for group in schema.get("groups", []):
        for field in group.get("fields", []):
            key = field.get("key")
            if not key:
                continue
            raw_value = _get_value_for_key(key, field.get("type") or "string")
            values[key] = _mask_danger_value(key, raw_value)
    return values


def _resolve_initial_dir(initial: str | None) -> str | None:
    if not initial:
        return None
    try:
        candidate = Path(str(initial)).expanduser()
    except Exception:
        return None
    if candidate.is_dir():
        return candidate.as_posix()
    parent = candidate.parent
    if parent.exists():
        return parent.as_posix()
    return None


def _ps_quote(value: str) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def _open_path_dialog_powershell(kind: str, title: str | None = None, initial: str | None = None) -> str:
    if os.name != "nt":
        raise RuntimeError("powershell fallback is only supported on Windows")

    title_text = title or ("Select folder" if kind == "dir" else "Select file")
    initial_dir = _resolve_initial_dir(initial) or ""
    title_lit = _ps_quote(title_text)
    initial_lit = _ps_quote(initial_dir)

    if kind == "dir":
        script = f"""
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Windows.Forms
[System.Windows.Forms.Application]::EnableVisualStyles()
$dialog = New-Object System.Windows.Forms.FolderBrowserDialog
$dialog.Description = {title_lit}
$dialog.ShowNewFolderButton = $true
if ({initial_lit} -and (Test-Path {initial_lit})) {{ $dialog.SelectedPath = {initial_lit} }}
$result = $dialog.ShowDialog()
if ($result -eq [System.Windows.Forms.DialogResult]::OK) {{ Write-Output $dialog.SelectedPath }}
"""
    else:
        script = f"""
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Windows.Forms
[System.Windows.Forms.Application]::EnableVisualStyles()
$dialog = New-Object System.Windows.Forms.OpenFileDialog
$dialog.Title = {title_lit}
$dialog.Filter = 'All files (*.*)|*.*'
if ({initial_lit} -and (Test-Path {initial_lit})) {{ $dialog.InitialDirectory = {initial_lit} }}
$result = $dialog.ShowDialog()
if ($result -eq [System.Windows.Forms.DialogResult]::OK) {{ Write-Output $dialog.FileName }}
"""

    try:
        completed = subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-Sta",
                "-Command",
                script,
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=300,
        )
    except FileNotFoundError as exc:
        raise RuntimeError("powershell not found") from exc

    if completed.returncode != 0:
        details = (completed.stderr or completed.stdout or "").strip()
        raise RuntimeError(details or "powershell dialog failed")

    return (completed.stdout or "").strip()


def _open_path_dialog_tk(kind: str, title: str | None = None, initial: str | None = None) -> str:
    try:
        import tkinter as tk
        from tkinter import filedialog
    except Exception as exc:
        raise RuntimeError(f"tkinter unavailable: {exc}") from exc

    root = tk.Tk()
    root.withdraw()
    initial_dir = _resolve_initial_dir(initial)

    def _front_dialog() -> None:
        try:
            root.deiconify()
            root.lift()
            root.attributes("-topmost", True)
            root.update()
            root.after(200, lambda: root.attributes("-topmost", False))
        except Exception:
            pass

    try:
        _front_dialog()
        if kind == "dir":
            options = {"parent": root, "title": title or "Select folder"}
            if initial_dir:
                options["initialdir"] = initial_dir
            path = filedialog.askdirectory(**options)
        else:
            options = {
                "parent": root,
                "title": title or "Select file",
                "filetypes": [("All files", "*.*")],
            }
            if initial_dir:
                options["initialdir"] = initial_dir
            path = filedialog.askopenfilename(**options)
        root.withdraw()
        return path or ""
    finally:
        try:
            root.destroy()
        except Exception:
            pass


def _open_path_dialog(kind: str, title: str | None = None, initial: str | None = None) -> str:
    # On Windows, prefer PowerShell dialog first.
    # Tk dialogs can freeze/hang when invoked from threaded Flask request handlers.
    if os.name == "nt":
        ps_error: Exception | None = None
        try:
            return _open_path_dialog_powershell(kind, title=title, initial=initial)
        except Exception as exc:
            ps_error = exc
        try:
            return _open_path_dialog_tk(kind, title=title, initial=initial)
        except Exception as tk_exc:
            raise RuntimeError(f"{ps_error}; tkinter fallback failed: {tk_exc}") from tk_exc

    tk_error: Exception | None = None
    try:
        return _open_path_dialog_tk(kind, title=title, initial=initial)
    except Exception as exc:
        tk_error = exc
    raise RuntimeError(str(tk_error))


@bp.get("/api/settings/env/schema")
def api_env_schema():
    return jsonify({"ok": True, **_build_env_schema()})


@bp.get("/api/settings/env")
def api_env_values():
    schema = _build_env_schema()
    return jsonify({"ok": True, "values": _collect_schema_values(schema)})


@bp.post("/api/settings/env/pick_path")
def api_env_pick_path():
    payload = request.get_json(silent=True) or {}
    kind = str(payload.get("kind") or "").strip().lower()
    if kind not in {"file", "dir"}:
        kind = "file"
    title = payload.get("title")
    if title is not None:
        title = str(title).strip()
    initial = payload.get("initial")
    if initial is not None:
        initial = str(initial).strip()
    try:
        path = _open_path_dialog(kind, title=title, initial=initial)
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 500
    return jsonify({"ok": True, "path": path, "cancelled": not bool(path)})


@bp.post("/api/settings/env")
def api_env_update():
    payload = request.get_json(silent=True) or {}
    updates = payload.get("updates") if isinstance(payload.get("updates"), dict) else payload

    if not isinstance(updates, dict) or not updates:
        return jsonify({"ok": False, "error": "저장할 설정이 없습니다."}), 400

    invalid_keys = [key for key in updates.keys() if key not in _BASE_FIELD_META]
    if invalid_keys:
        return jsonify({"ok": False, "error": f"허용되지 않은 키가 포함되어 있습니다: {', '.join(invalid_keys)}"}), 400

    env_updates: Dict[str, str] = {}
    runtime_updates: Dict[str, Any] = {}
    restart_keys: List[str] = []

    for key, value in updates.items():
        meta = _BASE_FIELD_META.get(key, {"type": "string"})
        try:
            parsed_value = _parse_payload_value(key, value, meta.get("type", "string"), meta)
        except ValueError as exc:
            return jsonify({"ok": False, "error": str(exc)}), 400

        if key in _DANGER_KEYS and _is_redacted_value(parsed_value):
            # UI sends redacted placeholders for danger keys when unchanged.
            continue

        env_updates[key] = _serialize_env_value(parsed_value)
        runtime_updates[key] = parsed_value
        if _is_restart_required(key):
            restart_keys.append(key)

    # Lite policy: DEST is not user-editable; always derived from SOURCE/DEST_FOLDER_NAME.
    if "SOURCE" in updates or "DEST_FOLDER_NAME" in updates:
        source_value = runtime_updates.get("SOURCE", _get_value_for_key("SOURCE", "string"))
        folder_value = runtime_updates.get("DEST_FOLDER_NAME", _get_value_for_key("DEST_FOLDER_NAME", "string"))
        derived_dest = _derive_dest_from_source(source_value, folder_value)
        env_updates["DEST"] = derived_dest
        runtime_updates["DEST"] = derived_dest
        if "DEST" not in restart_keys:
            restart_keys.append("DEST")

    if env_updates:
        update_env_vars(env_updates, env_path=str(_ENV_PATH))
        for key, value in env_updates.items():
            os.environ[key] = str(value)

    for key, value in runtime_updates.items():
        if not _is_restart_required(key):
            _apply_runtime_setting(key, value)

    schema = _build_env_schema()
    return jsonify(
        {
            "ok": True,
            "values": _collect_schema_values(schema),
            "restart_required": bool(restart_keys),
            "restart_required_keys": restart_keys,
        }
    )


@bp.get("/api/settings/env/raw")
def api_env_raw_get():
    return jsonify({"ok": True, "text": _mask_env_text(_load_env_text())})


@bp.post("/api/settings/env/raw")
def api_env_raw_update():
    payload = request.get_json(silent=True) or {}
    text = payload.get("text")
    if text is None:
        return jsonify({"ok": False, "error": "저장할 텍스트가 없습니다."}), 400

    old_env_text = _load_env_text()
    old_env = _safe_parse_env(old_env_text)
    normalized_text = _restore_redacted_env_text(str(text), old_env)

    try:
        new_env = _validate_env_text(normalized_text)
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400

    added_keys = sorted(key for key in new_env.keys() if key not in old_env)
    removed_keys = sorted(key for key in old_env.keys() if key not in new_env)
    changed_keys = sorted(
        key for key in new_env.keys() if key in old_env and new_env[key] != old_env[key]
    )

    dry_run = str(request.args.get("dry_run", "")).lower() in {"1", "true", "yes"}
    if not dry_run:
        write_env_text(normalized_text, env_path=str(_ENV_PATH))
        for key in removed_keys:
            os.environ.pop(key, None)
        for key, value in new_env.items():
            os.environ[key] = value

    return jsonify(
        {
            "ok": True,
            "added_keys": added_keys,
            "removed_keys": removed_keys,
            "changed_keys": changed_keys,
            "restart_required": True,
            "dry_run": dry_run,
        }
    )

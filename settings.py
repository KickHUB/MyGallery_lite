# settings.py (lite manual SOURCE + derived DEST)
from __future__ import annotations

import os
import ast
from pathlib import Path
from typing import List, Optional
try:
    from dotenv import load_dotenv  # type: ignore
except Exception:
    def load_dotenv(*args, **kwargs):
        return False

# -----------------------------
# Project directories
# -----------------------------
PROJECT_ROOT = Path(__file__).resolve().parent
DATA_DIR = PROJECT_ROOT / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)

ENV_FILE = PROJECT_ROOT / ".env"
if ENV_FILE.exists():
    load_dotenv(ENV_FILE.as_posix())
else:
    load_dotenv()

# -----------------------------
# Helpers
# -----------------------------
def _special_dirs() -> dict:
    user = Path(os.environ.get("USERPROFILE", "~")).expanduser()
    return {
        "USERPROFILE": user.as_posix(),
        "DESKTOP": (user / "Desktop").as_posix(),
        "DOWNLOADS": (user / "Downloads").as_posix(),
        "PROJECT": PROJECT_ROOT.as_posix(),
    }

def _expand_path(p: str) -> str:
    if not p:
        return ""
    for key, val in _special_dirs().items():
        p = p.replace("{" + key + "}", val)
    p = os.path.expandvars(os.path.expanduser(p))
    pp = Path(p)
    if not pp.is_absolute():
        pp = PROJECT_ROOT / pp
    return pp.as_posix()

def _depth(path: Path) -> int:
    try:
        return len(path.resolve().parts)
    except Exception:
        return len(path.parts)

def _find_comfy_output(roots: List[Path], max_depth: int = 6) -> Optional[Path]:
    """Search under likely roots for a folder named 'output' (ComfyUI output)."""
    candidates: List[Path] = []
    for r in roots:
        if not r.exists() or not r.is_dir():
            continue
        base_depth = _depth(r)
        try:
            for cur, dirs, files in os.walk(r.as_posix()):
                curp = Path(cur)
                if _depth(curp) - base_depth > max_depth:
                    dirs[:] = []  # prune deep
                    continue
                if curp.name.lower() == "output":
                    candidates.append(curp)
        except Exception:
            continue
    if not candidates:
        return None
    candidates.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return candidates[0]

def _autodetect_template_folder() -> str:
    candidates = ["client/templates", "templates", "."]
    for rel in candidates:
        base = PROJECT_ROOT / rel
        if (base / "index.html").exists():
            return base.as_posix()
    # if only index.html.txt exists, still point there so render_template can find others
    for rel in candidates:
        base = PROJECT_ROOT / rel
        if (base / "index.html.txt").exists():
            return base.as_posix()
    return PROJECT_ROOT.as_posix()

def _autodetect_static_folder() -> str:
    candidates = ["client/static", "static", "client", "."]
    for rel in candidates:
        base = PROJECT_ROOT / rel
        if any((base / name).exists() for name in ("style.css", "script.js", "favicon.ico")):
            return base.as_posix()
    return PROJECT_ROOT.as_posix()

def _to_int(x: str, default: int) -> int:
    try:
        return int(str(x).strip())
    except Exception:
        return default

def _to_bool(x: str, default: bool = False) -> bool:
    if x is None:
        return default
    value = str(x).strip().lower()
    if value in {"1", "true", "yes", "y", "on"}:
        return True
    if value in {"0", "false", "no", "n", "off"}:
        return False
    return default

def _to_float(x: str, default: float) -> float:
    try:
        return float(str(x).strip())
    except Exception:
        return default


def _parse_allowed_ips(raw: str) -> List[str]:
    text = (raw or "").strip()
    if not text:
        text = "127.0.0.1,localhost"

    ips: List[str] = []

    # Backward compatibility: allow python-list-like values
    # e.g. "['127.0.0.1', 'localhost']".
    if text.startswith("[") and text.endswith("]"):
        try:
            parsed = ast.literal_eval(text)
        except Exception:
            parsed = None
        if isinstance(parsed, (list, tuple, set)):
            for item in parsed:
                token = str(item).strip().strip("\"'")
                if token:
                    ips.append(token)
            if ips:
                return ips

    for part in text.split(","):
        token = part.strip().strip("[]").strip().strip("\"'")
        if token:
            ips.append(token)

    return ips

# -----------------------------
# Config with smart fallbacks
# -----------------------------
DEST_FOLDER_NAME = os.getenv("DEST_FOLDER_NAME", "Sorted_by_Date")
DRAFTS_FOLDER_NAME = os.getenv("DRAFTS_FOLDER_NAME", "Drafts")

# -----------------------------
# New layout options (backward compatible)
# -----------------------------
# When enabled, date folders live under DEST/<DEST_CONTENT_SUBDIR>/YYYY-MM-DD/...
# Example: DEST/source/2026-01-29/images, videos, audios, drafts
DEST_CONTENT_SUBDIR = os.getenv("DEST_CONTENT_SUBDIR", "source").strip().strip('\\/ ')
IMAGES_DIRNAME = os.getenv("IMAGES_DIRNAME", "images").strip() or "images"
VIDEOS_DIRNAME = os.getenv("VIDEOS_DIRNAME", "videos").strip() or "videos"
AUDIOS_DIRNAME = os.getenv("AUDIOS_DIRNAME", "audios").strip() or "audios"
DRAFTS_IN_DATE_DIRNAME = os.getenv("DRAFTS_IN_DATE_DIRNAME", "drafts").strip() or "drafts"

GALLERY_CACHE_TTL_SECONDS = _to_int(os.getenv("GALLERY_CACHE_TTL_SECONDS", "60"), 60)
USE_OFFSET_PAGINATION = _to_bool(os.getenv("USE_OFFSET_PAGINATION", "true"), False)
# Performance logs (request/DB timing)
PERF_LOGS = _to_bool(os.getenv("PERF_LOGS", "true"), True)
THUMB_LOG_SUMMARY = _to_bool(os.getenv("THUMB_LOG_SUMMARY", "true"), True)
DEBUG_MODE = _to_bool(os.getenv("DEBUG_MODE", "false"), False)
SPLIT_IMAGE_RELATION_LOADS = _to_bool(os.getenv("SPLIT_IMAGE_RELATION_LOADS", "true"), True)
SEARCH_USE_FTS = _to_bool(os.getenv("SEARCH_USE_FTS", "true"), True)
FTS_AUTO_BUILD = _to_bool(os.getenv("FTS_AUTO_BUILD", "false"), False)
METADATA_MISSING_EXTENDED_CHECKS = _to_bool(
    os.getenv("METADATA_MISSING_EXTENDED_CHECKS", "true"),
    True,
)
SEARCH_TOTAL_CACHE_TTL_SECONDS = _to_int(
    os.getenv("SEARCH_TOTAL_CACHE_TTL_SECONDS", "600"),
    600,
)
SEARCH_TOTAL_DATASET_COUNT_TTL_SECONDS = _to_int(
    os.getenv("SEARCH_TOTAL_DATASET_COUNT_TTL_SECONDS", "300"),
    300,
)
SEARCH_TOTAL_LARGE_DATASET_THRESHOLD = _to_int(
    os.getenv("SEARCH_TOTAL_LARGE_DATASET_THRESHOLD", "200000"),
    200000,
)
SEARCH_TOTAL_SKIP_LARGE_DATASET_TOTALS = _to_bool(
    os.getenv("SEARCH_TOTAL_SKIP_LARGE_DATASET_TOTALS", "true"),
    True,
)
INTEGRITY_MISSING_SAMPLES_LIMIT = _to_int(
    os.getenv("INTEGRITY_MISSING_SAMPLES_LIMIT", "20"),
    20,
)
INTEGRITY_DIAGNOSTICS_LIMIT = _to_int(
    os.getenv("INTEGRITY_DIAGNOSTICS_LIMIT", "20"),
    20,
)
SECRET_KEY = os.getenv("SECRET_KEY", "").strip()

SOURCE_RAW = os.getenv("SOURCE", "").strip()
DEST_RAW   = os.getenv("DEST", "").strip()  # Legacy key (Lite uses SOURCE + DEST_FOLDER_NAME).

# Lite policy:
# - SOURCE is user-managed (no automatic path discovery).
# - DEST is always derived as SOURCE/DEST_FOLDER_NAME.
SOURCE = _expand_path(SOURCE_RAW) if SOURCE_RAW else ""
if SOURCE:
    DEST = (Path(SOURCE) / DEST_FOLDER_NAME).as_posix()
else:
    DEST = ""

# Create DEST only when SOURCE currently exists as a directory.
try:
    if SOURCE and Path(SOURCE).is_dir() and DEST:
        Path(DEST).mkdir(parents=True, exist_ok=True)
except Exception:
    pass

# -----------------------------
# Legacy constants expected by the app
# -----------------------------
TEMPLATE_FOLDER = os.getenv("TEMPLATE_FOLDER", _autodetect_template_folder())
STATIC_FOLDER   = os.getenv("STATIC_FOLDER",   _autodetect_static_folder())

INDEX_DIR = os.getenv("INDEX", "").strip()

# FF tools (user override first)
FFMPEG_PATH_RAW = os.getenv("FFMPEG_PATH", "").strip()
FFPROBE_PATH_RAW = os.getenv("FFPROBE_PATH", "").strip()
FFPLAY_PATH_RAW = os.getenv("FFPLAY_PATH", "").strip()

# Handle user mistake: concatenated quoted paths like
# "...\ffmpeg.exe""...\ffplay.exe""...\ffprobe.exe"
# If any env var contains such a string, split and distribute by basename.
import re as _re

def _split_quoted_exe_paths(raw: str) -> list[str]:
    try:
        return _re.findall(r'"([^"]+\.exe)"', raw or '')
    except Exception:
        return []

def _distribute_fftool_paths(raw: str) -> None:
    global FFMPEG_PATH_RAW, FFPROBE_PATH_RAW, FFPLAY_PATH_RAW
    matches = _split_quoted_exe_paths(raw)
    if not matches:
        return
    for p in matches:
        base = os.path.basename(p).lower()
        if 'ffmpeg' in base and not FFMPEG_PATH_RAW:
            FFMPEG_PATH_RAW = p
        elif 'ffprobe' in base and not FFPROBE_PATH_RAW:
            FFPROBE_PATH_RAW = p
        elif 'ffplay' in base and not FFPLAY_PATH_RAW:
            FFPLAY_PATH_RAW = p
    # Also overwrite FFMPEG_PATH_RAW if it still looks concatenated and we found an ffmpeg path.
    if matches:
        for p in matches:
            base = os.path.basename(p).lower()
            if 'ffmpeg' in base:
                FFMPEG_PATH_RAW = p
                break

# Apply distribution only when probe/play are missing; but allow filling missing ones from any raw.
if (not FFPROBE_PATH_RAW or not FFPLAY_PATH_RAW) or _split_quoted_exe_paths(FFMPEG_PATH_RAW):
    for raw in (FFMPEG_PATH_RAW, FFPROBE_PATH_RAW, FFPLAY_PATH_RAW):
        if _split_quoted_exe_paths(raw):
            _distribute_fftool_paths(raw)

# Strip leftover quotes
FFMPEG_PATH_RAW = (FFMPEG_PATH_RAW or '').strip().strip('"')
FFPROBE_PATH_RAW = (FFPROBE_PATH_RAW or '').strip().strip('"')
FFPLAY_PATH_RAW = (FFPLAY_PATH_RAW or '').strip().strip('"')
EXIFTOOL_PATH_RAW = os.getenv("EXIFTOOL_PATH", "").strip().strip('"')

FFMPEG_PATH = _expand_path(FFMPEG_PATH_RAW) if FFMPEG_PATH_RAW else ""
FFPROBE_PATH = _expand_path(FFPROBE_PATH_RAW) if FFPROBE_PATH_RAW else ""
FFPLAY_PATH = _expand_path(FFPLAY_PATH_RAW) if FFPLAY_PATH_RAW else ""
EXIFTOOL_PATH = _expand_path(EXIFTOOL_PATH_RAW) if EXIFTOOL_PATH_RAW else ""

PORT  = _to_int(os.getenv("PORT", "7860"), 7860)
ALLOWED_IPS = _parse_allowed_ips(os.getenv("ALLOWED_IPS", "127.0.0.1,localhost"))

# Database path (inside project)
DB_PATH = (DATA_DIR / "gallery.db").as_posix()

# Database backup settings
DB_BACKUP_DIR_RAW = os.getenv("DB_BACKUP_DIR", "").strip()
DB_BACKUP_DIR = _expand_path(DB_BACKUP_DIR_RAW) if DB_BACKUP_DIR_RAW else ""
if not DB_BACKUP_DIR:
    DB_BACKUP_DIR = (DATA_DIR / "db_backups").as_posix()
try:
    Path(DB_BACKUP_DIR).mkdir(parents=True, exist_ok=True)
except Exception:
    DB_BACKUP_DIR = ""

MAX_DB_BACKUPS = _to_int(os.getenv("MAX_DB_BACKUPS", "10"), 10)

# Danbooru tag dictionary update
BOORU_DICT_SOURCE_PRESET = os.getenv(
    "BOORU_DICT_SOURCE_PRESET",
    "hf:newtextdoc1111/danbooru-tag-csv@main:danbooru_tags.csv",
).strip()
BOORU_DICT_CACHE_DIR_RAW = os.getenv("BOORU_DICT_CACHE_DIR", "data/booru_cache").strip()
if BOORU_DICT_CACHE_DIR_RAW:
    BOORU_DICT_CACHE_DIR = _expand_path(BOORU_DICT_CACHE_DIR_RAW)
else:
    BOORU_DICT_CACHE_DIR = (DATA_DIR / "booru_cache").as_posix()
BOORU_DICT_SKIP_IF_SAME_SHA256 = _to_bool(os.getenv("BOORU_DICT_SKIP_IF_SAME_SHA256", "true"), True)
BOORU_DICT_ALLOW_CUSTOM_URL = _to_bool(os.getenv("BOORU_DICT_ALLOW_CUSTOM_URL", "false"), False)
BOORU_DICT_CUSTOM_URL = os.getenv("BOORU_DICT_CUSTOM_URL", "").strip()
BOORU_DICT_SOURCE_KIND = os.getenv("BOORU_DICT_SOURCE_KIND", "hf").strip()
BOORU_DICT_GIT_URL = os.getenv("BOORU_DICT_GIT_URL", "").strip()
BOORU_DICT_GIT_REF = os.getenv("BOORU_DICT_GIT_REF", "main").strip()
BOORU_DICT_GIT_FILE = os.getenv("BOORU_DICT_GIT_FILE", "danbooru_tags.csv").strip()
BOORU_DICT_LOCAL_FILE_RAW = os.getenv("BOORU_DICT_LOCAL_FILE", "").strip()
BOORU_DICT_LOCAL_FILE = _expand_path(BOORU_DICT_LOCAL_FILE_RAW) if BOORU_DICT_LOCAL_FILE_RAW else ""
BOORU_TAG_SHOW_MANUAL = _to_bool(os.getenv("BOORU_TAG_SHOW_MANUAL", "true"), True)
BOORU_TAG_SHOW_AUTO = _to_bool(os.getenv("BOORU_TAG_SHOW_AUTO", "true"), True)
BOORU_TAG_SHOW_WD = _to_bool(os.getenv("BOORU_TAG_SHOW_WD", "true"), True)

# WD14 auto tagger
WD14_MODEL_PATH_RAW = os.getenv("WD14_MODEL_PATH", "").strip()
WD14_MODEL_PATH = _expand_path(WD14_MODEL_PATH_RAW) if WD14_MODEL_PATH_RAW else ""
WD14_TAGS_CSV_RAW = os.getenv("WD14_TAGS_CSV", "").strip()
WD14_TAGS_CSV = _expand_path(WD14_TAGS_CSV_RAW) if WD14_TAGS_CSV_RAW else ""
WD14_AUTO_TAG_ON_REFRESH = _to_bool(os.getenv("WD14_AUTO_TAG_ON_REFRESH", "true"), True)
WD14_PROVIDER_MODE = os.getenv("WD14_PROVIDER_MODE", "gpu_first").strip().lower()
WD14_PROVIDER_LIST = os.getenv("WD14_PROVIDER_LIST", "").strip()
WD14_THRESHOLD_GENERAL = _to_float(os.getenv("WD14_THRESHOLD_GENERAL", "0.35"), 0.35)
WD14_THRESHOLD_ARTIST = _to_float(os.getenv("WD14_THRESHOLD_ARTIST", "0.35"), 0.35)
WD14_THRESHOLD_COPYRIGHT = _to_float(os.getenv("WD14_THRESHOLD_COPYRIGHT", "0.35"), 0.35)
WD14_THRESHOLD_CHARACTER = _to_float(os.getenv("WD14_THRESHOLD_CHARACTER", "0.85"), 0.85)
WD14_THRESHOLD_META = _to_float(os.getenv("WD14_THRESHOLD_META", "0.35"), 0.35)
WD14_THRESHOLD_RATING = _to_float(os.getenv("WD14_THRESHOLD_RATING", "0.0"), 0.0)

if DEBUG_MODE:
    # Verbose diagnostics for local development only.
    print(f"[settings] DEBUG_MODE: on")
    print(f"[settings] PROJECT_ROOT: {PROJECT_ROOT.as_posix()}")
    print(f"[settings] SOURCE(raw): {SOURCE_RAW or '(not set)'}  ->  {SOURCE or '(not set)'}")
    print(f"[settings] DEST(raw):   {DEST_RAW or '(ignored in lite)'}  ->  {DEST or '(not set)'}")
    print(f"[settings] DB_PATH:     {DB_PATH}")
    print(f"[settings] DB_BACKUP_DIR: {DB_BACKUP_DIR or '(disabled)'}  MAX_DB_BACKUPS: {MAX_DB_BACKUPS}")
    print(f"[settings] TEMPLATE_FOLDER: {TEMPLATE_FOLDER}")
    print(f"[settings] STATIC_FOLDER:   {STATIC_FOLDER}")
    print(
        f"[settings] INDEX_DIR: {INDEX_DIR}  "
        f"FFMPEG_PATH: {FFMPEG_PATH or '(not set)'}  "
        f"FFPROBE_PATH: {FFPROBE_PATH or '(not set)'}  "
        f"FFPLAY_PATH: {FFPLAY_PATH or '(not set)'}  "
        f"EXIFTOOL_PATH: {EXIFTOOL_PATH or '(not set)'}  "
        f"PORT: {PORT}"
    )
    print(f"[settings] ALLOWED_IPS: {ALLOWED_IPS}")
    print(
        "[settings] INTEGRITY_MISSING_SAMPLES_LIMIT: "
        f"{INTEGRITY_MISSING_SAMPLES_LIMIT}  "
        "INTEGRITY_DIAGNOSTICS_LIMIT: "
        f"{INTEGRITY_DIAGNOSTICS_LIMIT}"
    )
    print(f"[settings] SECRET_KEY set: {'yes' if SECRET_KEY else 'no'}")
else:
    print("[settings] DEBUG_MODE: off (verbose settings logs hidden)")

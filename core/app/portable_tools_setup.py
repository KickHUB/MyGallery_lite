from __future__ import annotations

import json
import os
import re
import shutil
import sys
import tempfile
import zipfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin
from urllib.request import Request, urlopen

if os.name == "nt":
    import msvcrt
else:  # pragma: no cover - non-Windows fallback
    msvcrt = None

USER_AGENT = "MyGalleryPortableSetup/1.0"
STATE_FILE_NAME = "portable_setup_state.json"

FFMPEG_BUNDLE_URL = "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip"
BOORU_TAG_DB_URL = (
    "https://huggingface.co/datasets/newtextdoc1111/danbooru-tag-csv/"
    "resolve/main/danbooru_tags.csv"
)

WD14_MODELS: Dict[str, Dict[str, str]] = {
    "wd-eva02-large-tagger-v3": {
        "repo": "SmilingWolf/wd-eva02-large-tagger-v3",
        "onnx": "https://huggingface.co/SmilingWolf/wd-eva02-large-tagger-v3/resolve/main/model.onnx",
        "tags": "https://huggingface.co/SmilingWolf/wd-eva02-large-tagger-v3/resolve/main/selected_tags.csv",
    },
    "wd-swinv2-tagger-v3": {
        "repo": "SmilingWolf/wd-swinv2-tagger-v3",
        "onnx": "https://huggingface.co/SmilingWolf/wd-swinv2-tagger-v3/resolve/main/model.onnx",
        "tags": "https://huggingface.co/SmilingWolf/wd-swinv2-tagger-v3/resolve/main/selected_tags.csv",
    },
}

DEFAULT_SIZE_BYTES = {
    "ffmpeg": 95 * 1024 * 1024,
    "exiftool": 14 * 1024 * 1024,
    "wd-eva02-large-tagger-v3": 220 * 1024 * 1024,
    "wd-swinv2-tagger-v3": 130 * 1024 * 1024,
    "booru-db": 2 * 1024 * 1024,
}


@dataclass
class PromptItem:
    key: str
    title: str
    detail: str
    size_bytes: Optional[int]
    fallback_size_bytes: int


def _clear_console() -> None:
    os.system("cls" if os.name == "nt" else "clear")


def _human_size(size: int) -> str:
    value = float(size)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if value < 1024 or unit == "TB":
            if unit == "B":
                return f"{int(value)} {unit}"
            return f"{value:.1f} {unit}"
        value /= 1024.0
    return f"{size} B"


def _size_label(size_bytes: Optional[int], fallback_size_bytes: int) -> str:
    if size_bytes is None or size_bytes <= 0:
        return f"~{_human_size(fallback_size_bytes)}"
    return _human_size(size_bytes)


def _http_open(url: str, *, method: str = "GET", timeout: int = 60, headers: Optional[Dict[str, str]] = None):
    req_headers = {
        "User-Agent": USER_AGENT,
        "Accept": "*/*",
    }
    if headers:
        req_headers.update(headers)
    req = Request(url, headers=req_headers, method=method)
    return urlopen(req, timeout=timeout)


def _parse_content_length_from_headers(headers) -> Optional[int]:
    raw = headers.get("Content-Length")
    if raw and str(raw).isdigit():
        return int(raw)
    content_range = headers.get("Content-Range", "")
    match = re.search(r"/(\d+)$", str(content_range))
    if match:
        return int(match.group(1))
    return None


def _fetch_content_length(url: str, timeout: int = 20) -> Optional[int]:
    try:
        with _http_open(url, method="HEAD", timeout=timeout) as response:
            size = _parse_content_length_from_headers(response.headers)
            if size:
                return size
    except Exception:
        pass

    try:
        with _http_open(
            url,
            method="GET",
            timeout=timeout,
            headers={"Range": "bytes=0-0"},
        ) as response:
            return _parse_content_length_from_headers(response.headers)
    except Exception:
        return None


def _fetch_text(url: str, timeout: int = 30) -> str:
    with _http_open(url, method="GET", timeout=timeout) as response:
        raw = response.read()
    return raw.decode("utf-8", errors="replace")


def _resolve_exiftool_zip_url() -> Optional[str]:
    base = "https://exiftool.org/"
    try:
        page = _fetch_text(base)
    except Exception:
        return None

    def _version_key(url: str) -> tuple[int, ...]:
        match = re.search(r"exiftool-([0-9]+(?:\.[0-9]+)*)_64\.zip", url, flags=re.IGNORECASE)
        if not match:
            return (0,)
        parts = []
        for token in match.group(1).split("."):
            try:
                parts.append(int(token))
            except ValueError:
                parts.append(0)
        return tuple(parts) if parts else (0,)

    candidates: list[str] = []

    # 1) Prefer explicit href targets.
    hrefs = re.findall(r'href=["\']([^"\']+)["\']', page, flags=re.IGNORECASE)
    for href in hrefs:
        if re.search(r"exiftool-[0-9][0-9A-Za-z._-]*_64\.zip(?:/download)?$", href, flags=re.IGNORECASE):
            candidates.append(urljoin(base, href))

    # 2) Fallback: extract plain-text mentions if site markup changes.
    if not candidates:
        text_hits = re.findall(
            r"(https?://[^\s\"']*exiftool-[0-9][0-9A-Za-z._-]*_64\.zip(?:/download)?)",
            page,
            flags=re.IGNORECASE,
        )
        for hit in text_hits:
            candidates.append(hit)
        rel_hits = re.findall(
            r"(exiftool/files/exiftool-[0-9][0-9A-Za-z._-]*_64\.zip)",
            page,
            flags=re.IGNORECASE,
        )
        for hit in rel_hits:
            candidates.append(urljoin(base, hit))

    if not candidates:
        return None

    # Return latest version when multiple links exist.
    candidates = sorted(set(candidates), key=_version_key, reverse=True)
    return candidates[0]


def _read_key() -> str:
    if os.name != "nt" or msvcrt is None:
        return input().strip()

    ch = msvcrt.getwch()
    if ch in ("\x00", "\xe0"):
        extra = msvcrt.getwch()
        if extra == "K":
            return "LEFT"
        if extra == "M":
            return "RIGHT"
        if extra == "H":
            return "UP"
        if extra == "P":
            return "DOWN"
        return "SPECIAL"
    if ch in ("\r", "\n"):
        return "ENTER"
    if ch == "\x1b":
        return "ESC"
    return ch


def _prompt_yes_no(item: PromptItem, default_yes: bool = True) -> bool:
    if not (sys.stdin.isatty() and sys.stdout.isatty()):
        return default_yes

    size_text = _size_label(item.size_bytes, item.fallback_size_bytes)

    if os.name != "nt" or msvcrt is None:  # pragma: no cover - fallback
        raw = input(f"{item.title} ({size_text}) [Y/n]: ").strip().lower()
        if not raw:
            return default_yes
        return raw in {"y", "yes", "1", "true"}

    selected = 0 if default_yes else 1
    while True:
        _clear_console()
        print("MyGallery Portable Dependency Setup")
        print("=" * 42)
        print(f"\n{item.title}")
        print(item.detail)
        print(f"Estimated download size: {size_text}\n")
        print("Use arrow keys (LEFT/RIGHT), then press ENTER.")
        yes_text = "[ YES ]" if selected == 0 else "  YES  "
        no_text = "[ NO ]" if selected == 1 else "  NO   "
        print(f"\n{yes_text}    {no_text}\n")

        key = _read_key()
        if key in {"LEFT", "UP"}:
            selected = 0
        elif key in {"RIGHT", "DOWN"}:
            selected = 1
        elif key == "ENTER":
            return selected == 0
        elif key in {"y", "Y"}:
            return True
        elif key in {"n", "N"}:
            return False
        elif key == "ESC":
            return False


def _prompt_select(title: str, detail: str, options: Sequence[Tuple[str, str]], default_index: int = 0) -> int:
    if not (sys.stdin.isatty() and sys.stdout.isatty()):
        return default_index

    if os.name != "nt" or msvcrt is None:  # pragma: no cover
        print(title)
        print(detail)
        for idx, (label, _) in enumerate(options, start=1):
            print(f"{idx}. {label}")
        raw = input("Select number: ").strip()
        if raw.isdigit():
            value = int(raw) - 1
            if 0 <= value < len(options):
                return value
        return default_index

    selected = max(0, min(default_index, len(options) - 1))
    while True:
        _clear_console()
        print("MyGallery Portable Dependency Setup")
        print("=" * 42)
        print(f"\n{title}")
        print(detail)
        print("\nUse arrow keys (UP/DOWN), then press ENTER.\n")
        for idx, (label, sub) in enumerate(options):
            prefix = ">>" if idx == selected else "  "
            print(f"{prefix} {label}")
            if sub:
                print(f"   {sub}")
        print("")

        key = _read_key()
        if key in {"UP", "LEFT"}:
            selected = (selected - 1) % len(options)
        elif key in {"DOWN", "RIGHT"}:
            selected = (selected + 1) % len(options)
        elif key == "ENTER":
            return selected
        elif key == "ESC":
            return default_index


def _download_file(url: str, destination: Path, label: str) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    print(f"[DOWNLOAD] {label}")
    print(f"           {url}")
    with _http_open(url, method="GET", timeout=120) as response, destination.open("wb") as handle:
        total = _parse_content_length_from_headers(response.headers) or 0
        downloaded = 0
        while True:
            chunk = response.read(1024 * 1024)
            if not chunk:
                break
            handle.write(chunk)
            downloaded += len(chunk)
            if total > 0:
                pct = (downloaded / total) * 100
                print(f"\r           {pct:5.1f}% ({_human_size(downloaded)}/{_human_size(total)})", end="", flush=True)
            else:
                print(f"\r           {_human_size(downloaded)}", end="", flush=True)
    print("")


def _find_first(root: Path, filename: str) -> Optional[Path]:
    for path in root.rglob(filename):
        if path.is_file():
            return path
    return None


def _to_repo_relative(path: Path, repo_root: Path) -> str:
    try:
        return path.resolve().relative_to(repo_root.resolve()).as_posix()
    except Exception:
        return path.resolve().as_posix()


def _install_ffmpeg_bundle(repo_root: Path, tools_root: Path, want_ffmpeg: bool, want_ffprobe: bool) -> Dict[str, str]:
    env_updates: Dict[str, str] = {}
    with tempfile.TemporaryDirectory(prefix="mygallery_ffmpeg_") as temp_dir:
        temp_path = Path(temp_dir)
        zip_path = temp_path / "ffmpeg.zip"
        extract_dir = temp_path / "extract"
        _download_file(FFMPEG_BUNDLE_URL, zip_path, "FFmpeg bundle")
        with zipfile.ZipFile(zip_path, "r") as archive:
            archive.extractall(extract_dir)

        ffmpeg_exe = _find_first(extract_dir, "ffmpeg.exe")
        if not ffmpeg_exe:
            raise RuntimeError("Unable to find ffmpeg.exe in downloaded archive.")
        source_bin = ffmpeg_exe.parent

        target_root = tools_root / "ffmpeg"
        target_bin = target_root / "bin"
        if target_root.exists():
            shutil.rmtree(target_root, ignore_errors=True)
        target_bin.mkdir(parents=True, exist_ok=True)

        copied: Dict[str, Path] = {}
        for exe_name in ("ffmpeg.exe", "ffprobe.exe", "ffplay.exe"):
            src = source_bin / exe_name
            if src.is_file():
                dst = target_bin / exe_name
                shutil.copy2(src, dst)
                copied[exe_name] = dst

        if want_ffmpeg and "ffmpeg.exe" in copied:
            env_updates["FFMPEG_PATH"] = _to_repo_relative(copied["ffmpeg.exe"], repo_root)
        if want_ffprobe and "ffprobe.exe" in copied:
            env_updates["FFPROBE_PATH"] = _to_repo_relative(copied["ffprobe.exe"], repo_root)
        if (want_ffmpeg or want_ffprobe) and "ffplay.exe" in copied:
            env_updates["FFPLAY_PATH"] = _to_repo_relative(copied["ffplay.exe"], repo_root)

    return env_updates


def _install_exiftool(repo_root: Path, tools_root: Path, exiftool_zip_url: str) -> Dict[str, str]:
    with tempfile.TemporaryDirectory(prefix="mygallery_exiftool_") as temp_dir:
        temp_path = Path(temp_dir)
        zip_path = temp_path / "exiftool.zip"
        extract_dir = temp_path / "extract"
        _download_file(exiftool_zip_url, zip_path, "ExifTool")
        with zipfile.ZipFile(zip_path, "r") as archive:
            archive.extractall(extract_dir)

        exe_candidates = sorted(
            [p for p in extract_dir.rglob("*.exe") if p.name.lower().startswith("exiftool")]
        )
        if not exe_candidates:
            raise RuntimeError("Unable to find exiftool executable in downloaded archive.")

        preferred = None
        for candidate in exe_candidates:
            if candidate.name.lower() == "exiftool.exe":
                preferred = candidate
                break
        if preferred is None:
            preferred = exe_candidates[0]

        target_root = tools_root / "exiftool"
        if target_root.exists():
            shutil.rmtree(target_root, ignore_errors=True)
        target_root.mkdir(parents=True, exist_ok=True)

        target_exe = target_root / "exiftool.exe"
        shutil.copy2(preferred, target_exe)

        source_files_dir = preferred.parent / "exiftool_files"
        if source_files_dir.is_dir():
            shutil.copytree(source_files_dir, target_root / "exiftool_files", dirs_exist_ok=True)

    return {"EXIFTOOL_PATH": _to_repo_relative(target_exe, repo_root)}


def _install_wd14_model(repo_root: Path, tools_root: Path, model_key: str) -> Dict[str, str]:
    model_cfg = WD14_MODELS[model_key]
    model_dir = tools_root / "wd14" / model_key
    model_dir.mkdir(parents=True, exist_ok=True)

    model_path = model_dir / "model.onnx"
    tags_path = model_dir / "selected_tags.csv"
    _download_file(model_cfg["onnx"], model_path, f"WD14 model ({model_cfg['repo']})")
    _download_file(model_cfg["tags"], tags_path, f"WD14 tags ({model_cfg['repo']})")

    return {
        "WD14_MODEL_PATH": _to_repo_relative(model_path, repo_root),
        "WD14_TAGS_CSV": _to_repo_relative(tags_path, repo_root),
    }


def _install_booru_db(repo_root: Path, tools_root: Path) -> Dict[str, str]:
    booru_dir = tools_root / "booru"
    booru_dir.mkdir(parents=True, exist_ok=True)
    booru_file = booru_dir / "danbooru_tags.csv"
    _download_file(BOORU_TAG_DB_URL, booru_file, "Danbooru tag DB")
    return {
        "BOORU_DICT_SOURCE_KIND": "local",
        "BOORU_DICT_LOCAL_FILE": _to_repo_relative(booru_file, repo_root),
    }


def _upsert_env_file(env_path: Path, updates: Dict[str, str]) -> None:
    lines: List[str] = []
    if env_path.exists():
        lines = env_path.read_text(encoding="utf-8").splitlines()

    updated_keys: set[str] = set()
    output: List[str] = []
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in line:
            output.append(line)
            continue
        key = stripped.split("=", 1)[0].strip()
        if key in updates:
            output.append(f"{key}={updates[key]}")
            updated_keys.add(key)
        else:
            output.append(line)

    for key, value in updates.items():
        if key in updated_keys:
            continue
        if output and output[-1].strip() != "":
            output.append("")
        output.append(f"{key}={value}")

    env_path.parent.mkdir(parents=True, exist_ok=True)
    env_path.write_text("\n".join(output).rstrip() + "\n", encoding="utf-8")


def _apply_system_fallbacks(env_updates: Dict[str, str]) -> Dict[str, str]:
    discovered: Dict[str, str] = {}

    if "FFMPEG_PATH" not in env_updates:
        ffmpeg_system = shutil.which("ffmpeg")
        if ffmpeg_system:
            value = Path(ffmpeg_system).as_posix()
            env_updates.setdefault("FFMPEG_PATH", value)
            discovered["FFMPEG_PATH"] = value

    if "FFPROBE_PATH" not in env_updates:
        ffprobe_system = shutil.which("ffprobe")
        if ffprobe_system:
            value = Path(ffprobe_system).as_posix()
            env_updates.setdefault("FFPROBE_PATH", value)
            discovered["FFPROBE_PATH"] = value

    if "EXIFTOOL_PATH" not in env_updates:
        exiftool_system = shutil.which("exiftool")
        if exiftool_system:
            value = Path(exiftool_system).as_posix()
            env_updates.setdefault("EXIFTOOL_PATH", value)
            discovered["EXIFTOOL_PATH"] = value

    return discovered


def _write_state_file(state_path: Path, payload: Dict[str, object]) -> None:
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def run_portable_tools_setup(repo_root: Path, force: bool = False) -> Dict[str, object]:
    repo_root = Path(repo_root).resolve()
    tools_root = repo_root / "tools"
    tools_root.mkdir(parents=True, exist_ok=True)
    state_path = tools_root / STATE_FILE_NAME
    env_path = repo_root / ".env"

    if state_path.exists() and not force:
        return {"status": "skipped", "reason": "already_configured", "state_path": state_path.as_posix()}

    exiftool_zip_url = _resolve_exiftool_zip_url()
    ffmpeg_size = _fetch_content_length(FFMPEG_BUNDLE_URL)
    exiftool_size = _fetch_content_length(exiftool_zip_url) if exiftool_zip_url else None
    booru_size = _fetch_content_length(BOORU_TAG_DB_URL)

    wd_sizes: Dict[str, Optional[int]] = {}
    for model_key, model_cfg in WD14_MODELS.items():
        model_size = _fetch_content_length(model_cfg["onnx"])
        tags_size = _fetch_content_length(model_cfg["tags"])
        if model_size is None and tags_size is None:
            wd_sizes[model_key] = None
        else:
            wd_sizes[model_key] = (model_size or 0) + (tags_size or 0)

    prompt_items = [
        PromptItem(
            key="ffmpeg",
            title="Install FFmpeg into ./tools ?",
            detail="Required for video metadata stripping and thumbnail generation.",
            size_bytes=ffmpeg_size,
            fallback_size_bytes=DEFAULT_SIZE_BYTES["ffmpeg"],
        ),
        PromptItem(
            key="ffprobe",
            title="Install FFprobe into ./tools ?",
            detail="Required for video metadata read and audio-stream detection.",
            size_bytes=ffmpeg_size,
            fallback_size_bytes=DEFAULT_SIZE_BYTES["ffmpeg"],
        ),
        PromptItem(
            key="exiftool",
            title="Install ExifTool into ./tools ?",
            detail="Required for image EXIF read/remove workflows.",
            size_bytes=exiftool_size,
            fallback_size_bytes=DEFAULT_SIZE_BYTES["exiftool"],
        ),
        PromptItem(
            key="wd14",
            title="Install WD14 model into ./tools ?",
            detail="Required for automatic WD14 tagging.",
            size_bytes=None,
            fallback_size_bytes=max(
                DEFAULT_SIZE_BYTES["wd-eva02-large-tagger-v3"],
                DEFAULT_SIZE_BYTES["wd-swinv2-tagger-v3"],
            ),
        ),
        PromptItem(
            key="booru",
            title="Install Danbooru tag DB into ./tools ?",
            detail="Installs a local copy of danbooru_tags.csv.",
            size_bytes=booru_size,
            fallback_size_bytes=DEFAULT_SIZE_BYTES["booru-db"],
        ),
    ]

    answers: Dict[str, bool] = {}
    for item in prompt_items:
        answers[item.key] = _prompt_yes_no(item, default_yes=True)

    selected_wd14_model = ""
    if answers.get("wd14"):
        options: List[Tuple[str, str]] = []
        for model_key, model_cfg in WD14_MODELS.items():
            size_text = _size_label(
                wd_sizes.get(model_key),
                DEFAULT_SIZE_BYTES.get(model_key, 150 * 1024 * 1024),
            )
            options.append((f"{model_key} ({size_text})", model_cfg["repo"]))
        chosen = _prompt_select(
            title="Select WD14 model",
            detail="Pick one WD14 model to download.",
            options=options,
            default_index=0,
        )
        selected_wd14_model = list(WD14_MODELS.keys())[chosen]

    _clear_console()
    print("MyGallery Portable Dependency Setup")
    print("=" * 42)
    print("\nApplying selected installs...\n")

    env_updates: Dict[str, str] = {}
    errors: List[str] = []
    installed: List[str] = []

    if answers.get("ffmpeg") or answers.get("ffprobe"):
        try:
            ff_updates = _install_ffmpeg_bundle(
                repo_root=repo_root,
                tools_root=tools_root,
                want_ffmpeg=answers.get("ffmpeg", False),
                want_ffprobe=answers.get("ffprobe", False),
            )
            env_updates.update(ff_updates)
            installed.append("ffmpeg-bundle")
        except Exception as exc:  # pragma: no cover - runtime dependent
            errors.append(f"FFmpeg/FFprobe install failed: {exc}")

    if answers.get("exiftool"):
        if not exiftool_zip_url:
            errors.append("ExifTool install failed: unable to resolve official download URL.")
        else:
            try:
                exif_updates = _install_exiftool(
                    repo_root=repo_root,
                    tools_root=tools_root,
                    exiftool_zip_url=exiftool_zip_url,
                )
                env_updates.update(exif_updates)
                installed.append("exiftool")
            except Exception as exc:  # pragma: no cover
                errors.append(f"ExifTool install failed: {exc}")

    if answers.get("wd14"):
        try:
            wd_updates = _install_wd14_model(
                repo_root=repo_root,
                tools_root=tools_root,
                model_key=selected_wd14_model,
            )
            env_updates.update(wd_updates)
            installed.append(f"wd14:{selected_wd14_model}")
        except Exception as exc:  # pragma: no cover
            errors.append(f"WD14 install failed: {exc}")

    if answers.get("booru"):
        try:
            booru_updates = _install_booru_db(repo_root=repo_root, tools_root=tools_root)
            env_updates.update(booru_updates)
            installed.append("booru-db")
        except Exception as exc:  # pragma: no cover
            errors.append(f"Booru DB install failed: {exc}")

    discovered_from_path = _apply_system_fallbacks(env_updates=env_updates)

    if env_updates:
        _upsert_env_file(env_path=env_path, updates=env_updates)

    payload = {
        "completed_at": datetime.now().isoformat(timespec="seconds"),
        "answers": answers,
        "selected_wd14_model": selected_wd14_model,
        "installed": installed,
        "env_updates": env_updates,
        "path_discovered": discovered_from_path,
        "errors": errors,
    }
    _write_state_file(state_path, payload)

    print("[DONE] Portable setup finished.")
    if installed:
        print(f"       Installed: {', '.join(installed)}")
    if env_updates:
        print("       Updated .env keys:")
        for key in sorted(env_updates.keys()):
            print(f"         - {key}")
    if discovered_from_path:
        print("       Found from system PATH:")
        for key, value in discovered_from_path.items():
            print(f"         - {key}: {value}")
    if errors:
        print("       Errors:")
        for err in errors:
            print(f"         - {err}")

    return payload

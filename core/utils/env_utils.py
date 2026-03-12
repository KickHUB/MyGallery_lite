from __future__ import annotations

import os
import shutil
from datetime import datetime
from pathlib import Path


def _default_backup_dir(env_path: str | Path) -> Path:
    env_path = Path(env_path)
    return env_path.resolve().parent / "data" / "env_backups"


def backup_env_file(env_path: str | Path, backup_dir: str | Path) -> Path | None:
    env_path = Path(env_path)
    if not env_path.exists():
        return None
    backup_dir = Path(backup_dir)
    backup_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = backup_dir / f"{env_path.name}.{timestamp}.bak"
    shutil.copyfile(env_path, backup_path)
    return backup_path


def atomic_write_text(path: str | Path, text: str) -> None:
    path = Path(path)
    tmp_path = path.with_suffix(".tmp")
    tmp_path.write_text(text, encoding="utf-8")
    os.replace(tmp_path, path)


def parse_env_text(text: str) -> dict[str, str]:
    data: dict[str, str] = {}
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
        if not key:
            raise ValueError(f"Invalid env line at {idx}: {line}")
        data[key] = value
    return data


def render_env_dict(env_dict: dict[str, str], preserve_order: bool = True) -> str:
    items = env_dict.items() if preserve_order else sorted(env_dict.items())
    return "\n".join(f"{key}={value}" for key, value in items) + "\n"


def write_env_text(text: str, env_path: str = ".env") -> None:
    env_path = Path(env_path)
    backup_env_file(env_path, _default_backup_dir(env_path))
    if text and not text.endswith("\n"):
        text = f"{text}\n"
    atomic_write_text(env_path, text)


def update_env_vars(updates: dict, env_path: str = ".env") -> None:
    """키=값으로 .env 갱신(있으면 치환, 없으면 추가). UTF-8."""
    p = Path(env_path)
    lines = p.read_text(encoding="utf-8").splitlines() if p.exists() else []
    kv = {k: str(v) for k, v in (updates or {}).items() if v is not None}
    out, seen = [], set()
    for line in lines:
        if "=" in line and not line.strip().startswith("#"):
            k = line.split("=", 1)[0].strip()
            if k in kv:
                out.append(f"{k}={kv[k]}")
                seen.add(k)
            else:
                out.append(line)
        else:
            out.append(line)
    for k, v in kv.items():
        if k not in seen:
            out.append(f"{k}={v}")
    backup_env_file(p, _default_backup_dir(p))
    atomic_write_text(p, "\n".join(out) + "\n")

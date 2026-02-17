from __future__ import annotations

import time
from pathlib import Path


def get_static_build_id(static_folder: str, filename: str) -> str:
    target = Path(static_folder) / filename
    try:
        return str(int(target.stat().st_mtime))
    except FileNotFoundError:
        return str(int(time.time()))
    except OSError:
        return str(int(time.time()))

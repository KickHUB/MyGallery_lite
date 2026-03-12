from __future__ import annotations

import mimetypes
import os
from pathlib import Path
from typing import Dict, List

from flask import Blueprint, render_template, send_file

from settings import DEST

bp = Blueprint("quarantine", __name__)
IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".webp")


def _is_supported_image(filename: str) -> bool:
    lower = filename.lower()
    return any(lower.endswith(ext) for ext in IMAGE_EXTS)


def _collect_quarantine_images() -> Dict[str, List[dict]]:
    root = Path(DEST) / "quarantine"
    grouped: Dict[str, List[dict]] = {}
    if not root.is_dir():
        return grouped

    for current_root, _, filenames in os.walk(root):
        rel_root = Path(current_root).relative_to(root)
        group_key = rel_root.parts[0] if rel_root.parts else "기타"
        for filename in filenames:
            if not _is_supported_image(filename):
                continue
            file_path = Path(current_root) / filename
            rel_path = file_path.relative_to(root).as_posix()
            grouped.setdefault(group_key, []).append({
                "rel_path": rel_path,
                "label": rel_path,
                "filename": filename,
            })

    for key in grouped:
        grouped[key] = sorted(grouped[key], key=lambda x: x["label"].lower())
    return dict(sorted(grouped.items(), key=lambda x: x[0].lower()))


@bp.get("/quarantine")
def quarantine_page():
    grouped = _collect_quarantine_images()
    return render_template("quarantine.html", grouped=grouped)


@bp.get("/quarantine_img/<path:filename>")
def quarantine_img(filename: str):
    root = Path(DEST) / "quarantine"
    target = (root / filename).resolve()
    try:
        target.relative_to(root.resolve())
    except Exception:
        return ("❌ 파일 없음", 404)
    if target.is_file():
        mimetype, _ = mimetypes.guess_type(target.as_posix())
        return send_file(target.as_posix(), mimetype=mimetype)
    return ("❌ 파일 없음", 404)

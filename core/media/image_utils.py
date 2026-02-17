import os
import shutil
from datetime import datetime
from pathlib import Path
from typing import List

from core.media.gallery_layout import get_media_root


def _is_video_meta_png(name: str) -> bool:
    n = name.lower()
    return n.endswith(".png") and n.startswith("video")


def organize_pngs(
    source_folder: str,
    destination_root: str,
    *,
    rename: bool = True,
    skip_video_meta: bool = True,
) -> List[str]:
    """Move PNG files from *source_folder* into date-based folders under *destination_root*.

    New layout (preferred):
        DEST/<DEST_CONTENT_SUBDIR>/YYYY-MM-DD/{images,drafts}/...

    Legacy layout (still supported):
        DEST/YYYY-MM-DD/...  (and old Drafts/YYYY-MM-DD)

    If *rename* is True, files are renamed to ``YYYYMMDD_HHMMSS.png`` based on creation time.
    When *skip_video_meta* is True, files matching ``video*.png`` are ignored.

    Returns a list of destination paths for successfully moved files.
    """

    moved: List[str] = []
    src = Path(source_folder)
    dest_root = Path(destination_root)
    if not src.is_dir():
        return moved

    for entry in src.iterdir():
        if not entry.is_file() or entry.suffix.lower() != ".png":
            continue
        if skip_video_meta and _is_video_meta_png(entry.name):
            continue

        is_draft = "draft" in entry.stem.lower()

        try:
            ctime = os.path.getctime(entry)
            dt = datetime.fromtimestamp(ctime)
            date_str = dt.strftime("%Y-%m-%d")

            kind = "drafts" if is_draft else "images"
            date_dir = get_media_root(dest_root, date_str, kind, create=True)

            if rename:
                ts = dt.strftime("%Y%m%d_%H%M%S")
                target = date_dir / f"{ts}.png"
            else:
                target = date_dir / entry.name

            if target.exists():
                print(f"⚠️ 중복으로 건너뜀: {target.name}")
                continue

            shutil.move(str(entry), str(target))
            moved.append(str(target))
            print(f"✅ PNG 이동: {entry.name} → {target}")
        except Exception as e:
            print(f"⚠️ PNG 이동 실패({entry.name}): {e}")

    return moved

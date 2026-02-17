import os
from urllib.parse import unquote
from settings import DEST, DEST_FOLDER_NAME, DRAFTS_FOLDER_NAME


def resolve_dest_path(rel_path: str) -> str | None:
    """Return absolute path within DEST for given relative path.

    The path is normalized and validated to ensure it resides inside the DEST
    directory. If the resulting path is outside DEST or the input is empty,
    None is returned.
    """
    if not rel_path:
        return None

    rel_path = unquote(rel_path).replace("\\", "/")
    prefixes = [p for p in ("Sorted_by_Date/", f"{DEST_FOLDER_NAME}/") if p]
    draft_prefix = f"{DRAFTS_FOLDER_NAME}/" if DRAFTS_FOLDER_NAME else ""
    for prefix in prefixes:
        if rel_path.startswith(prefix):
            rel_path = rel_path[len(prefix):]
    while draft_prefix and rel_path.startswith(f"{draft_prefix}{draft_prefix}"):
        rel_path = rel_path[len(draft_prefix):]
    dest_root = os.path.abspath(DEST)
    abs_path = os.path.abspath(os.path.normpath(os.path.join(dest_root, rel_path)))

    try:
        if os.path.commonpath([abs_path, dest_root]) != dest_root:
            return None
    except ValueError:
        return None

    return abs_path

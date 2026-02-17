from __future__ import annotations
import os, json, datetime, math
from pathlib import Path
from typing import Dict, Optional, Tuple
from flask import Blueprint, render_template, request, jsonify, send_file
from settings import DEST, DEST_FOLDER_NAME
from core.media.gallery_layout import get_media_root
from core.tagging.tag_utils import extract_prompt_from_png, extract_prompt_from_file
from core.db.search_utils import save_tags_to_db, remove_image_from_db
from core.media.thumbs import (
    normalize_thumb_rel_path,
    build_thumb_cache_path,
    thumb_cache_is_fresh,
    build_thumb_fallback_candidates,
    generate_thumbnail,
)
from core.media.video_index import VIDEO_EXTS, remove_video_from_db, upsert_video

bp = Blueprint("trash", __name__)

try:
    _DEST_PATH: Optional[Path] = Path(DEST).resolve()
except Exception:
    _DEST_PATH = None

def _get_dest_root() -> Optional[Path]:
    global _DEST_PATH
    if _DEST_PATH and _DEST_PATH.exists():
        return _DEST_PATH
    if not DEST:
        return None
    try:
        _DEST_PATH = Path(DEST).resolve()
    except Exception:
        _DEST_PATH = None
    return _DEST_PATH

def _strip_known_prefixes(rel: str) -> str:
    prefixes = tuple(p for p in ("Sorted_by_Date/", f"{DEST_FOLDER_NAME}/") if p)
    changed = True
    while changed:
        changed = False
        for prefix in prefixes:
            if rel.startswith(prefix):
                rel = rel[len(prefix):]
                changed = True
    return rel

def _resolve_rel_path(rel_path: str) -> Optional[Path]:
    root = _get_dest_root()
    if not root:
        return None
    rel_clean = _strip_known_prefixes(rel_path.replace("\\", "/").lstrip("/"))
    candidate = (root / rel_clean).resolve()
    try:
        candidate.relative_to(root)
    except Exception:
        return None
    return candidate

def _get_trash_dir() -> Optional[Path]:
    root = _get_dest_root()
    if not root:
        return None
    trash_dir = root / "Trash"
    try:
        trash_dir.mkdir(parents=True, exist_ok=True)
    except Exception:
        return None
    return trash_dir

def _load_trash_log() -> Dict[str, str]:
    trash_dir = _get_trash_dir()
    if not trash_dir:
        return {}
    log_path = trash_dir / "trash_log.json"
    if not log_path.exists():
        return {}
    try:
        with log_path.open("r", encoding="utf-8") as fh:
            data = json.load(fh)
            if isinstance(data, dict):
                return data
    except Exception:
        pass
    return {}

def _save_trash_log(log: Dict[str, str]) -> None:
    trash_dir = _get_trash_dir()
    if not trash_dir:
        return
    log_path = trash_dir / "trash_log.json"
    try:
        with log_path.open("w", encoding="utf-8") as fh:
            json.dump(log, fh, ensure_ascii=False, indent=2)
    except Exception:
        pass

def _move_file_to_trash(path: Path) -> Path:
    trash_dir = _get_trash_dir()
    if not trash_dir:
        raise RuntimeError("휴지통 경로를 찾을 수 없습니다.")
    target = trash_dir / path.name
    base_name = path.stem
    suffix = path.suffix
    counter = 1
    while target.exists():
        target = trash_dir / f"{base_name}_{counter}{suffix}"
        counter += 1
    path.rename(target)
    return target

def _delete_single_media(rel_path: str, log: Dict[str, str]) -> Tuple[bool, Optional[str], int]:
    rel_value = (rel_path or "").strip()
    if not rel_value:
        return False, "경로 없음", 400
    target = _resolve_rel_path(rel_value)
    if not target or not target.exists():
        return False, "파일 없음", 404
    if target.is_dir():
        return False, "폴더는 삭제할 수 없습니다.", 400

    ext = target.suffix.lower()
    is_video = ext in VIDEO_EXTS
    thumb_path = target.with_suffix(".png") if is_video else None

    try:
        trash_path = _move_file_to_trash(target)
    except Exception as exc:
        return False, f"휴지통 이동 실패: {exc}", 500

    log[trash_path.name] = rel_value

    if is_video:
        remove_video_from_db(rel_value)
        if thumb_path and thumb_path.exists():
            try:
                thumb_trash_path = _move_file_to_trash(thumb_path)
                thumb_rel_value = str(Path(rel_value).with_suffix(".png")).replace("\\", "/")
                log[thumb_trash_path.name] = thumb_rel_value
            except Exception:
                pass
    else:
        remove_image_from_db(rel_value)

    return True, None, 200

@bp.post("/delete_image")
def delete_image():
    rel_path = request.form.get("path", "")
    if not rel_path:
        return jsonify({"error": "경로 없음"}), 400

    log = _load_trash_log()
    success, error, status = _delete_single_media(rel_path, log)
    if success:
        _save_trash_log(log)
        return jsonify({"success": True})
    return jsonify({"error": error or "삭제 실패"}), status

@bp.post("/delete_media_batch")
def delete_media_batch():
    payload = request.get_json(silent=True) or {}
    paths = payload.get("paths")
    if not isinstance(paths, list) or not paths:
        return jsonify({
            "success": False,
            "deleted": 0,
            "errors": [],
            "error": "선택된 파일이 없습니다."
        }), 400

    log = _load_trash_log()
    deleted = 0
    errors = []
    fallback_status = 400

    for rel in paths:
        success, err_msg, status = _delete_single_media(str(rel), log)
        if success:
            deleted += 1
        else:
            errors.append({
                "path": rel,
                "message": err_msg or "삭제 실패"
            })
            if status >= 400:
                fallback_status = status

    if deleted:
        _save_trash_log(log)

    response = {
        "success": deleted > 0,
        "deleted": deleted,
        "errors": errors,
    }
    if deleted == 0 and errors:
        response["error"] = errors[0]["message"]

    status_code = 200 if deleted > 0 else fallback_status
    return jsonify(response), status_code

@bp.post("/restore_image")
def restore_image():
    filename = request.form.get("file")
    if not filename:
        return jsonify({"error": "파일 없음"}), 400
    trash_dir = Path(DEST) / "Trash"
    trash_path = trash_dir / filename
    if not trash_path.exists():
        return jsonify({"error": "휴지통에 파일 없음"}), 404

    log_path = trash_dir / "trash_log.json"
    log = {}
    if log_path.exists():
        try:
            log = json.load(log_path.open("r", encoding="utf-8"))
        except Exception:
            log = {}

    def _fallback_restore_dir(source: Path, kind: str) -> Path:
        date_str = datetime.datetime.fromtimestamp(source.stat().st_mtime).strftime("%Y-%m-%d")
        dest_root = _get_dest_root() or Path(DEST)
        # Prefer new layout: DEST/<DEST_CONTENT_SUBDIR>/<date>/<kind>/...
        return get_media_root(dest_root, date_str, kind, create=True)

    def _resolve_restore_path(rel_value: Optional[str], fallback_dir: Path, name: str) -> Path:
        if rel_value:
            resolved = _resolve_rel_path(rel_value)
            if resolved:
                resolved.parent.mkdir(parents=True, exist_ok=True)
                return resolved
        fallback_dir.mkdir(parents=True, exist_ok=True)
        return fallback_dir / name

    ext = trash_path.suffix.lower()
    stem = trash_path.stem
    restore_targets: list[tuple[Path, Path]] = []
    restored_video: Optional[Path] = None
    restored_thumb: Optional[Path] = None

    video_trash: Optional[Path] = None
    thumb_trash: Optional[Path] = None

    if ext in VIDEO_EXTS:
        video_trash = trash_path
        thumb_candidate = trash_dir / f"{stem}.png"
        if thumb_candidate.exists():
            thumb_trash = thumb_candidate
    elif ext == ".png":
        thumb_trash = trash_path
        for v_ext in VIDEO_EXTS:
            candidate = trash_dir / f"{stem}{v_ext}"
            if candidate.exists():
                video_trash = candidate
                break

    if video_trash:
        fallback_dir = _fallback_restore_dir(video_trash, "videos")
        video_rel = log.get(video_trash.name)
        thumb_rel = log.get(thumb_trash.name) if thumb_trash else None
        if not thumb_rel and video_rel:
            thumb_rel = str(Path(video_rel).with_suffix(".png")).replace("\\", "/")

        video_restore = _resolve_restore_path(video_rel, fallback_dir, video_trash.name)
        restore_targets.append((video_trash, video_restore))
        restored_video = video_restore

        if thumb_trash:
            thumb_restore = _resolve_restore_path(thumb_rel, fallback_dir, thumb_trash.name)
            restore_targets.append((thumb_trash, thumb_restore))
            restored_thumb = thumb_restore
    else:
        fallback_dir = _fallback_restore_dir(trash_path, "images")
        original_rel = log.get(filename)
        restore_path = _resolve_restore_path(original_rel, fallback_dir, filename)
        restore_targets.append((trash_path, restore_path))

    for src, dst in restore_targets:
        dst.parent.mkdir(parents=True, exist_ok=True)
        src.rename(dst)
        if src.name in log:
            del log[src.name]

    if log_path.exists():
        try:
            json.dump(log, log_path.open("w", encoding="utf-8"), ensure_ascii=False, indent=2)
        except Exception:
            pass
    if restored_video and restored_video.exists():
        thumb_for_db = restored_thumb if (restored_thumb and restored_thumb.exists()) else restored_video
        meta = extract_prompt_from_file(restored_video)
        upsert_video(restored_video.as_posix(), thumb_for_db.as_posix(), meta=meta)
    elif not restored_video:
        info = extract_prompt_from_png(os.path.dirname(restore_targets[0][1]))
        save_tags_to_db(info)
    return jsonify({"success": True})

@bp.get("/trash")
def trash_page():
    page = request.args.get("page", "1")
    limit = request.args.get("limit", "50")
    try:
        page_num = max(int(page), 1)
    except (TypeError, ValueError):
        page_num = 1
    try:
        limit_num = max(int(limit), 1)
    except (TypeError, ValueError):
        limit_num = 50
    limit_num = min(limit_num, 200)

    trash_dir = Path(DEST) / "Trash"
    files: list[Path] = []
    if trash_dir.is_dir():
        entries = [e for e in trash_dir.iterdir() if e.is_file()]
        for entry in entries:
            ext = entry.suffix.lower()
            if ext == ".png":
                files.append(entry)
                continue
            if ext in VIDEO_EXTS:
                # 영상 단독(=페어 PNG 없음)인 경우에도 목록에 노출
                if not (trash_dir / f"{entry.stem}.png").exists():
                    files.append(entry)

    files.sort(key=lambda item: item.stat().st_mtime, reverse=True)

    total = len(files)
    total_pages = max(math.ceil(total / limit_num), 1)
    if page_num > total_pages:
        page_num = total_pages
    start = (page_num - 1) * limit_num
    end = start + limit_num
    page_files = [f.name for f in files[start:end]]
    start_index = start + 1 if total else 0
    end_index = min(end, total)

    return render_template(
        "trash.html",
        files=page_files,
        page=page_num,
        limit=limit_num,
        total=total,
        total_pages=total_pages,
        start_index=start_index,
        end_index=end_index,
    )

@bp.get("/trash_img/<path:filename>")
def trash_image(filename):
    # NOTE: 휴지통에서도 video-only 파일의 썸네일을 보여주기 위해,
    # 요청된 파일(영상/이미지)로부터 320px PNG 썸네일을 동기 생성/캐시한다.
    safe_name = os.path.basename(filename or "")
    if not safe_name:
        return ("❌ 파일 없음", 404)
    trash_dir = Path(DEST) / "Trash"
    try:
        trash_root = trash_dir.resolve()
        src = (trash_dir / safe_name).resolve()
        src.relative_to(trash_root)
    except Exception:
        return ("❌ 잘못된 경로", 400)

    if not src.is_file():
        return ("❌ 파일 없음", 404)

    rel = f"Trash/{safe_name}"
    normalized = normalize_thumb_rel_path(rel)
    if not normalized:
        return ("❌ 잘못된 경로", 400)

    thumb_path = build_thumb_cache_path(normalized)
    src_str = src.as_posix()

    if not thumb_cache_is_fresh(thumb_path, src_str):
        try:
            generate_thumbnail(src_str, thumb_path)
        except Exception:
            # fallback candidates
            for candidate in build_thumb_fallback_candidates(normalized):
                if os.path.isfile(candidate):
                    resp = send_file(candidate, mimetype="image/png", conditional=True, etag=True)
                    resp.cache_control.public = True
                    resp.cache_control.max_age = 60
                    return resp
            # 마지막 수단: PNG 원본은 직접 제공
            if src.suffix.lower() == ".png":
                resp = send_file(src_str, mimetype="image/png", conditional=True, etag=True)
                resp.cache_control.public = True
                resp.cache_control.max_age = 60
                return resp
            return ("❌ 썸네일 생성 실패", 500)

    if os.path.isfile(thumb_path):
        resp = send_file(thumb_path, mimetype="image/png", conditional=True, etag=True)
        resp.cache_control.public = True
        resp.cache_control.max_age = 60
        return resp

    # thumb가 없다면 fallback 또는 원본
    for candidate in build_thumb_fallback_candidates(normalized):
        if os.path.isfile(candidate):
            resp = send_file(candidate, mimetype="image/png", conditional=True, etag=True)
            resp.cache_control.public = True
            resp.cache_control.max_age = 60
            return resp
    if src.suffix.lower() == ".png":
        resp = send_file(src_str, mimetype="image/png", conditional=True, etag=True)
        resp.cache_control.public = True
        resp.cache_control.max_age = 60
        return resp
    return ("❌ 썸네일 파일 없음", 404)

@bp.post("/trash_delete")
def trash_delete():
    filename = request.form.get("file")
    if not filename:
        return jsonify({"error": "파일 없음"}), 400
    trash_dir = Path(DEST) / "Trash"
    target = trash_dir / filename
    if not target.exists():
        return jsonify({"error": "파일 없음"}), 404

    removed = 0
    counterparts = []
    stem = target.stem
    # 관련된 영상/썸네일 파일도 함께 제거한다.
    for ext in (*VIDEO_EXTS, ".png"):
        candidate = trash_dir / f"{stem}{ext}"
        if candidate.exists():
            counterparts.append(candidate)

    log_path = trash_dir / "trash_log.json"
    log = {}
    if log_path.exists():
        try:
            log = json.load(log_path.open("r", encoding="utf-8"))
        except Exception:
            log = {}

    for candidate in counterparts:
        try:
            candidate.unlink()
            removed += 1
            if candidate.name in log:
                del log[candidate.name]
        except Exception:
            pass

    if log_path.exists():
        try:
            json.dump(log, log_path.open("w", encoding="utf-8"), ensure_ascii=False, indent=2)
        except Exception:
            pass

    return jsonify({"success": True, "removed": removed})

@bp.post("/trash_clear")
def trash_clear():
    trash_dir = os.path.join(DEST, "Trash")
    removed = 0
    if os.path.isdir(trash_dir):
        for f in os.listdir(trash_dir):
            path = os.path.join(trash_dir, f)
            if os.path.isfile(path):
                try:
                    os.remove(path)
                    removed += 1
                except Exception:
                    pass
        log_path = os.path.join(trash_dir, "trash_log.json")
        if os.path.exists(log_path):
            try:
                os.remove(log_path)
            except Exception:
                pass
    return jsonify({"success": True, "removed": removed})

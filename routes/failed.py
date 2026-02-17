from __future__ import annotations
import logging
import os
import shutil
import mimetypes
import threading
import time
from collections import deque
from pathlib import Path
from flask import Blueprint, render_template, request, jsonify, send_file
from settings import DEST, DEST_FOLDER_NAME
from core.ops.full_refresh import recover_failed_only
from core.tagging.tag_utils import extract_prompt_from_file
from core.db.search_utils import save_tags_to_db, remove_image_from_db
from core.media.gallery_layout import get_media_root, rel_under_dest

bp = Blueprint("failed", __name__)
IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".webp")
logger = logging.getLogger(__name__)

_failed_restore_state = {
    "status": "idle",
    "progress": 0,
    "message": "대기 중",
    "last_error": None,
    "summary": None,
    "started_at": None,
    "finished_at": None,
    "updated_at": 0.0,
}
_failed_restore_logs: deque = deque(maxlen=200)
_failed_restore_lock = threading.Lock()
_failed_restore_thread: threading.Thread | None = None


def _append_failed_restore_log(message: str, *, allow_duplicate: bool = True) -> None:
    entry = {"ts": time.time(), "message": message}
    with _failed_restore_lock:
        if not allow_duplicate and _failed_restore_logs and _failed_restore_logs[-1]["message"] == message:
            return
        _failed_restore_logs.append(entry)
        _failed_restore_state["updated_at"] = time.time()


def _update_failed_restore_state(**updates) -> dict:
    with _failed_restore_lock:
        _failed_restore_state.update(updates)
        _failed_restore_state["updated_at"] = time.time()
        state_copy = dict(_failed_restore_state)
        logs_copy = list(_failed_restore_logs)
    state_copy["logs"] = logs_copy
    return state_copy


def _get_failed_restore_state() -> dict:
    with _failed_restore_lock:
        state_copy = dict(_failed_restore_state)
        state_copy["logs"] = list(_failed_restore_logs)
    return state_copy


def _run_failed_restore_task() -> None:
    logger.info("♻️ failed 이미지 복구 작업 시작")
    start_time = time.time()

    def progress_cb(progress, stage=None, detail=None, remaining_steps=None, summary=None):
        msg = detail or stage or "진행 중"
        _update_failed_restore_state(
            progress=int(progress),
            message=msg,
            summary=summary,
        )
        if msg:
            _append_failed_restore_log(msg, allow_duplicate=False)

    try:
        _update_failed_restore_state(
            status="running",
            progress=0,
            message="failed 복구 시작",
            started_at=start_time,
            finished_at=None,
            last_error=None,
            summary=None,
        )
        _append_failed_restore_log("failed 이미지 복구를 시작합니다.")
        summary = recover_failed_only(progress_cb=progress_cb)
        _update_failed_restore_state(
            status="completed",
            progress=100,
            message="failed 복구 완료",
            finished_at=time.time(),
            summary=summary,
        )
        _append_failed_restore_log("failed 이미지 복구가 완료되었습니다.")
        logger.info("✅ failed 이미지 복구 완료")
    except Exception as exc:
        logger.exception("failed 이미지 복구 실패")
        _update_failed_restore_state(
            status="failed",
            message=str(exc),
            last_error=str(exc),
            finished_at=time.time(),
        )
        _append_failed_restore_log(f"오류 발생: {exc}")


def _is_supported_image(filename: str) -> bool:
    lower = filename.lower()
    return any(lower.endswith(ext) for ext in IMAGE_EXTS)


@bp.get("/failed")
def failed_page():
    root = os.path.join(DEST, "failed")
    grouped = {}
    if os.path.isdir(root):
        for date_str in sorted(os.listdir(root)):
            folder = os.path.join(root, date_str)
            if os.path.isdir(folder):
                files = []
                for current_root, _, filenames in os.walk(folder):
                    for filename in filenames:
                        if not _is_supported_image(filename):
                            continue
                        file_path = os.path.join(current_root, filename)
                        rel_path = os.path.relpath(file_path, folder)
                        files.append({
                            "rel_path": Path(rel_path).as_posix(),
                            "label": Path(rel_path).as_posix(),
                            "filename": filename,
                        })
                grouped[date_str] = sorted(files, key=lambda x: x["label"].lower())
    return render_template("failed.html", grouped=grouped)


@bp.get("/failed_img/<date>/<path:filename>")
def failed_img(date, filename):
    path = os.path.join(DEST, "failed", date, filename)
    if os.path.isfile(path):
        mimetype, _ = mimetypes.guess_type(path)
        return send_file(path, mimetype=mimetype)
    return ("❌ 파일 없음", 404)


def _safe_unique_path(base_dir: Path, filename: str) -> Path:
    t = base_dir / filename
    if not t.exists(): return t
    stem, ext = os.path.splitext(filename)
    i = 1
    while True:
        c = base_dir / f"{stem}_{i}{ext}"
        if not c.exists(): return c
        i += 1


@bp.post("/failed_restore")
def failed_restore():
    date = request.form.get("date")
    fname = request.form.get("file")
    if not date or not fname:
        return jsonify({"error": "파라미터 누락"}), 400
    src = os.path.join(DEST, "failed", date, fname)
    dest_root = Path(DEST)
    dst_dir = get_media_root(dest_root, date, "images", create=True)
    orig_ext = Path(fname).suffix
    clean_name = fname.split("(failed")[0] + orig_ext
    try:
        target = _safe_unique_path(Path(dst_dir), os.path.basename(clean_name))
        shutil.move(src, target.as_posix())
        try:
            info = extract_prompt_from_file(target.as_posix())
            if info: save_tags_to_db([info])
        except Exception:
            pass
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@bp.post("/failed_delete")
def failed_delete():
    date = request.form.get("date")
    fname = request.form.get("file")
    if not date or not fname:
        return jsonify({"error": "파라미터 누락"}), 400
    p = os.path.join(DEST, "failed", date, fname)
    try:
        if os.path.isfile(p):
            os.remove(p)
            orig_ext = Path(fname).suffix
            original = fname.split("(failed")[0] + orig_ext
            dest_root = Path(DEST)
            candidates = set()
            # legacy
            candidates.add(f"{DEST_FOLDER_NAME}/{date}/{original}")
            # new layout typical images dir
            try:
                img_dir = get_media_root(dest_root, date, "images")
                candidates.add(f"{DEST_FOLDER_NAME}/{(img_dir / original).relative_to(dest_root).as_posix()}")
            except Exception:
                pass
            for rel in candidates:
                remove_image_from_db(rel)
            return jsonify({"success": True})
        else:
            return jsonify({"error": "파일 없음"}), 404
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@bp.post("/failed_restore_all")
def failed_restore_all():
    global _failed_restore_thread
    with _failed_restore_lock:
        if _failed_restore_state.get("status") == "running" and _failed_restore_thread and _failed_restore_thread.is_alive():
            return jsonify(_get_failed_restore_state()), 202
        _failed_restore_logs.clear()
    _update_failed_restore_state(
        status="running",
        progress=0,
        message="작업 시작 대기 중",
        started_at=time.time(),
        finished_at=None,
        last_error=None,
        summary=None,
    )
    _append_failed_restore_log("failed 이미지 복구 작업을 시작합니다.")
    _failed_restore_thread = threading.Thread(target=_run_failed_restore_task, daemon=True)
    _failed_restore_thread.start()
    return jsonify(_get_failed_restore_state()), 202


@bp.get("/failed_restore_status")
def failed_restore_status():
    return jsonify(_get_failed_restore_state())

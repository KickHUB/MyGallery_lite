from __future__ import annotations
import json
import os, sys, time, webbrowser, threading, logging
from pathlib import Path
import mimetypes
from collections import deque
from typing import Any, Dict

MIN_SUPPORTED_PYTHON = (3, 10)
MAX_SUPPORTED_PYTHON = (3, 14)


def _ensure_supported_python() -> None:
    current = (sys.version_info.major, sys.version_info.minor)
    if MIN_SUPPORTED_PYTHON <= current <= MAX_SUPPORTED_PYTHON:
        return
    current_text = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
    supported_text = (
        f"{MIN_SUPPORTED_PYTHON[0]}.{MIN_SUPPORTED_PYTHON[1]} ~ "
        f"{MAX_SUPPORTED_PYTHON[0]}.{MAX_SUPPORTED_PYTHON[1]}"
    )
    raise SystemExit(
        f"[ERROR] Unsupported Python version: {current_text}. Supported range: {supported_text}."
    )


_ensure_supported_python()

from flask import Flask, abort, g, jsonify, request
from settings import (
    TEMPLATE_FOLDER,
    STATIC_FOLDER,
    ALLOWED_IPS,
    PORT,
    PERF_LOGS,
    THUMB_LOG_SUMMARY,
    DEBUG_MODE,
    DEST,
    SECRET_KEY,
)
from core.db.search_utils import ensure_image_tables
from core.booru.booru_dict import ensure_booru_tables, get_booru_meta
from core.utils.cache_utils import get_static_build_id
from core.tasks.data_tasks import DataTaskManager
from core.media.video_index import ensure_videos_table
from core.ops.full_refresh import (
    full_refresh,
    RefreshCancelled,
)
from core.ops.watcher import start_watchdog, process_existing_on_startup
from core.booru.booru_dict_update import run_booru_dict_update
from core.app.runtime_assets import run_runtime_asset_install, get_runtime_assets_meta
from routes import register_all

def _configure_logging() -> None:
    log_level = logging.DEBUG if DEBUG_MODE else logging.INFO
    logging.basicConfig(level=log_level, format='[%(levelname)s] %(message)s')
    root_logger = logging.getLogger()
    if PERF_LOGS or DEBUG_MODE:
        root_logger.setLevel(log_level)
        for handler in root_logger.handlers:
            if handler.level == logging.NOTSET or handler.level > log_level:
                handler.setLevel(log_level)
    logging.getLogger("werkzeug").addFilter(_ThumbRequestLogFilter())

def _register_mimetypes() -> None:
    mimetypes.add_type("video/mp4", ".mp4")
    mimetypes.add_type("video/webm", ".webm")
    mimetypes.add_type("video/quicktime", ".mov")
    mimetypes.add_type("video/x-matroska", ".mkv")
    mimetypes.add_type("video/x-msvideo", ".avi")


class _ThumbRequestLogFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        if not THUMB_LOG_SUMMARY:
            return True
        try:
            request_line = ""
            if record.args and len(record.args) >= 3:
                request_line = str(record.args[2])
            if not request_line:
                request_line = record.getMessage()
            return " /thumb" not in request_line
        except Exception:
            return True


_configure_logging()
_register_mimetypes()
logger = logging.getLogger(__name__)
THUMB_LOG_SUMMARY_DELAY_SEC = 0.5
_thumb_log_lock = threading.Lock()
_thumb_log_state: Dict[str, Any] = {
    "count": 0,
    "status_counts": {},
    "cache_counts": {},
    "timer": None,
}


def _set_thumb_log_summary_enabled(enabled: bool) -> None:
    global THUMB_LOG_SUMMARY
    THUMB_LOG_SUMMARY = enabled
    if not enabled:
        with _thumb_log_lock:
            timer = _thumb_log_state.get("timer")
            if timer:
                timer.cancel()
            _thumb_log_state["timer"] = None
            _thumb_log_state["count"] = 0
            _thumb_log_state["status_counts"] = {}
            _thumb_log_state["cache_counts"] = {}


def _flush_thumb_summary() -> None:
    with _thumb_log_lock:
        count = _thumb_log_state["count"]
        if count == 0:
            _thumb_log_state["timer"] = None
            return
        status_counts = dict(_thumb_log_state["status_counts"])
        cache_counts = dict(_thumb_log_state["cache_counts"])
        _thumb_log_state["count"] = 0
        _thumb_log_state["status_counts"] = {}
        _thumb_log_state["cache_counts"] = {}
        _thumb_log_state["timer"] = None
    parts = []
    if status_counts:
        status_part = ",".join(
            f"{code}:{status_counts[code]}" for code in sorted(status_counts)
        )
        parts.append(f"status={status_part}")
    if cache_counts:
        cache_part = ",".join(
            f"{key}:{cache_counts[key]}" for key in sorted(cache_counts)
        )
        parts.append(f"cache={cache_part}")
    suffix = f" {' '.join(parts)}" if parts else ""
    logger.info("PERF thumb_summary count=%d%s", count, suffix)


def _record_thumb_summary(response) -> None:
    status = response.status_code
    cache_status = response.headers.get("X-Thumb-Cache")
    if not cache_status:
        cache_status = "fresh" if status in (200, 304) else "unknown"
    with _thumb_log_lock:
        _thumb_log_state["count"] += 1
        status_counts = _thumb_log_state["status_counts"]
        cache_counts = _thumb_log_state["cache_counts"]
        status_counts[status] = status_counts.get(status, 0) + 1
        cache_counts[cache_status] = cache_counts.get(cache_status, 0) + 1
        timer = _thumb_log_state.get("timer")
        if timer:
            timer.cancel()
        timer = threading.Timer(THUMB_LOG_SUMMARY_DELAY_SEC, _flush_thumb_summary)
        timer.daemon = True
        _thumb_log_state["timer"] = timer
        timer.start()

app = Flask(__name__, template_folder=TEMPLATE_FOLDER, static_folder=STATIC_FOLDER)
if SECRET_KEY:
    app.secret_key = SECRET_KEY
else:
    logger.warning("SECRET_KEY가 설정되지 않았습니다. 세션이 불안정할 수 있습니다.")


@app.before_request
def _start_request_timer() -> None:
    if not PERF_LOGS:
        return
    g._perf_start = time.perf_counter()


@app.after_request
def _log_request_performance(response):
    if not PERF_LOGS:
        return response
    if request.path == "/thumb" and THUMB_LOG_SUMMARY:
        _record_thumb_summary(response)
        return response
    start = getattr(g, "_perf_start", None)
    duration_ms = (time.perf_counter() - start) * 1000 if start else 0.0
    endpoint = request.endpoint or "unknown"
    logger.info(
        "PERF request endpoint=%s path=%s status=%s duration_ms=%.2f",
        endpoint,
        request.path,
        response.status_code,
        duration_ms,
    )
    return response


@app.after_request
def _apply_monitoring_cache_headers(response):
    static_url_path = app.static_url_path or "/static"
    if request.path == f"{static_url_path}/script.js":
        build_id = get_static_build_id(app.static_folder, "script.js")
        response.headers["Cache-Control"] = "no-cache, must-revalidate"
        response.set_etag(build_id, weak=True)
    return response

register_all(app)

REFRESH_LOCK_PATH = os.path.join(os.path.dirname(__file__), "data", "refresh.lock")
REFRESH_PERSIST_INTERVAL = float(os.getenv("REFRESH_PERSIST_INTERVAL", "0.5"))


def initialize_database() -> None:
    try:
        ensure_image_tables()
        ensure_videos_table()
        ensure_booru_tables()
        logger.info("데이터베이스 테이블 초기화 완료")
    except Exception as exc:
        logger.exception("데이터베이스 테이블 초기화 실패: %s", exc)
        raise

_refresh_state: Dict[str, Any] = {
    "status": "idle",
    "progress": 0,
    "message": "대기 중",
    "current_step": None,
    "remaining_steps": [],
    "summary": None,
    "started_at": None,
    "finished_at": None,
    "last_error": None,
    "updated_at": 0.0,
}
_refresh_logs: deque = deque(maxlen=200)
_refresh_lock = threading.Lock()
_refresh_thread: threading.Thread | None = None
_refresh_cancel = threading.Event()
_refresh_last_persist: float = 0.0
_refresh_pending_payload: tuple[Dict[str, Any], list[dict[str, Any]]] | None = None

_startup_cleanup_state: Dict[str, Any] = {
    "status": "idle",
    "message": "대기 중",
    "started_at": None,
    "finished_at": None,
    "last_error": None,
    "updated_at": 0.0,
}
_startup_cleanup_lock = threading.Lock()
_data_task_manager = DataTaskManager(
    {
        "booru_dict_update": "Danbooru 태그DB 업데이트",
        "runtime_ffmpeg_install": "FFmpeg/FFprobe 설치",
        "runtime_exiftool_install": "ExifTool 설치",
        "runtime_wd14_install": "WD14 모델 설치",
    }
)


def _ensure_refresh_lock_dir() -> None:
    try:
        os.makedirs(os.path.dirname(REFRESH_LOCK_PATH), exist_ok=True)
    except Exception:
        logger.exception("refresh.lock 디렉터리 생성 실패")


def _record_refresh_lock(data: Dict[str, Any]) -> None:
    tmp_path = f"{REFRESH_LOCK_PATH}.{os.getpid()}.tmp"
    try:
        _ensure_refresh_lock_dir()
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())
        for attempt in range(5):
            try:
                os.replace(tmp_path, REFRESH_LOCK_PATH)
                break
            except PermissionError:
                if attempt == 4:
                    raise
                time.sleep(0.1 * (attempt + 1))
    except Exception:
        logger.exception("refresh.lock 기록 실패")
        try:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
        except Exception:
            logger.exception("refresh.lock 임시 파일 제거 실패")


def _remove_refresh_lock() -> None:
    try:
        if os.path.exists(REFRESH_LOCK_PATH):
            os.remove(REFRESH_LOCK_PATH)
    except Exception:
        logger.exception("refresh.lock 제거 실패")


def _check_stale_refresh_lock() -> None:
    try:
        data = _load_refresh_state_from_disk()
        if not data:
            return
        status = data.get("status")
        started_at = data.get("started_at")
        warning = None
        if status == "running":
            started_str = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(started_at)) if started_at else "알 수 없음"
            warning = f"이전 전체 재정리 작업이 비정상 종료된 것으로 감지되었습니다 (시작: {started_str})."
        # NOTE: completed/failed/cancelled 상태가 디스크에 남아 있는 것은 정상적인 상황입니다.
        #       (서버 재시작 시 UI에서 계속 노이즈 로그가 쌓이지 않도록 경고를 띄우지 않습니다.)
        elif status in ("cancelling", "stopping"):
            warning = f"이전 전체 재정리 작업이 '{status}' 상태에서 중단된 것으로 감지되었습니다."
        if warning:
            logger.warning(warning)
            _append_refresh_log(warning, allow_duplicate=False)
            _update_refresh_state(message=warning, last_error=warning)
    except Exception:
        logger.exception("refresh.lock 확인 중 오류")


def _load_refresh_state_from_disk() -> Dict[str, Any] | None:
    if not os.path.exists(REFRESH_LOCK_PATH):
        return None
    try:
        with open(REFRESH_LOCK_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except json.JSONDecodeError as exc:
        logger.warning("refresh.lock JSON 파싱 실패: %s", exc)
        return None
    except Exception:
        logger.exception("refresh.lock 읽기 실패")
        return None


def _persist_refresh_state(state: Dict[str, Any], logs: list[dict[str, Any]]) -> None:
    payload = {
        "updated_at": time.time(),
        "pid": os.getpid(),
        **state,
        "logs": logs,
    }
    _record_refresh_lock(payload)

def _persist_refresh_state_throttled(
    state: Dict[str, Any],
    logs: list[dict[str, Any]],
    *,
    force: bool = False,
) -> None:
    global _refresh_last_persist, _refresh_pending_payload
    interval = max(0.0, REFRESH_PERSIST_INTERVAL)
    now = time.monotonic()
    if not force and interval > 0 and (now - _refresh_last_persist) < interval:
        _refresh_pending_payload = (state, logs)
        return
    _refresh_last_persist = now
    _refresh_pending_payload = None
    _persist_refresh_state(state, logs)


def _maybe_flush_refresh_pending() -> None:
    global _refresh_last_persist, _refresh_pending_payload
    if not _refresh_pending_payload:
        return
    interval = max(0.0, REFRESH_PERSIST_INTERVAL)
    now = time.monotonic()
    if interval == 0 or (now - _refresh_last_persist) >= interval:
        state, logs = _refresh_pending_payload
        _refresh_pending_payload = None
        _refresh_last_persist = now
        _persist_refresh_state(state, logs)


def _hydrate_refresh_state_from_disk() -> Dict[str, Any] | None:
    data = _load_refresh_state_from_disk()
    if not data:
        return None
    logs_copy = data.get("logs", []) or []
    state_copy = {k: v for k, v in data.items() if k != "logs"}
    with _refresh_lock:
        _refresh_state.clear()
        _refresh_state.update(state_copy)
        _refresh_logs.clear()
        _refresh_logs.extend(logs_copy)
    state_copy["logs"] = logs_copy
    return state_copy


def _append_refresh_log(message: str, *, allow_duplicate: bool = True) -> None:
    entry = {"ts": time.time(), "message": message}
    with _refresh_lock:
        if not allow_duplicate and _refresh_logs and _refresh_logs[-1]["message"] == message:
            return
        _refresh_logs.append(entry)
        _refresh_state["updated_at"] = time.time()
        state_copy = dict(_refresh_state)
        logs_copy = list(_refresh_logs)
    _persist_refresh_state_throttled(state_copy, logs_copy)


def _seed_initial_refresh_logs(include_videos: bool) -> None:
    initial_messages = [
        "DB 백업 준비",
        "이미지 스캔 준비",
        "failed 복구 준비",
        "이미지 정리 준비",
    ]
    if include_videos:
        initial_messages.extend(["영상 인덱스 준비", "영상 정리 준비"])

    for msg in initial_messages:
        _append_refresh_log(msg, allow_duplicate=False)


def _update_refresh_state(**updates) -> Dict[str, Any]:
    with _refresh_lock:
        _refresh_state.update(updates)
        _refresh_state["updated_at"] = time.time()
        state_copy = dict(_refresh_state)
        logs_copy = list(_refresh_logs)
    status = updates.get("status")
    force_persist = status in {"running", "completed", "failed", "cancelled"}
    _persist_refresh_state_throttled(state_copy, logs_copy, force=force_persist)
    state_copy["logs"] = logs_copy
    return state_copy


def _get_refresh_state() -> Dict[str, Any]:
    _maybe_flush_refresh_pending()
    with _refresh_lock:
        state_copy = dict(_refresh_state)
        state_copy["logs"] = list(_refresh_logs)
    return state_copy


def _is_refresh_running() -> bool:
    state = _get_refresh_state()
    return state.get("status") in {"running", "cancelling", "stopping"}


def _is_data_task_running() -> bool:
    payload = _data_task_manager.get_status_payload()
    active = payload.get("active_task")
    if not active:
        return False
    state = (payload.get("tasks") or {}).get(active) or {}
    return state.get("status") in {"running", "cancelling"}


def _guard_not_refresh_running():
    if _is_refresh_running():
        return jsonify({"error": "전체 재정리 작업이 실행 중입니다. 종료 후 다시 시도하세요."}), 409
    return None


def _guard_not_data_task_running():
    if _is_data_task_running():
        return jsonify({"error": "다른 데이터 작업이 실행 중입니다. 종료 후 다시 시도하세요."}), 409
    return None


def _update_startup_cleanup_state(**updates) -> Dict[str, Any]:
    with _startup_cleanup_lock:
        _startup_cleanup_state.update(updates)
        _startup_cleanup_state["updated_at"] = time.time()
        state_copy = dict(_startup_cleanup_state)
    return state_copy


def _get_startup_cleanup_state() -> Dict[str, Any]:
    with _startup_cleanup_lock:
        return dict(_startup_cleanup_state)


def _run_startup_cleanup() -> None:
    _update_startup_cleanup_state(status="running", message="초기 정리 진행 중", started_at=time.time())
    try:
        logger.info("🧹 초기 정리 백그라운드 작업 시작")
        process_existing_on_startup()
        _update_startup_cleanup_state(
            status="completed",
            message="초기 정리 완료",
            finished_at=time.time(),
        )
    except Exception as exc:
        logger.exception("초기 정리 작업 실패: %s", exc)
        _update_startup_cleanup_state(
            status="failed",
            message="초기 정리 실패",
            last_error=str(exc),
            finished_at=time.time(),
        )


_hydrate_refresh_state_from_disk()
_check_stale_refresh_lock()


def _run_refresh_task(include_videos: bool = True):
    logger.info("🔄 전체 재정리 백그라운드 작업 시작")
    start_time = time.time()

    _seed_initial_refresh_logs(include_videos)

    def progress_cb(
        progress: float,
        stage: str | None = None,
        detail: str | None = None,
        remaining_steps=None,
        summary=None,
    ):
        msg = detail or stage or "진행 중"
        _update_refresh_state(
            progress=int(progress),
            message=msg,
            current_step=stage,
            remaining_steps=remaining_steps or [],
            summary=summary,
        )
        if msg:
            _append_refresh_log(msg, allow_duplicate=False)

    try:
        _update_refresh_state(
            status="running",
            progress=0,
            message="작업 대기 중",
            started_at=start_time,
            finished_at=None,
            last_error=None,
        )
        _refresh_cancel.clear()
        full_refresh(
            progress_cb=progress_cb,
            cancel_event=_refresh_cancel,
            include_videos=include_videos,
        )
        _update_refresh_state(status="completed", progress=100, message="전체 재정리 완료", finished_at=time.time())
        _append_refresh_log("전체 재정리가 완료되었습니다.")
        logger.info("✅ 전체 재정리 작업 완료")
    except RefreshCancelled:
        _update_refresh_state(status="cancelled", message="사용자가 취소했습니다.", finished_at=time.time())
        _append_refresh_log("사용자 취소로 작업이 중단되었습니다.")
        logger.info("⚠️ 전체 재정리 작업 취소")
    except Exception as e:
        logger.exception("전체 재정리 작업 중 오류")
        _update_refresh_state(status="failed", message=str(e), last_error=str(e), finished_at=time.time())
        _append_refresh_log(f"오류 발생: {e}")


def start_refresh_task(include_videos: bool = True) -> Dict[str, Any]:
    global _refresh_thread
    with _refresh_lock:
        if _refresh_state.get("status") == "running" and _refresh_thread and _refresh_thread.is_alive():
            return _get_refresh_state()
        _refresh_logs.clear()
    _update_refresh_state(
        status="running",
        progress=0,
        message="작업 시작 대기 중",
        current_step=None,
        remaining_steps=[],
        started_at=time.time(),
        finished_at=None,
        last_error=None,
    )
    _append_refresh_log("전체 재정리 작업을 시작합니다.")
    _refresh_thread = threading.Thread(
        target=_run_refresh_task, args=(include_videos,), daemon=True
    )
    _refresh_thread.start()
    return _get_refresh_state()


def cancel_refresh_task() -> Dict[str, Any]:
    _refresh_cancel.set()
    _append_refresh_log("취소 요청됨")
    return _update_refresh_state(message="취소 신호를 보냈습니다.", status=_refresh_state.get("status"))


def _parse_bool(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "y", "on"}

@app.before_request
def restrict_ip():
    from flask import request
    # Flask request에서 클라이언트 IP 추출
    client_ip = request.remote_addr
    loopbacks = {"127.0.0.1", "::1", "localhost"}
    if ALLOWED_IPS and (client_ip not in ALLOWED_IPS) and (client_ip not in loopbacks):
        logger.warning("❌ 차단된 접근: %s", client_ip)
        abort(403)

@app.route("/update_paths", methods=["POST"])
def update_paths():
    from flask import request, redirect
    from core.utils.env_utils import update_env_vars

    source = request.form.get("source","").strip()
    dest   = request.form.get("dest","").strip()
    index  = request.form.get("index","").strip()
    ffmpeg_path = request.form.get("ffmpeg_path", "").strip()
    if not (os.path.isdir(source) and os.path.isdir(dest)):
        return "<h2>❌ 유효하지 않은 경로입니다. <a href='/'>← 돌아가기</a></h2>", 400
    env_path = Path(__file__).resolve().parent / ".env"
    update_env_vars(
        {
            "SOURCE": source,
            "DEST": dest,
            "INDEX": index,
            "FFMPEG_PATH": ffmpeg_path,
        },
        env_path=str(env_path),
    )
    return redirect("/restart")

@app.route("/refresh", methods=["POST"])
def refresh_all():
    from flask import jsonify, redirect, request

    include_videos_param = request.values.get("include_videos")
    include_videos = True
    if include_videos_param is not None:
        include_videos = str(include_videos_param).lower() not in {"false", "0", "no"}

    wants_json = request.accept_mimetypes.accept_json and not request.accept_mimetypes.accept_html
    is_ajax = request.headers.get("X-Requested-With") == "XMLHttpRequest"

    guard = _guard_not_data_task_running()
    if guard:
        if wants_json or is_ajax:
            return guard
        return redirect("/?refresh_error=data_task")

    state = start_refresh_task(include_videos=include_videos)
    if wants_json or is_ajax:
        return jsonify(state), 202
    return redirect("/")


@app.route("/refresh/status", methods=["GET"])
def refresh_status():
    from flask import jsonify

    state = _get_refresh_state()
    state["startup_cleanup"] = _get_startup_cleanup_state()
    return jsonify(state)


@app.route("/refresh/cancel", methods=["POST"])
def refresh_cancel():
    from flask import jsonify

    state = _get_refresh_state()
    if state.get("status") != "running":
        return jsonify(state)
    return jsonify(cancel_refresh_task())


@app.post("/data/booru-dict-update")
def data_booru_dict_update():
    from flask import jsonify

    guard = _guard_not_refresh_running()
    if guard:
        return guard

    force = _parse_bool(request.values.get("force"), default=False)
    payload = _data_task_manager.start_task(
        "booru_dict_update",
        lambda **kwargs: run_booru_dict_update(force=force, **kwargs),
        start_message="태그DB 업데이트 준비 중",
    )
    status_code = 202 if "error" not in payload else 409
    return jsonify(payload), status_code


@app.get("/data/booru-dict-meta")
def data_booru_dict_meta():
    from flask import jsonify

    try:
        meta = get_booru_meta()
        if "tag_count" in meta:
            try:
                meta["tag_count"] = int(meta["tag_count"])
            except (TypeError, ValueError):
                pass
        return jsonify({"meta": meta})
    except Exception as exc:
        return jsonify({"error": str(exc), "meta": {}}), 500


@app.post("/data/runtime-install")
def data_runtime_install():
    from flask import jsonify

    guard = _guard_not_refresh_running()
    if guard:
        return guard

    target = (request.values.get("target") or "").strip().lower()
    model_key = (request.values.get("model_key") or "").strip()
    task_map = {
        "ffmpeg": ("runtime_ffmpeg_install", "FFmpeg/FFprobe 설치 준비 중"),
        "exiftool": ("runtime_exiftool_install", "ExifTool 설치 준비 중"),
        "wd14": ("runtime_wd14_install", "WD14 모델 설치 준비 중"),
    }
    mapping = task_map.get(target)
    if not mapping:
        return jsonify({"error": "지원하지 않는 설치 대상입니다."}), 400

    task_type, start_message = mapping
    payload = _data_task_manager.start_task(
        task_type,
        lambda **kwargs: run_runtime_asset_install(target=target, model_key=model_key, **kwargs),
        start_message=start_message,
    )
    status_code = 202 if "error" not in payload else 409
    return jsonify(payload), status_code


@app.get("/data/runtime-assets-meta")
def data_runtime_assets_meta():
    from flask import jsonify

    try:
        return jsonify({"meta": get_runtime_assets_meta()})
    except Exception as exc:
        return jsonify({"error": str(exc), "meta": {}}), 500


@app.get("/data/status")
def data_task_status():
    from flask import jsonify

    return jsonify(_data_task_manager.get_status_payload())


@app.post("/data/cancel")
def data_task_cancel():
    from flask import jsonify

    payload = _data_task_manager.cancel_active()
    status_code = 200 if "error" not in payload else 409
    return jsonify(payload), status_code

@app.route("/restart", methods=["GET","POST"])
def restart_server():
    from flask import jsonify, request

    try:
        state = _get_refresh_state()
        if state.get("status") == "running" and _refresh_thread:
            cancel_requested = str(request.values.get("cancel_refresh", "")).lower() in {"1", "true", "yes", "y"}
            force_exit = str(request.values.get("force", "")).lower() in {"1", "true", "yes", "y"}
            if not cancel_requested:
                message = "현재 전체 재정리 작업이 실행 중입니다. ?cancel_refresh=1 파라미터로 취소 후 재시작할 수 있습니다."
                logger.warning(message)
                if request.accept_mimetypes.accept_json and not request.accept_mimetypes.accept_html:
                    return jsonify({"error": message, "refresh_state": state}), 409
                return message, 409

            logger.info("재시작을 위해 전체 재정리 작업 취소 요청")
            _append_refresh_log("재시작을 위해 전체 재정리 작업을 취소합니다.")
            _update_refresh_state(status="cancelling", message="재시작을 위해 종료 대기 중")
            _refresh_cancel.set()
            join_timeout = 30
            _refresh_thread.join(timeout=join_timeout)
            if _refresh_thread.is_alive():
                waiting_msg = f"재정리 스레드가 {join_timeout}초 내 종료되지 않았습니다. 종료를 기다리는 중입니다."
                logger.warning(waiting_msg)
                _append_refresh_log(waiting_msg)
                _update_refresh_state(status="stopping", message="종료 대기 중")
                if not force_exit:
                    response_body = {"error": "작업이 아직 종료되지 않았습니다.", "refresh_state": _get_refresh_state()}
                    wants_json = request.accept_mimetypes.accept_json and not request.accept_mimetypes.accept_html
                    status_code = 503 if wants_json else 409
                    if wants_json:
                        return jsonify(response_body), status_code
                    return "작업이 아직 종료되지 않았습니다. ?force=1 로 강제 종료할 수 있습니다.", status_code
                force_msg = "⚠️ 강제 종료 옵션으로 재시작을 진행합니다. 작업이 완전히 종료되지 않았을 수 있습니다."
                logger.warning(force_msg)
                _append_refresh_log(force_msg)
            else:
                logger.info("재정리 스레드가 안전하게 종료되어 재시작을 진행합니다.")
                _update_refresh_state(message="재시작을 위해 작업이 종료되었습니다.")

        python_exe = sys.executable
        script_path = os.path.abspath(__file__)
        import subprocess
        subprocess.Popen([python_exe, script_path])
        logger.info("♻ 서버 재시작 명령 실행됨")
        os._exit(0)
    except Exception as e:
        return f"❌ 재시작 오류: {e}", 500

@app.get("/restarting")
def restarting_page():
    return "<h1>♻ 서버 재시작 중...</h1><p>새 창을 확인하세요.</p>"

if __name__ == "__main__":
    try:
        initialize_database()
    except Exception:
        logger.error("데이터베이스 초기화에 실패하여 애플리케이션을 종료합니다.")
        sys.exit(1)

    threading.Thread(target=_run_startup_cleanup, daemon=True).start()
    start_watchdog()

    def open_browser():
        time.sleep(1)
        local_url = f"http://127.0.0.1:{PORT}?media=all"
        try:
            webbrowser.open(local_url, new=1)
            logger.info("🌐 로컬 브라우저 자동 연결: %s", local_url)
        except Exception as e:
            logger.warning("⚠️ 브라우저 자동 실행 실패: %s", e)

    threading.Thread(target=open_browser, daemon=True).start()

    local_url = f"http://127.0.0.1:{PORT}"
    logger.info("[INFO] Local-only mode: %s", local_url)

    app.run(host="127.0.0.1", port=PORT, debug=DEBUG_MODE, use_reloader=False)

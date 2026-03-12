from __future__ import annotations

import threading
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Optional


@dataclass
class TaskState:
    task_type: str
    label: str
    status: str = "idle"
    progress: int = 0
    message: str = "대기 중"
    summary: Optional[Dict[str, Any]] = None
    started_at: Optional[float] = None
    finished_at: Optional[float] = None
    last_error: Optional[str] = None
    updated_at: float = 0.0
    logs: deque = field(default_factory=lambda: deque(maxlen=200))
    thread: Optional[threading.Thread] = None
    cancel_event: Optional[threading.Event] = None

    def reset_for_run(self) -> None:
        self.status = "running"
        self.progress = 0
        self.message = "작업 준비 중"
        self.summary = None
        self.started_at = time.time()
        self.finished_at = None
        self.last_error = None
        self.updated_at = time.time()
        self.logs.clear()
        self.cancel_event = threading.Event()

    def append_log(self, message: str) -> None:
        entry = {"ts": time.time(), "message": message}
        self.logs.append(entry)
        self.updated_at = time.time()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "task": self.task_type,
            "label": self.label,
            "status": self.status,
            "progress": self.progress,
            "message": self.message,
            "summary": self.summary,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "last_error": self.last_error,
            "updated_at": self.updated_at,
            "logs": list(self.logs),
        }


class DataTaskManager:
    def __init__(self, labels: Optional[Dict[str, str]] = None) -> None:
        self._lock = threading.Lock()
        self._labels = labels or {}
        self._tasks: Dict[str, TaskState] = {
            task_type: TaskState(task_type=task_type, label=label)
            for task_type, label in self._labels.items()
        }
        self._active_task: Optional[str] = None

    def _get_task(self, task_type: str) -> TaskState:
        if task_type not in self._tasks:
            label = self._labels.get(task_type, task_type)
            self._tasks[task_type] = TaskState(task_type=task_type, label=label)
        return self._tasks[task_type]

    def _build_payload_locked(self) -> Dict[str, Any]:
        return {
            "active_task": self._active_task,
            "tasks": {task_type: state.to_dict() for task_type, state in self._tasks.items()},
        }

    def get_status_payload(self) -> Dict[str, Any]:
        with self._lock:
            return self._build_payload_locked()

    def _make_log_cb(self, task_type: str) -> Callable[[str], None]:
        def _log(message: str) -> None:
            with self._lock:
                state = self._get_task(task_type)
                state.append_log(message)
        return _log

    def _make_progress_cb(self, task_type: str) -> Callable[[float, str | None, Dict[str, Any] | None], None]:
        def _progress(progress: float, message: str | None = None, summary: Dict[str, Any] | None = None) -> None:
            with self._lock:
                state = self._get_task(task_type)
                state.progress = int(progress)
                if message:
                    state.message = message
                if summary is not None:
                    state.summary = summary
                state.updated_at = time.time()
        return _progress

    def start_task(
        self,
        task_type: str,
        target: Callable[..., Dict[str, Any]],
        *,
        start_message: Optional[str] = None,
    ) -> Dict[str, Any]:
        with self._lock:
            if self._active_task:
                active_state = self._tasks.get(self._active_task)
                if active_state and active_state.status in {"running", "cancelling"} and active_state.thread and active_state.thread.is_alive():
                    payload = self._build_payload_locked()
                    payload["error"] = "다른 데이터 작업이 이미 실행 중입니다."
                    return payload

            state = self._get_task(task_type)
            state.reset_for_run()
            if start_message:
                state.message = start_message
            state.append_log(f"{state.label} 작업을 시작합니다.")
            self._active_task = task_type
            cancel_event = state.cancel_event
            log_cb = self._make_log_cb(task_type)
            progress_cb = self._make_progress_cb(task_type)

        thread = threading.Thread(
            target=self._run_task_wrapper,
            args=(task_type, target, progress_cb, log_cb, cancel_event),
            daemon=True,
        )
        with self._lock:
            state.thread = thread
        thread.start()
        return self.get_status_payload()

    def _run_task_wrapper(
        self,
        task_type: str,
        target: Callable[..., Dict[str, Any]],
        progress_cb: Callable[[float, str | None, Dict[str, Any] | None], None],
        log_cb: Callable[[str], None],
        cancel_event: Optional[threading.Event],
    ) -> None:
        try:
            result = target(progress_cb=progress_cb, log_cb=log_cb, cancel_event=cancel_event)
            if cancel_event and cancel_event.is_set():
                self._finish_task(task_type, status="cancelled", message="사용자가 취소했습니다.", summary=(result or {}).get("summary"))
            else:
                status = "completed" if (result or {}).get("status") == "ok" else "failed"
                message = (result or {}).get("message") or "작업이 완료되었습니다."
                summary = (result or {}).get("summary")
                last_error = (result or {}).get("error") if status == "failed" else None
                self._finish_task(task_type, status=status, message=message, summary=summary, last_error=last_error)
        except Exception as exc:
            self._finish_task(task_type, status="failed", message=str(exc), last_error=str(exc))
        finally:
            with self._lock:
                if self._active_task == task_type:
                    self._active_task = None

    def _finish_task(
        self,
        task_type: str,
        *,
        status: str,
        message: str,
        summary: Optional[Dict[str, Any]] = None,
        last_error: Optional[str] = None,
    ) -> None:
        with self._lock:
            state = self._get_task(task_type)
            state.status = status
            state.message = message
            if summary is not None:
                state.summary = summary
            state.finished_at = time.time()
            state.last_error = last_error
            state.updated_at = time.time()
            state.append_log(message)

    def cancel_active(self) -> Dict[str, Any]:
        with self._lock:
            if not self._active_task:
                payload = self._build_payload_locked()
                payload["error"] = "취소할 작업이 없습니다."
                return payload
            state = self._get_task(self._active_task)
            if state.cancel_event:
                state.cancel_event.set()
            if state.status == "running":
                state.status = "cancelling"
            state.message = "취소 요청됨"
            state.append_log("취소 요청됨")
            state.updated_at = time.time()
            return self._build_payload_locked()

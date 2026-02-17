from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional

from flask import Blueprint, jsonify, request

bp = Blueprint("repo_update", __name__)


def _parse_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    return str(value).strip().lower() in {"1", "true", "yes", "y", "on"}


def _run_cmd(args: List[str], timeout: int = 300) -> str:
    """Run a command and return combined stdout/stderr text."""
    completed = subprocess.run(
        args,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
    )
    out = ((completed.stdout or "") + (completed.stderr or "")).strip()
    if completed.returncode != 0:
        raise RuntimeError(out or f"명령 실행 실패: {args} (code={completed.returncode})")
    return out


def _run_git(repo_root: Path, *git_args: str, timeout: int = 300) -> str:
    return _run_cmd(["git", "-C", str(repo_root), *git_args], timeout=timeout)


def _get_repo_root() -> Path:
    # routes/ 아래에 있으므로 부모 1단계가 레포 루트
    return Path(__file__).resolve().parents[1]


def _get_request_value(key: str) -> Optional[Any]:
    # form/query/json 모두 지원 (버튼 호출 방식이 바뀌어도 대응)
    if request.values.get(key) is not None:
        return request.values.get(key)
    payload = request.get_json(silent=True) or {}
    return payload.get(key)


@bp.post("/api/repo/update/mygallery")
def api_update_mygallery() -> tuple:
    """MyGallery 레포를 git pull로 업데이트합니다.

    - 기본: fast-forward only
    - 옵션:
        - rebase=1  -> git pull --rebase --autostash
        - stash=1   -> dirty 상태이면 stash 후 pull, 완료 후 stash pop 시도
    """
    if shutil.which("git") is None:
        return jsonify({"ok": False, "error": "git이 PATH에 없습니다. Git for Windows 설치 후 PATH를 확인하세요."}), 400

    repo_root = _get_repo_root()
    git_dir = repo_root / ".git"
    if not git_dir.exists():
        return jsonify(
            {
                "ok": False,
                "error": "현재 실행 중인 MyGallery 폴더에 .git 이 없습니다. (zip로 설치한 경우) git clone 형태로 설치해야 업데이트 버튼을 사용할 수 있습니다.",
            }
        ), 400

    rebase = _parse_bool(_get_request_value("rebase"))
    stash = _parse_bool(_get_request_value("stash"))

    logs: List[str] = []
    warnings: List[str] = []

    def log(msg: str) -> None:
        logs.append(msg)

    stashed = False

    try:
        log(f"repo_root: {repo_root}")
        branch = _run_git(repo_root, "rev-parse", "--abbrev-ref", "HEAD")
        old_commit = _run_git(repo_root, "rev-parse", "HEAD")

        status = _run_git(repo_root, "status", "--porcelain=v1")
        if status.strip():
            if not stash:
                return jsonify(
                    {
                        "ok": False,
                        "error": "로컬 변경사항이 있어 업데이트할 수 없습니다. (git status가 dirty) 변경사항을 커밋/스태시 후 다시 시도하세요.",
                        "details": status,
                        "repo_root": str(repo_root),
                        "branch": branch,
                    }
                ), 409

            log("dirty 상태 감지 → stash push -u")
            _run_git(repo_root, "stash", "push", "-u", "-m", "MyGallery in-app update")
            stashed = True

        log("git fetch --all --prune")
        fetch_out = _run_git(repo_root, "fetch", "--all", "--prune")
        if fetch_out:
            log(fetch_out)

        if rebase:
            log("git pull --rebase --autostash")
            pull_out = _run_git(repo_root, "pull", "--rebase", "--autostash")
        else:
            log("git pull --ff-only")
            pull_out = _run_git(repo_root, "pull", "--ff-only")
        if pull_out:
            log(pull_out)

        new_commit = _run_git(repo_root, "rev-parse", "HEAD")
        updated = old_commit.strip() != new_commit.strip()

        if stashed:
            try:
                log("stash pop 시도")
                pop_out = _run_git(repo_root, "stash", "pop")
                if pop_out:
                    log(pop_out)
            except Exception as exc:
                warnings.append(
                    "stash pop에 실패했습니다. 충돌이 있을 수 있으니 수동으로 확인하세요. (git stash list / git status)"
                )
                log(f"[stash pop 오류] {exc}")

        return (
            jsonify(
                {
                    "ok": True,
                    "updated": updated,
                    "restart_required": updated,
                    "repo_root": str(repo_root),
                    "branch": branch.strip(),
                    "old_commit": old_commit.strip(),
                    "new_commit": new_commit.strip(),
                    "warnings": warnings,
                    "logs": logs,
                }
            ),
            200,
        )

    except subprocess.TimeoutExpired:
        return jsonify({"ok": False, "error": "git 명령이 시간 초과되었습니다.", "logs": logs}), 504
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc), "logs": logs}), 500

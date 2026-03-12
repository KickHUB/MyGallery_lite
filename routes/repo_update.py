from __future__ import annotations

import logging
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any, List, Optional

from flask import Blueprint, jsonify, request

bp = Blueprint("repo_update", __name__)
logger = logging.getLogger(__name__)

DEFAULT_REMOTE_URL = os.getenv(
    "MYGALLERY_UPDATE_REMOTE_URL",
    "https://github.com/KickHUB/MyGallery_lite.git",
).strip()
DEFAULT_REMOTE_BRANCH = (os.getenv("MYGALLERY_UPDATE_BRANCH", "main") or "main").strip()


def _parse_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    return str(value).strip().lower() in {"1", "true", "yes", "y", "on"}


def _run_cmd(args: List[str], timeout: int = 300) -> str:
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
        raise RuntimeError(out or f"command failed: {args} (code={completed.returncode})")
    return out


def _run_git(repo_root: Path, *git_args: str, timeout: int = 300) -> str:
    return _run_cmd(["git", "-C", str(repo_root), *git_args], timeout=timeout)


def _get_repo_root() -> Path:
    # routes/ under repository root.
    return Path(__file__).resolve().parents[1]


def _get_request_value(key: str) -> Optional[Any]:
    # Support query/form/json.
    if request.values.get(key) is not None:
        return request.values.get(key)
    payload = request.get_json(silent=True) or {}
    return payload.get(key)


def _sanitize_client_text(value: str, repo_root: Path) -> str:
    text = str(value or "")
    root = str(repo_root)
    if not text or not root:
        return text
    variants = {
        root,
        root.replace("\\", "/"),
        root.replace("/", "\\"),
    }
    for candidate in variants:
        text = text.replace(candidate, "<repo>")
    return text


def _sanitize_client_logs(logs: List[str], repo_root: Path) -> List[str]:
    return [_sanitize_client_text(line, repo_root) for line in logs if line]


def _ensure_local_identity(repo_root: Path, log) -> None:
    try:
        _run_git(repo_root, "config", "--get", "user.name")
    except Exception:
        _run_git(repo_root, "config", "--local", "user.name", "MyGallery Updater")
        log("git config user.name (local fallback) applied")

    try:
        _run_git(repo_root, "config", "--get", "user.email")
    except Exception:
        _run_git(
            repo_root,
            "config",
            "--local",
            "user.email",
            "mygallery-updater@users.noreply.local",
        )
        log("git config user.email (local fallback) applied")


def _bootstrap_from_zip_install(
    repo_root: Path,
    *,
    remote_url: str,
    branch: str,
    rebase: bool,
    stash: bool,
    log,
) -> None:
    git_dir = repo_root / ".git"
    if git_dir.exists():
        log("bootstrap skipped: .git already exists")
        return

    log("zip install detected -> git bootstrap start")
    tmp_clone_dir = Path(tempfile.mkdtemp(prefix="mygallery-lite-bootstrap-"))
    try:
        clone_out = _run_cmd(
            [
                "git",
                "clone",
                "--branch",
                branch,
                "--single-branch",
                "--depth",
                "1",
                remote_url,
                str(tmp_clone_dir),
            ],
            timeout=900,
        )
        if clone_out:
            log(clone_out)

        src_git_dir = tmp_clone_dir / ".git"
        if not src_git_dir.exists():
            raise RuntimeError("bootstrap failed: cloned repository has no .git directory")

        shutil.copytree(src_git_dir, git_dir)
        log("bootstrap copied .git metadata into current folder")

        # Keep remote URL synced with request/env overrides.
        _run_git(repo_root, "remote", "set-url", "origin", remote_url)
        _run_git(repo_root, "fetch", "--all", "--prune")
        _ensure_local_identity(repo_root, log)

        if rebase:
            log("bootstrap mode: rebase update requested")
        elif stash:
            log("bootstrap mode: autostash update requested")
        else:
            log("bootstrap mode: ff-only update requested")
    finally:
        shutil.rmtree(tmp_clone_dir, ignore_errors=True)


@bp.post("/api/repo/update/mygallery")
def api_update_mygallery() -> tuple:
    if shutil.which("git") is None:
        return jsonify({"ok": False, "error": "git is not found in PATH."}), 400

    repo_root = _get_repo_root()
    git_dir = repo_root / ".git"

    rebase = _parse_bool(_get_request_value("rebase"))
    stash = _parse_bool(_get_request_value("stash"))
    bootstrap = _parse_bool(_get_request_value("bootstrap"))
    remote_url = str(_get_request_value("remote_url") or DEFAULT_REMOTE_URL).strip()
    branch_name = str(_get_request_value("branch") or DEFAULT_REMOTE_BRANCH).strip() or "main"

    logs: List[str] = []
    warnings: List[str] = []

    def log(msg: str) -> None:
        logs.append(msg)

    stashed = False

    try:
        if not git_dir.exists():
            if not bootstrap:
                return (
                    jsonify(
                        {
                            "ok": False,
                            "error": (
                                "No .git directory found in current MyGallery folder. "
                                "If installed from zip, run update with bootstrap enabled "
                                "or use git clone install."
                            ),
                        }
                    ),
                    400,
                )

            if not remote_url:
                return jsonify({"ok": False, "error": "remote_url is empty. Cannot bootstrap git repo."}), 400

            _bootstrap_from_zip_install(
                repo_root,
                remote_url=remote_url,
                branch=branch_name,
                rebase=rebase,
                stash=stash,
                log=log,
            )
            warnings.append("Zip install detected. Initialized git metadata automatically before update.")

        log("repository root resolved")
        branch = _run_git(repo_root, "rev-parse", "--abbrev-ref", "HEAD")
        old_commit = _run_git(repo_root, "rev-parse", "HEAD")

        status = _run_git(repo_root, "status", "--porcelain=v1")
        if status.strip():
            if not stash:
                return (
                    jsonify(
                        {
                            "ok": False,
                            "error": "Local working tree is dirty. Commit/stash changes first.",
                            "details": status,
                            "branch": branch,
                        }
                    ),
                    409,
                )

            log("dirty working tree detected -> git stash push -u")
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
                log("git stash pop")
                pop_out = _run_git(repo_root, "stash", "pop")
                if pop_out:
                    log(pop_out)
            except Exception as exc:
                warnings.append(
                    "stash pop failed. Check conflicts manually with `git status` and `git stash list`."
                )
                log(f"[stash pop error] {exc}")

        return (
            jsonify(
                {
                    "ok": True,
                    "updated": updated,
                    "restart_required": updated,
                    "branch": branch.strip(),
                    "old_commit": old_commit.strip(),
                    "new_commit": new_commit.strip(),
                    "warnings": warnings,
                    "logs": _sanitize_client_logs(logs, repo_root),
                }
            ),
            200,
        )

    except subprocess.TimeoutExpired:
        logger.warning("Repository update timed out for %s", repo_root)
        return jsonify({"ok": False, "error": "git command timed out.", "logs": _sanitize_client_logs(logs, repo_root)}), 504
    except Exception as exc:
        logger.exception("Repository update failed")
        return (
            jsonify(
                {
                    "ok": False,
                    "error": "Failed to update repository. Check server logs for details.",
                    "logs": _sanitize_client_logs(logs, repo_root),
                }
            ),
            500,
        )

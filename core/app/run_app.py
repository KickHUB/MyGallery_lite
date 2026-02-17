"""Launcher utility for MyGallery.

Responsibilities:
1) ensure execution is inside repo venv
2) check/install required Python packages
3) run first-time portable dependency setup wizard (optional)
4) start main.py
"""

from __future__ import annotations

import argparse
import importlib
import os
import subprocess
import sys
from importlib import metadata
from pathlib import Path

default_environment = None
Requirement = None


def _ensure_packaging_bootstrap():
    global default_environment, Requirement
    if default_environment is not None and Requirement is not None:
        return default_environment, Requirement
    try:
        from packaging.markers import default_environment as _default_environment
        from packaging.requirements import Requirement as _Requirement
        default_environment, Requirement = _default_environment, _Requirement
        return _default_environment, _Requirement
    except ModuleNotFoundError:
        print("[INFO] 'packaging' is missing. Installing bootstrap dependency...")
        try:
            subprocess.check_call(
                [sys.executable, "-m", "pip", "install", "packaging>=24.1,<26"]
            )
        except subprocess.CalledProcessError as exc:
            raise SystemExit(
                "[ERROR] Failed to install bootstrap dependency 'packaging'. "
                "Please check network/pip settings and retry."
            ) from exc
        from packaging.markers import default_environment as _default_environment
        from packaging.requirements import Requirement as _Requirement
        default_environment, Requirement = _default_environment, _Requirement
        return _default_environment, _Requirement


def ensure_virtualenv(repo_root: Path) -> None:
    expected_env = repo_root / "venv"
    virtual_env_envvar = os.environ.get("VIRTUAL_ENV")
    candidates: list[Path] = []

    if virtual_env_envvar:
        candidates.append(Path(virtual_env_envvar))
    candidates.append(Path(sys.prefix))

    for candidate in candidates:
        try:
            if candidate.resolve() == expected_env.resolve():
                return
        except Exception:
            continue

    current_env = virtual_env_envvar or sys.prefix
    raise SystemExit(
        f"[ERROR] Expected venv is {expected_env}, but current environment is {current_env}. "
        "Please run through run_mygallery_venv.bat."
    )


def load_requirements(path: Path) -> list[str]:
    lines: list[str] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        stripped = raw.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped.startswith("-"):
            continue
        cleaned = stripped.split("#", maxsplit=1)[0].strip()
        if cleaned:
            lines.append(cleaned)
    return lines


def find_missing(requirements: list[str]) -> list[str]:
    missing: list[str] = []
    _default_environment, _Requirement = _ensure_packaging_bootstrap()
    env = _default_environment()
    for requirement in requirements:
        req = _Requirement(requirement)
        if req.marker and not req.marker.evaluate(env):
            continue
        try:
            version = metadata.version(req.name)
        except metadata.PackageNotFoundError:
            missing.append(requirement)
            continue
        if req.specifier and version not in req.specifier:
            missing.append(requirement)
    return missing


def install_requirements(repo_root: Path) -> None:
    requirements_path = repo_root / "requirements.txt"
    if not requirements_path.exists():
        raise SystemExit("[ERROR] requirements.txt not found.")
    print("[INFO] Installing required packages from requirements.txt...")
    subprocess.check_call([sys.executable, "-m", "pip", "install", "-r", str(requirements_path)])


def show_torch_status() -> None:
    spec = importlib.util.find_spec("torch")
    if spec is None:
        print("[INFO] torch is not installed. (expected for Lite)")
        return

    torch = importlib.import_module("torch")
    version = getattr(torch, "__version__", "unknown")
    print(f"[INFO] torch version: {version}")

    cuda_available = torch.cuda.is_available()
    print(f"[INFO] torch.cuda.is_available(): {cuda_available}")

    if cuda_available:
        try:
            device_name = torch.cuda.get_device_name(0)
            print(f"[INFO] CUDA device: {device_name}")
        except Exception as exc:  # pylint: disable=broad-exception-caught
            print(f"[WARN] Failed to read CUDA device name: {exc}")


def _bool_env(name: str, default: bool = False) -> bool:
    if name not in os.environ:
        return default
    return str(os.getenv(name, default)).strip().lower() in ("1", "true", "yes", "on")


def maybe_run_portable_setup(repo_root: Path, *, force: bool, skip: bool) -> None:
    if skip:
        return
    if not (sys.stdin.isatty() and sys.stdout.isatty()):
        return

    state_path = repo_root / "tools" / "portable_setup_state.json"
    if state_path.exists() and not force:
        return

    script_dir = Path(__file__).resolve().parent
    if str(script_dir) not in sys.path:
        sys.path.insert(0, str(script_dir))

    try:
        from portable_tools_setup import run_portable_tools_setup
    except Exception as exc:  # pragma: no cover
        print(f"[WARN] Portable setup module load failed: {exc}")
        return

    try:
        run_portable_tools_setup(repo_root=repo_root, force=force)
    except Exception as exc:  # pragma: no cover
        print(f"[WARN] Portable dependency setup failed: {exc}")


def main() -> None:
    parser = argparse.ArgumentParser(description="MyGallery launcher utility")
    parser.add_argument("--repair", action="store_true", help="Automatically install missing required packages.")
    parser.add_argument(
        "--portable-tools-setup",
        action="store_true",
        help="Force-run portable dependency setup wizard.",
    )
    parser.add_argument(
        "--skip-portable-tools-setup",
        action="store_true",
        help="Skip portable dependency setup wizard.",
    )
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parents[2]
    os.chdir(repo_root)

    ensure_virtualenv(repo_root)
    auto_install = args.repair or _bool_env("MYGALLERY_AUTO_INSTALL", False)
    requirements_path = repo_root / "requirements.txt"
    if not requirements_path.exists():
        raise SystemExit("[ERROR] requirements.txt not found.")

    missing = find_missing(load_requirements(requirements_path))

    if missing:
        print("[WARN] Missing or incompatible required packages:")
        for pkg in missing:
            print(f"       - {pkg}")
        if auto_install:
            install_requirements(repo_root)
        else:
            print("[WARN] Auto install is disabled. Use --repair or MYGALLERY_AUTO_INSTALL=1.")
    else:
        print("[INFO] All required packages are already installed.")

    maybe_run_portable_setup(
        repo_root,
        force=args.portable_tools_setup,
        skip=args.skip_portable_tools_setup,
    )

    show_torch_status()
    subprocess.check_call([sys.executable, str(repo_root / "main.py")])


if __name__ == "__main__":
    main()

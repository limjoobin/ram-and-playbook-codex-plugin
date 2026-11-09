#!/usr/bin/env python3
"""Standard-library launcher for the plugin's private redis-iris runtime.

The plugin runs on the redis-iris SDK, which has compiled dependencies, so it
cannot run from the bare plugin cache. This launcher keeps one private virtual
environment per Python version and pinned requirement set under the plugin
data directory, installs the exact pins as binary wheels on first use, and then
replaces itself with that interpreter.

    python3 launch.py             # ensure the runtime, then run the MCP server
    python3 launch.py --install   # ensure the runtime only (explicit setup step)
    python3 launch.py --check     # exit 0 when the runtime is ready
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
import subprocess
import sys

MINIMUM_PYTHON = (3, 11)
SERVER_ROOT = Path(__file__).resolve().parent
REQUIREMENTS = SERVER_ROOT / "requirements.txt"
MAIN = SERVER_ROOT / "main.py"
READY_MARKER = ".ready"


def _fail(message: str) -> None:
    sys.stderr.write(f"Redis Shared Memory: {message}\n")
    raise SystemExit(1)


def data_root(environment: os._Environ[str] | dict[str, str] | None = None) -> Path:
    values = os.environ if environment is None else environment
    configured = (values.get("PLUGIN_DATA") or "").strip()
    if configured:
        return Path(configured).expanduser()
    return Path.home() / ".local" / "share" / "redis-shared-memory"


def runtime_dir(environment: os._Environ[str] | dict[str, str] | None = None) -> Path:
    digest = hashlib.sha256(REQUIREMENTS.read_bytes()).hexdigest()[:16]
    version = f"py{sys.version_info.major}{sys.version_info.minor}"
    return data_root(environment) / "runtime" / f"{version}-{digest}"


def _python(venv: Path) -> Path:
    if os.name == "nt":
        return venv / "Scripts" / "python.exe"
    return venv / "bin" / "python"


def runtime_python(environment: os._Environ[str] | dict[str, str] | None = None) -> Path | None:
    """The ready runtime interpreter, or None. Never installs anything."""

    if sys.version_info < MINIMUM_PYTHON:
        return None
    venv = runtime_dir(environment)
    python = _python(venv)
    if (venv / READY_MARKER).is_file() and python.is_file():
        return python
    return None


def _locked_install(venv: Path) -> Path:
    import fcntl
    import venv as venv_module

    venv.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    lock_path = venv.parent / f"{venv.name}.lock"
    with open(lock_path, "w", encoding="utf-8") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        python = _python(venv)
        if (venv / READY_MARKER).is_file() and python.is_file():
            return python
        sys.stderr.write(
            "Redis Shared Memory: installing the pinned redis-iris runtime (first run only)...\n"
        )
        venv_module.EnvBuilder(with_pip=True, clear=True).create(venv)
        result = subprocess.run(
            [
                str(python),
                "-m",
                "pip",
                "install",
                "--disable-pip-version-check",
                "--no-input",
                "--only-binary=:all:",
                "--require-virtualenv",
                "-r",
                str(REQUIREMENTS),
            ],
            stdout=sys.stderr,
            stderr=sys.stderr,
            check=False,
        )
        if result.returncode != 0:
            _fail(
                "the redis-iris runtime could not be installed. Check network access to the "
                "approved Python package index, then run: python3 server/launch.py --install"
            )
        (venv / READY_MARKER).write_text(
            hashlib.sha256(REQUIREMENTS.read_bytes()).hexdigest() + "\n", encoding="utf-8"
        )
        return python


def ensure_runtime() -> Path:
    if sys.version_info < MINIMUM_PYTHON:
        _fail("Python 3.11 or newer is required as python3.")
    ready = runtime_python()
    if ready is not None:
        return ready
    return _locked_install(runtime_dir())


def main(argv: list[str]) -> None:
    if argv[:1] == ["--check"]:
        raise SystemExit(0 if runtime_python() is not None else 1)
    python = ensure_runtime()
    if argv[:1] == ["--install"]:
        sys.stderr.write(f"Redis Shared Memory: runtime ready at {python.parent.parent}\n")
        return
    os.execv(str(python), [str(python), "-I", str(MAIN), *argv])


if __name__ == "__main__":
    main(sys.argv[1:])

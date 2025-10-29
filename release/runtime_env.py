"""Set default runtime environment for the packaged CLI.

When running from the PyInstaller bundle, this module will:
1. Load optional environment overrides from resources/env/.env.
2. Start the embedded Ollama runtime if no external URL is configured.
3. Ensure the shipped model alias exists (creating it on first run).
4. Export CENTRAL_LLM_URL / CENTRAL_LLM_MODEL so the CLI can connect.
"""

from __future__ import annotations

import atexit
import os
import socket
import subprocess
import time
from pathlib import Path

try:
    from urllib.request import urlopen
except ImportError:  # pragma: no cover - Python < 3.11 not supported
    urlopen = None  # type: ignore


def _load_env_file(env_path: Path) -> None:
    try:
        content = env_path.read_text(encoding="utf-8")
    except Exception:
        return
    for raw_line in content.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if not key:
            continue
        os.environ.setdefault(key, value.strip())


def _read_text(path: Path, default: str = "") -> str:
    try:
        return path.read_text(encoding="utf-8").strip() or default
    except Exception:
        return default


def _is_local_url(url: str) -> bool:
    lower = (url or "").lower()
    return any(token in lower for token in ("127.0.0.1", "localhost"))


def _pick_port() -> int:
    explicit = os.getenv("NOCTICS_EMBEDDED_OLLAMA_PORT")
    if explicit:
        try:
            value = int(explicit)
            if value > 0:
                return value
        except Exception:
            pass
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _wait_for_endpoint(url: str, timeout: float = 20.0) -> bool:
    if urlopen is None:
        return False
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urlopen(url, timeout=2.0):
                return True
        except Exception:
            time.sleep(0.25)
    return False


def _list_models(ollama_bin: Path, env: dict[str, str]) -> set[str]:
    try:
        output = subprocess.check_output(
            [str(ollama_bin), "list"],
            env=env,
            stderr=subprocess.DEVNULL,
            text=True,
        )
    except Exception:
        return set()
    names = []
    for line in output.splitlines()[1:]:
        parts = line.split()
        if parts:
            names.append(parts[0])
    return set(names)


def _ensure_model(
    *,
    ollama_bin: Path,
    env: dict[str, str],
    alias: str,
    modelfile: Path,
    cwd: Path,
) -> None:
    if alias in _list_models(ollama_bin, env):
        return
    if not modelfile.exists():
        return
    stdout = subprocess.DEVNULL
    stderr = subprocess.STDOUT
    if os.getenv("NOCTICS_DEBUG_RUNTIME") == "1":
        stdout = None
        stderr = None
    subprocess.run(
        [str(ollama_bin), "create", alias, "-f", str(modelfile)],
        check=True,
        env=env,
        cwd=str(cwd),
        stdout=stdout,
        stderr=stderr,
    )


def _resolve_resources_root(runtime_path: Path) -> Path:
    """Find the PyInstaller resources directory that holds the embedded assets."""

    candidates = [
        runtime_path / "resources",
        runtime_path / "_internal" / "resources",
        runtime_path.parent / "resources",
        runtime_path.parent / "_internal" / "resources",
    ]
    for candidate in candidates:
        if (candidate / "ollama" / "bin" / "ollama").exists():
            return candidate

    for ancestor in runtime_path.parents:
        candidate = ancestor / "resources"
        if (candidate / "ollama" / "bin" / "ollama").exists():
            return candidate

    raise RuntimeError("Embedded Ollama binary missing: no resources directory found")


def _start_embedded_ollama(
    *,
    root: Path,
    alias: str,
    modelfile: Path,
) -> tuple[subprocess.Popen[bytes], dict[str, str], str]:
    ollama_bin = root / "ollama" / "bin" / "ollama"
    models_dir = root / "ollama" / "models"
    runtime_dir = root / "runtime"
    if not ollama_bin.exists():
        raise RuntimeError(f"Embedded Ollama binary missing: {ollama_bin}")
    models_dir.mkdir(parents=True, exist_ok=True)
    runtime_dir.mkdir(parents=True, exist_ok=True)

    port = _pick_port()
    host = f"127.0.0.1:{port}"
    env = os.environ.copy()
    env.setdefault("OLLAMA_MODELS", str(models_dir))
    env.setdefault("OLLAMA_HOME", str(root / "ollama"))
    env.setdefault("OLLAMA_HOST", host)

    process = subprocess.Popen(
        [str(ollama_bin), "serve"],
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    if not _wait_for_endpoint(f"http://{host}/api/version", timeout=30.0):
        process.terminate()
        raise RuntimeError("Embedded Ollama runtime failed to start within the timeout window")

    _ensure_model(
        ollama_bin=ollama_bin,
        env=env,
        alias=alias,
        modelfile=modelfile,
        cwd=root,
    )

    return process, env, host


def _prepare_environment() -> None:
    runtime_path = Path(__file__).resolve().parent
    if os.getenv("NOCTICS_DEBUG_RUNTIME") == "1":
        try:
            debug_file = Path(os.getenv("NOCTICS_DEBUG_FILE", "/tmp/noctics_runtime_debug.txt"))
            debug_file.write_text(f"runtime_path={runtime_path}\n", encoding="utf-8")
        except Exception:
            pass
    resources_root = _resolve_resources_root(runtime_path)
    env_file = resources_root / "env" / ".env"
    if env_file.exists():
        _load_env_file(env_file)

    runtime_dir = resources_root / "runtime"
    alias_file = runtime_dir / "primary_alias.txt"
    alias = os.environ.get("CENTRAL_LLM_MODEL") or _read_text(alias_file, "centi-nox")
    modelfile = runtime_dir / f"{alias}.modelfile"

    existing_url = os.environ.get("CENTRAL_LLM_URL")
    if existing_url:
        if not _is_local_url(existing_url):
            os.environ.setdefault("CENTRAL_LLM_MODEL", alias)
            return
        if os.environ.get("NOCTICS_FORCE_EMBEDDED_OLLAMA") != "1":
            os.environ.setdefault("CENTRAL_LLM_MODEL", alias)
            return

    if os.environ.get("NOCTICS_SKIP_EMBEDDED_OLLAMA") == "1":
        os.environ.setdefault("CENTRAL_LLM_MODEL", alias)
        return

    process, env, host = _start_embedded_ollama(
        root=resources_root,
        alias=alias,
        modelfile=modelfile,
    )

    def _cleanup(proc: subprocess.Popen[bytes]) -> None:
        try:
            proc.terminate()
        except Exception:
            pass

    atexit.register(_cleanup, process)

    os.environ.setdefault("CENTRAL_LLM_MODEL", alias)
    os.environ.setdefault("CENTRAL_LLM_URL", f"http://{host}/api/generate")
    os.environ.setdefault("OLLAMA_MODELS", env["OLLAMA_MODELS"])


_prepare_environment()

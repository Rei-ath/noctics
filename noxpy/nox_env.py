"""Environment helpers for Nox orchestration with secure secret fallbacks."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Dict, List, Optional

_SECRETS_CACHE: Dict[str, str] | None = None


def _default_secret_roots() -> List[Path]:
    roots: List[Path] = []
    env_root = os.getenv("NOCTICS_CONFIG_HOME")
    if env_root:
        roots.append(Path(env_root).expanduser())
    home = Path.home()
    if sys.platform == "win32":
        base = Path(os.getenv("APPDATA", home / "AppData" / "Roaming"))
        roots.extend([base / "Noctics", base / "noctics"])
    elif sys.platform == "darwin":
        base = home / "Library/Application Support"
        roots.extend([base / "Noctics", base / "noctics"])
    else:
        xdg = Path(os.getenv("XDG_CONFIG_HOME", home / ".config"))
        roots.extend([xdg / "noctics", home / ".config/noctics"])
    deduped: List[Path] = []
    for root in roots:
        expanded = root.expanduser()
        if expanded not in deduped:
            deduped.append(expanded)
    return deduped


def _load_secrets() -> Dict[str, str]:
    """Load key/value pairs from a secrets file or directory if configured."""

    global _SECRETS_CACHE
    if _SECRETS_CACHE is not None:
        return _SECRETS_CACHE

    secrets: Dict[str, str] = {}
    file_hint = os.getenv("NOCTICS_SECRETS_FILE")
    dir_hint = os.getenv("NOCTICS_SECRETS_DIR")

    if file_hint:
        path = Path(file_hint).expanduser()
        if path.is_file():
            for line in path.read_text(encoding="utf-8").splitlines():
                stripped = line.strip()
                if not stripped or stripped.startswith("#") or "=" not in stripped:
                    continue
                key, value = stripped.split("=", 1)
                secrets[key.strip()] = value.strip()

    if dir_hint:
        root = Path(dir_hint).expanduser()
        if root.is_dir():
            for candidate in root.iterdir():
                if candidate.is_file():
                    secrets[candidate.name] = candidate.read_text(encoding="utf-8").strip()

    for root in _default_secret_roots():
        default_file = root / "secrets.env"
        if default_file.is_file():
            for line in default_file.read_text(encoding="utf-8").splitlines():
                stripped = line.strip()
                if not stripped or stripped.startswith("#") or "=" not in stripped:
                    continue
                key, value = stripped.split("=", 1)
                secrets.setdefault(key.strip(), value.strip())

    _SECRETS_CACHE = secrets
    return secrets


def get_env(name: str) -> Optional[str]:
    """Return an environment value, falling back to the configured secrets source."""

    value = os.getenv(name)
    if value is None:
        secrets = _load_secrets()
        value = secrets.get(name)
    if value is None:
        return None
    trimmed = value.strip()
    return trimmed or None


def require_env(name: str) -> str:
    value = get_env(name)
    if value is None:
        raise RuntimeError(
            f"Missing environment variable: {name}. "
            "Define it in your secrets backend or export it before running Nox."
        )
    return value

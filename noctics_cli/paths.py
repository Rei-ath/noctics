"""Shared path utilities for installer and setup logic."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Optional


def _env_path(name: str) -> Optional[Path]:
    value = os.getenv(name)
    if not value:
        return None
    return Path(value).expanduser()


def config_home() -> Path:
    """Return the per-user configuration directory."""

    override = _env_path("NOCTICS_CONFIG_HOME")
    if override:
        return override

    home = Path.home()
    if sys.platform == "win32":
        base = Path(os.getenv("APPDATA", home / "AppData" / "Roaming"))
        return base / "Noctics"
    if sys.platform == "darwin":
        base = home / "Library" / "Application Support"
        return base / "Noctics"
    base = Path(os.getenv("XDG_CONFIG_HOME", home / ".config"))
    return base / "noctics"


def install_home() -> Path:
    """Return the root directory for binaries/runtime assets."""

    override = _env_path("NOCTICS_INSTALL_HOME")
    if override:
        return override

    home = Path.home()
    if sys.platform == "win32":
        base = Path(os.getenv("LOCALAPPDATA", home / "AppData" / "Local"))
        return base / "Noctics"
    if sys.platform == "darwin":
        base = home / "Library" / "Application Support"
        return base / "Noctics" / "Runtime"
    base = Path(os.getenv("XDG_DATA_HOME", home / ".local" / "share"))
    return base / "noctics"


def bin_dir() -> Path:
    """Return the directory where shims should be dropped."""

    override = _env_path("NOCTICS_BIN_DIR")
    if override:
        return override

    home = Path.home()
    if sys.platform == "win32":
        base = Path(os.getenv("LOCALAPPDATA", home / "AppData" / "Local"))
        return base / "Noctics" / "bin"
    return home / ".local" / "bin"


__all__ = ["config_home", "install_home", "bin_dir"]

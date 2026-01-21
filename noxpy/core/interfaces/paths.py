"""Shared path utilities for resolving user memory locations."""

from __future__ import annotations

import os
import shutil
from pathlib import Path

__all__ = [
    "resolve_data_root",
    "resolve_memory_root",
    "resolve_sessions_root",
    "resolve_users_root",
]


def _expand(path: str) -> Path:
    return Path(path).expanduser()


def resolve_data_root() -> Path:
    """Return the base data directory for Noctics user data.

    Precedence:
    1. ``NOCTICS_DATA_ROOT`` environment variable
    2. ``XDG_DATA_HOME`` if set, falling back to ``~/.local/share``
    """

    override = os.getenv("NOCTICS_DATA_ROOT")
    if override:
        return _expand(override)

    xdg = os.getenv("XDG_DATA_HOME")
    if xdg:
        base = _expand(xdg)
    else:
        base = Path.home() / ".local" / "share"
    return base / "noctics"


_REPO_MEMORY_ROOT = Path(__file__).resolve().parents[2] / "memory"


def _migrate_legacy_memory(target: Path) -> None:
    if target.exists():
        return
    legacy_root = _REPO_MEMORY_ROOT
    if legacy_root.exists() and legacy_root != target:
        try:
            target.mkdir(parents=True, exist_ok=True)
        except Exception:
            pass
        for subdir in ("sessions", "users", "early-archives"):
            src = legacy_root / subdir
            dest = target / subdir
            if src.exists() and not dest.exists():
                try:
                    shutil.copytree(src, dest, dirs_exist_ok=True)
                except Exception:
                    continue
        for file_path in legacy_root.glob("*"):
            if file_path.is_file():
                dest = target / file_path.name
                if not dest.exists():
                    try:
                        shutil.copy2(file_path, dest)
                    except Exception:
                        continue


def resolve_memory_root() -> Path:
    """Return the directory that should store session memories."""

    override = os.getenv("NOCTICS_MEMORY_HOME")
    if override:
        root = _expand(override)
    else:
        root = resolve_data_root() / "memory"

    _migrate_legacy_memory(root)
    try:
        root.mkdir(parents=True, exist_ok=True)
    except PermissionError:
        # Fallback to legacy in-place storage when the preferred location is not writable
        legacy = _REPO_MEMORY_ROOT
        legacy.mkdir(parents=True, exist_ok=True)
        return legacy
    if not _is_writable_directory(root):
        legacy = _REPO_MEMORY_ROOT
        legacy.mkdir(parents=True, exist_ok=True)
        return legacy
    return root


def resolve_sessions_root() -> Path:
    root = resolve_memory_root() / "sessions"
    root.mkdir(parents=True, exist_ok=True)
    return root


def resolve_users_root() -> Path:
    root = resolve_memory_root() / "users"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _is_writable_directory(path: Path) -> bool:
    if not path.exists():
        return False
    if not os.access(path, os.W_OK | os.X_OK):
        return False
    probe = path / ".noctics-write-test"
    try:
        with probe.open("w", encoding="utf-8") as handle:
            handle.write("")
        probe.unlink(missing_ok=True)
        return True
    except Exception:
        if probe.exists():
            try:
                probe.unlink()
            except Exception:
                pass
        return False

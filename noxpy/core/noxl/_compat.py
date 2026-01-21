"""Compatibility utilities that keep the noxl toolkit lightweight.

These wrappers make the CLI resilient when optional runtime dependencies
such as ``central`` or ``interfaces`` are not available. Each utility
prefers the richer implementation when present and otherwise falls back
to standard-library only behaviour.
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Callable, Optional

_FG_CODES = {
    "black": "30",
    "red": "31",
    "green": "32",
    "yellow": "33",
    "blue": "34",
    "magenta": "35",
    "cyan": "36",
    "white": "37",
}

try:
    from central.colors import color as _central_color  # type: ignore
except Exception:  # pragma: no cover - handled by fallback
    _central_color: Optional[Callable[..., str]] = None

try:
    from interfaces.session_logger import (
        format_session_display_name as _format_session_display_name,  # type: ignore
    )
except Exception:  # pragma: no cover - handled by fallback
    _format_session_display_name = None  # type: ignore[assignment]

try:
    from interfaces.paths import (  # type: ignore
        resolve_memory_root as _interfaces_memory_root,
        resolve_sessions_root as _interfaces_sessions_root,
        resolve_users_root as _interfaces_users_root,
    )
except Exception:  # pragma: no cover - handled by fallback
    _interfaces_memory_root = None  # type: ignore[assignment]
    _interfaces_sessions_root = None  # type: ignore[assignment]
    _interfaces_users_root = None  # type: ignore[assignment]


def _fallback_color(text: str, *, fg: Optional[str] = None, bold: bool = False) -> str:
    codes = []
    if bold:
        codes.append("1")
    if fg:
        code = _FG_CODES.get(fg.lower())
        if code:
            codes.append(code)
    if not codes:
        return text
    prefix = f"\033[{';'.join(codes)}m"
    suffix = "\033[0m"
    return f"{prefix}{text}{suffix}"


def color(text: str, *, fg: Optional[str] = None, bold: bool = False) -> str:
    """Colourise ``text`` when possible; fall back to plain output otherwise."""

    if _central_color is not None:
        try:
            return _central_color(text, fg=fg, bold=bold)
        except Exception:
            pass
    return _fallback_color(text, fg=fg, bold=bold)


def _fallback_format_session_display_name(session_id: str) -> str:
    base = (session_id or "").strip()
    if not base:
        return "Session"
    pretty = base.replace("-", " ")
    return pretty.title()


def format_session_display_name(session_id: str) -> str:
    """Return a human-friendly label for ``session_id``."""

    if _format_session_display_name is not None:
        try:
            return _format_session_display_name(session_id)
        except Exception:
            pass
    return _fallback_format_session_display_name(session_id)


def _fallback_memory_root() -> Path:
    override = os.getenv("NOCTICS_MEMORY_HOME")
    if override:
        root = Path(override).expanduser()
    else:
        data_override = os.getenv("NOCTICS_DATA_ROOT")
        if data_override:
            base = Path(data_override).expanduser()
        else:
            xdg = os.getenv("XDG_DATA_HOME")
            if xdg:
                base = Path(xdg).expanduser()
            else:
                base = Path.home() / ".local" / "share"
        root = base / "noctics" / "memory"
    fallback_root = (Path(__file__).resolve().parents[2] / "memory").resolve()
    try:
        root.mkdir(parents=True, exist_ok=True)
    except Exception:
        fallback_root.mkdir(parents=True, exist_ok=True)
        return fallback_root
    if not _is_writable_directory(root):
        fallback_root.mkdir(parents=True, exist_ok=True)
        return fallback_root
    return root


def _is_writable_directory(path: Path) -> bool:
    if not path.exists():
        return False
    if not os.access(path, os.W_OK | os.X_OK):
        return False
    probe = path / ".noxl-write-test"
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


@lru_cache(maxsize=None)
def resolve_memory_root() -> Path:
    """Resolve the base memory directory with graceful fallbacks."""

    if _interfaces_memory_root is not None:
        try:
            return Path(_interfaces_memory_root())
        except Exception:
            pass
    return _fallback_memory_root()


@lru_cache(maxsize=None)
def resolve_sessions_root() -> Path:
    """Resolve the sessions directory, creating it when necessary."""

    if _interfaces_sessions_root is not None:
        try:
            return Path(_interfaces_sessions_root())
        except Exception:
            pass
    root = resolve_memory_root() / "sessions"
    root.mkdir(parents=True, exist_ok=True)
    return root


@lru_cache(maxsize=None)
def resolve_users_root() -> Path:
    """Resolve the users directory, creating it when necessary."""

    if _interfaces_users_root is not None:
        try:
            return Path(_interfaces_users_root())
        except Exception:
            pass
    root = resolve_memory_root() / "users"
    root.mkdir(parents=True, exist_ok=True)
    return root


__all__ = [
    "color",
    "format_session_display_name",
    "resolve_memory_root",
    "resolve_sessions_root",
    "resolve_users_root",
]

"""Reusable HUD ASCII art helpers for the Noctics CLI."""

from __future__ import annotations

from pathlib import Path
from typing import Iterable, List, Mapping, Sequence

from nox_env import get_env

__all__ = ["resolve_logo_lines"]

# Default HUD art matches the official Nox banner.
# Default HUD art matches the official Nox banner.
_DEFAULT_LOGO: Sequence[str] = (
    "╔╗╔┌─┐─┐┬",
    "║║║││┌┴┬┘",
    "╝╚╝└─┘┴└─",
)
# Placeholder art keeps dimensions reasonable while inviting customization.
_PLACEHOLDER_LOGO: Sequence[str] = (
    "┌────────────────────────────┐",
    "│        NOCTICS HUD        │",
    "└────────────────────────────┘",
)

# Preset mapping so scale/variant hints can swap banners without touching code.
_LOGO_PRESETS: Mapping[str, Sequence[str]] = {
    "default": _DEFAULT_LOGO,
    "placeholder": _PLACEHOLDER_LOGO,
    # Provide named placeholders for common variants—replace in config/overrides.
    "nano": _PLACEHOLDER_LOGO,
    "micro": _PLACEHOLDER_LOGO,
    "milli": _PLACEHOLDER_LOGO,
    "centi": _DEFAULT_LOGO,
}


def _clean_lines(lines: Iterable[str]) -> List[str]:
    cleaned = [line.rstrip("\n\r") for line in lines]
    return cleaned if any(cleaned) else []


def _load_art_file(path: Path) -> List[str]:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return []
    return _clean_lines(text.splitlines())


def resolve_logo_lines(*, style_hint: str | None = None) -> List[str]:
    """Return the ASCII art lines for the HUD banner.

    Precedence:
        1. Environment variable ``NOX_HUD_ASCII`` (``\\n``-separated lines)
        2. Environment variable ``NOX_HUD_ASCII_FILE`` pointing to a text file
        3. Named preset selected via ``NOX_HUD_STYLE`` or ``style_hint``
        4. Placeholder banner inviting customization
    """

    inline_override = get_env("NOX_HUD_ASCII")
    if inline_override:
        return _clean_lines(inline_override.split("\\n"))

    file_override = get_env("NOX_HUD_ASCII_FILE")
    if file_override:
        art = _load_art_file(Path(file_override).expanduser())
        if art:
            return art

    style = (get_env("NOX_HUD_STYLE") or style_hint or "default").strip().lower()
    preset = _LOGO_PRESETS.get(style)
    if not preset and style.endswith("-nox"):
        preset = _LOGO_PRESETS.get(style.split("-")[0])
    if not preset and ":" in style:
        preset = _LOGO_PRESETS.get(style.split(":", 1)[0])

    if preset:
        return list(preset)

    return list(_PLACEHOLDER_LOGO)

"""Minimal CLI facade retained for backwards compatibility."""

from __future__ import annotations

from central.core.reasoning import strip_chain_of_thought
from .simple import build_parser, main, parse_args

def _extract_visible_reply(text: str | None) -> tuple[str, bool]:
    """Return the user-visible reply and whether a think block was present."""

    if text is None:
        return "", False
    lower = text.lower()
    cleaned = strip_chain_of_thought(text) or ""
    return cleaned, "<think>" in lower


__all__ = ["_extract_visible_reply", "build_parser", "main", "parse_args"]

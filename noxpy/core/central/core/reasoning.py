"""Reasoning and output sanitisation utilities for Nox."""

from __future__ import annotations

import re
from typing import List, Optional, Tuple

__all__ = ["strip_chain_of_thought", "extract_public_segments", "clean_public_reply"]

_THINK_PATTERN = re.compile(r"<think>.*?</think>\s*", re.IGNORECASE | re.DOTALL)
_INSTRUMENT_RESULT_BLOCK = re.compile(
    r"^\s*\[INSTRUMENT\s+RESULT\](.*?)\[/INSTRUMENT\s+RESULT\]\s*$",
    re.IGNORECASE | re.DOTALL,
)
_AUX_BLOCKS = [
    re.compile(r"\[SET\s*TITLE\].*?\[/SET\s*TITLE\]", re.IGNORECASE | re.DOTALL),
    re.compile(r"\[INSTRUMENT\s+QUERY\].*?\[/INSTRUMENT\s+QUERY\]", re.IGNORECASE | re.DOTALL),
    re.compile(r"\[INSTRUMENT\s+RESULT\].*?\[/INSTRUMENT\s+RESULT\]", re.IGNORECASE | re.DOTALL),
]
_NOX_PREFIX = re.compile(r"^(?:(?:Noctics\s+)?Nox\s*[:：]\s*)+", re.IGNORECASE)
_HARDWARE_PREFIX = re.compile(r"^hardware\s+context\s*:\s*", re.IGNORECASE)


def strip_chain_of_thought(text: Optional[str]) -> Optional[str]:
    """Remove ``<think>...</think>`` segments while preserving public content."""

    if text is None:
        return None
    cleaned = _THINK_PATTERN.sub("", text)
    return cleaned.strip()


def extract_public_segments(buffer: str) -> Tuple[str, str]:
    """Return ``(public_text, remainder)`` preserving incomplete think blocks."""

    lower = buffer.lower()
    pos = 0
    public_parts: List[str] = []
    length = len(buffer)
    open_tag = "<think>"
    close_tag = "</think>"
    open_len = len(open_tag)
    close_len = len(close_tag)

    while pos < length:
        open_idx = lower.find(open_tag, pos)
        if open_idx == -1:
            public_parts.append(buffer[pos:])
            return "".join(public_parts), ""
        public_parts.append(buffer[pos:open_idx])
        close_search_start = open_idx + open_len
        close_idx = lower.find(close_tag, close_search_start)
        if close_idx == -1:
            return "".join(public_parts), buffer[open_idx:]
        pos = close_idx + close_len

    return "".join(public_parts), ""


def clean_public_reply(text: Optional[str]) -> Optional[str]:
    """Normalise assistant replies before surfacing them to the user.

    Removes instrument result wrappers, duplicate CLI labels, and stray hardware
    context echoes that occasionally leak from the model output.
    """

    if text is None:
        return None

    cleaned = text.strip()
    if not cleaned:
        return cleaned

    # Drop repeated CLI label prefixes such as "Nox:" or "Noctics Nox:"
    cleaned = _NOX_PREFIX.sub("", cleaned, count=1).lstrip()

    def _unwrap_result_block(value: str) -> str:
        for pattern in (_INSTRUMENT_RESULT_BLOCK,):
            match = pattern.match(value)
            if match:
                return match.group(1).strip()
        return value

    cleaned = _unwrap_result_block(cleaned)

    # Remove leading hardware context echoes
    lines = cleaned.splitlines()
    while lines:
        first = lines[0].strip()
        if not first:
            lines.pop(0)
            continue
        if _HARDWARE_PREFIX.match(first):
            lines.pop(0)
            # Drop following blank separator if present
            while lines and not lines[0].strip():
                lines.pop(0)
            continue
        break

    cleaned = "\n".join(lines).strip()
    cleaned = _unwrap_result_block(cleaned)
    for pattern in _AUX_BLOCKS:
        cleaned = pattern.sub("", cleaned)
    # Strip template tokens and closing tags produced by local models
    cleaned = re.sub(r"<\|/?(?:assistant|user)\|>", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\[\s*/\s*(?:assistant|dev|user)\s*\]", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"</\s*(?:assistant|dev|user)\s*>", "", cleaned, flags=re.IGNORECASE)
    cleaned = cleaned.strip()
    return cleaned

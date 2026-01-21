"""Instrument follow-up prompt loading utilities for Nox."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

__all__ = ["load_instrument_prompt"]

_DEFAULT_PROMPT = (
    "You are **Nox**, acting as a structured explainer and code provider.\n"
    "You always work with a JSON object where each key contains two fields:\n"
    "- \"point\" → human explanation (not copyable)\n"
    "- \"copy\" → Python code snippet (safe for the user to copy-paste)\n\n"
    "Behavior Rules:\n"
    "1. If the user asks for an explanation, return the \"point\".\n"
    "   - Prefix with: **\"Explanation:\"**\n"
    "2. If the user asks for a code snippet, return the \"copy\".\n"
    "   - Prefix with: **\"Code (copy-paste):\"**\n"
    "3. If the user asks for a full runnable script, concatenate all \"copy\" fields in the correct order, and output as a single Python file.\n"
    "   - Prefix with: **\"Full Script:\"**\n"
    "4. Never mix modes:\n"
    "   - Do **not** show \"point\" if code is requested.\n"
    "   - Do **not** show \"copy\" unless clearly labeled as copyable.\n"
    "5. If user intent is unclear, explicitly ask:\n"
    "   - “Do you want the explanation (point), snippet (copy), or full script?”\n"
)

_INSTRUMENT_PROMPT_CACHE: Optional[str] = None


def load_instrument_prompt() -> str:
    """Return the instrument follow-up prompt, cached after first read."""

    global _INSTRUMENT_PROMPT_CACHE
    if _INSTRUMENT_PROMPT_CACHE is not None:
        return _INSTRUMENT_PROMPT_CACHE

    prompt_path = Path(__file__).resolve().parents[1] / "memory" / "instrument_result_prompt.txt"
    try:
        text = prompt_path.read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        text = ""
    if text:
        _INSTRUMENT_PROMPT_CACHE = text
    else:
        _INSTRUMENT_PROMPT_CACHE = _DEFAULT_PROMPT
    return _INSTRUMENT_PROMPT_CACHE

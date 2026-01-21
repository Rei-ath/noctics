"""Public interface for the Nox chat client package."""

from __future__ import annotations

from .client import ChatClient, DEFAULT_URL
from .instrument_prompt import load_instrument_prompt
from .payloads import build_payload
from .reasoning import clean_public_reply, extract_public_segments, strip_chain_of_thought

_extract_public_segments = extract_public_segments
_load_instrument_prompt = load_instrument_prompt

__all__ = [
    "ChatClient",
    "DEFAULT_URL",
    "build_payload",
    "load_instrument_prompt",
    "clean_public_reply",
    "extract_public_segments",
    "strip_chain_of_thought",
    "_extract_public_segments",
    "_load_instrument_prompt",
]

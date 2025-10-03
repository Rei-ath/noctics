"""Instrument registry for routing Central requests through provider SDKs."""

from __future__ import annotations

from typing import Optional, Tuple

from .base import BaseInstrument
from .openai import OpenAIInstrument

_REGISTRY: tuple[type[BaseInstrument], ...] = (OpenAIInstrument,)


def build_instrument(
    *,
    url: Optional[str],
    model: Optional[str],
    api_key: Optional[str],
) -> Tuple[Optional[BaseInstrument], Optional[str]]:
    """Return the first instrument that supports the configured target.

    Parameters mirror the core chat client's configuration. Returns a tuple of
    ``(instrument, warning)`` where ``warning`` is a human-readable message if
    the instrument could not be instantiated (e.g., missing dependency).
    """

    for cls in _REGISTRY:
        instrument, warning = cls.maybe_create(url=url, model=model, api_key=api_key)
        if instrument is not None or warning:
            return instrument, warning
    return None, None


__all__ = ["build_instrument"]

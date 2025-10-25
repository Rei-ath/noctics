"""Instrument registry for routing Central requests through provider SDKs."""

from __future__ import annotations

import importlib
import os
from typing import Iterable, List, Optional, Tuple, Type

from .base import BaseInstrument

_REGISTRY: List[Type[BaseInstrument]] = []


def register_instrument(cls: Type[BaseInstrument]) -> None:
    """Register an instrument implementation.

    Plugins can call this at import time to add themselves to the registry.
    """

    if cls not in _REGISTRY:
        _REGISTRY.append(cls)


def iter_instruments() -> Iterable[Type[BaseInstrument]]:
    return tuple(_REGISTRY)


def _import_plugin(module_name: str) -> None:
    module_name = module_name.strip()
    if not module_name:
        return
    try:
        importlib.import_module(module_name)
    except Exception:
        # Ignore plugin load failures; they can be surfaced via logs elsewhere if needed.
        return


def _load_plugins_from_env() -> None:
    raw = os.getenv("CENTRAL_INSTRUMENT_PLUGINS", "")
    if not raw:
        return
    for token in raw.split(","):
        _import_plugin(token)


from .openai import OpenAIInstrument  # noqa: E402  (import after register definition)

register_instrument(OpenAIInstrument)

try:  # noqa: E402
    from .anthropic import AnthropicInstrument
except Exception:
    AnthropicInstrument = None  # type: ignore[assignment]
else:
    register_instrument(AnthropicInstrument)

_load_plugins_from_env()


def build_instrument(
    *,
    url: Optional[str],
    model: Optional[str],
    api_key: Optional[str],
) -> Tuple[Optional[BaseInstrument], Optional[str]]:
    """Return the first instrument that supports the configured target."""

    for cls in _REGISTRY:
        instrument, warning = cls.maybe_create(url=url, model=model, api_key=api_key)
        if instrument is not None or warning:
            return instrument, warning
    return None, None


__all__ = ["build_instrument", "register_instrument", "iter_instruments"]

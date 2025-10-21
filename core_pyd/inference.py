"""Shim module that exposes the compiled ``inference`` extension."""

from __future__ import annotations

import sys as _sys

from core_pyd import ensure_modules as _ensure_modules

_module = _ensure_modules(("inference",))["inference"]
_sys.modules[__name__] = _module

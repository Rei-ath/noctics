"""Shim module that exposes the compiled ``central`` extension."""

from __future__ import annotations

import sys as _sys

from core_pinaries import ensure_modules as _ensure_modules

_module = _ensure_modules(("central",))["central"]
_sys.modules[__name__] = _module

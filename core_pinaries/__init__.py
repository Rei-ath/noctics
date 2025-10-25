"""
Binary distribution shim for the Noctics core packages.

Importing ``core_pinaries`` ensures the compiled ``central``, ``config``,
``inference``, ``interfaces``, and ``noxl`` extension modules are registered so downstream code can
``import central`` without accessing the Python sources.
"""

from __future__ import annotations

import importlib.machinery
import importlib.util
import pathlib
import sys
from types import ModuleType
from typing import Iterable


_ROOT = pathlib.Path(__file__).resolve().parent
_MODULE_NAMES: tuple[str, ...] = ("central", "config", "inference", "interfaces", "noxl")


def _resolve_extension_path(name: str) -> pathlib.Path:
    pattern = f"{name}.cpython-*.so"
    candidates = sorted(_ROOT.glob(pattern))
    if not candidates:
        raise ImportError(f"Missing compiled extension for '{name}' in {_ROOT}")
    return candidates[0]


def _load_extension(name: str) -> ModuleType:
    path = _resolve_extension_path(name)
    loader = importlib.machinery.ExtensionFileLoader(name, str(path))
    spec = importlib.util.spec_from_loader(name, loader)
    if spec is None:
        raise ImportError(f"Unable to build spec for extension '{name}' at {path}")
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    sys.modules[name] = module
    return module


def ensure_modules(names: Iterable[str] = _MODULE_NAMES) -> dict[str, ModuleType]:
    """Ensure the compiled modules are present in ``sys.modules``."""
    loaded: dict[str, ModuleType] = {}
    for name in names:
        if name in sys.modules:
            loaded[name] = sys.modules[name]
            continue
        loaded[name] = _load_extension(name)
    return loaded


# Load the canonical modules on import so `import central` works immediately.
_loaded = ensure_modules()

__all__ = tuple(_loaded.keys())

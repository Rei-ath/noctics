"""Shim package that bootstraps Noctics core modules.

When the full source tree is present, this module is effectively empty.
When only the compiled binaries are available, importing :mod:`core`
loads the compiled extensions so packages such as :mod:`central` remain
importable.
"""

from __future__ import annotations

import importlib
import pathlib


def _bootstrap() -> None:
    root = pathlib.Path(__file__).resolve().parent
    if (root / "central").is_dir():
        # Source tree is available; nothing special to do.
        return
    try:
        core_bin = importlib.import_module("core_pinaries")
    except ModuleNotFoundError as exc:  # pragma: no cover - missing binary bundle
        raise ImportError(
            "Noctics core binaries not found. Install the core_pinaries package or "
            "provide the core source tree."
        ) from exc
    core_bin.ensure_modules()


_bootstrap()

__all__ = []

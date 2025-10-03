"""Noxics Central CLI package."""

from __future__ import annotations

import sys
from pathlib import Path

_CORE_ROOT = Path(__file__).resolve().parents[1] / "core"
if str(_CORE_ROOT) not in sys.path:
    sys.path.insert(0, str(_CORE_ROOT))

from .app import main, parse_args, RuntimeIdentity, resolve_runtime_identity
from .dev import (
    CENTRAL_DEV_PASSPHRASE_ATTEMPT_ENV,
    require_dev_passphrase,
    resolve_dev_passphrase,
    validate_dev_passphrase,
)

__all__ = [
    "main",
    "parse_args",
    "RuntimeIdentity",
    "resolve_runtime_identity",
    "require_dev_passphrase",
    "validate_dev_passphrase",
    "resolve_dev_passphrase",
    "CENTRAL_DEV_PASSPHRASE_ATTEMPT_ENV",
]

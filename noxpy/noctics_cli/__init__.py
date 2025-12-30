"""Noctics CLI package."""

from __future__ import annotations

from .args import parse_args
from .multitool import main as multitool_main

try:
    from .app import main as chat_main, RuntimeIdentity, resolve_runtime_identity
    from .dev import (
        NOX_DEV_PASSPHRASE_ATTEMPT_ENV,
        require_dev_passphrase,
        resolve_dev_passphrase,
        validate_dev_passphrase,
    )
except ImportError as exc:  # pragma: no cover - surfaced to the caller
    raise ImportError(
        "Noctics CLI requires the noctics-core package. "
        "Install it with `pip install noctics-core` or include it in your environment."
    ) from exc

__all__ = [
    "main",
    "chat_main",
    "parse_args",
    "RuntimeIdentity",
    "resolve_runtime_identity",
    "require_dev_passphrase",
    "validate_dev_passphrase",
    "resolve_dev_passphrase",
    "NOX_DEV_PASSPHRASE_ATTEMPT_ENV",
]

main = multitool_main

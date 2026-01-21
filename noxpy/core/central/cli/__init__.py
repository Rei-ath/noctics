"""Lightweight CLI entrypoints bundled with the public core package."""

from __future__ import annotations

from ..runtime_identity import RuntimeIdentity, resolve_runtime_identity
from .dev import (
    NOX_DEV_PASSPHRASE_ATTEMPT_ENV,
    require_dev_passphrase,
    resolve_dev_passphrase,
    validate_dev_passphrase,
)
from .simple import build_parser, main, parse_args

__all__ = [
    "NOX_DEV_PASSPHRASE_ATTEMPT_ENV",
    "RuntimeIdentity",
    "build_parser",
    "main",
    "parse_args",
    "require_dev_passphrase",
    "resolve_dev_passphrase",
    "resolve_runtime_identity",
    "validate_dev_passphrase",
]

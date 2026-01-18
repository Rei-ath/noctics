"""Noctics CLI package."""

from __future__ import annotations

from typing import Any, List

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


def _require_core() -> None:
    try:
        import central  # noqa: F401
    except Exception as exc:  # pragma: no cover - surfaced to caller
        raise ImportError(
            "Noctics CLI requires the noctics-core package. "
            "Install it with `pip install noctics-core` or include it in your environment."
        ) from exc


def __getattr__(name: str) -> Any:
    if name in {"main", "multitool_main"}:
        from .multitool import main as multitool_main
        return multitool_main
    if name == "parse_args":
        from .args import parse_args
        return parse_args
    if name in {"chat_main", "RuntimeIdentity", "resolve_runtime_identity"}:
        _require_core()
        from .app import main as chat_main, RuntimeIdentity, resolve_runtime_identity
        if name == "chat_main":
            return chat_main
        if name == "RuntimeIdentity":
            return RuntimeIdentity
        return resolve_runtime_identity
    if name in {
        "NOX_DEV_PASSPHRASE_ATTEMPT_ENV",
        "require_dev_passphrase",
        "resolve_dev_passphrase",
        "validate_dev_passphrase",
    }:
        _require_core()
        from .dev import (
            NOX_DEV_PASSPHRASE_ATTEMPT_ENV,
            require_dev_passphrase,
            resolve_dev_passphrase,
            validate_dev_passphrase,
        )
        mapping = {
            "NOX_DEV_PASSPHRASE_ATTEMPT_ENV": NOX_DEV_PASSPHRASE_ATTEMPT_ENV,
            "require_dev_passphrase": require_dev_passphrase,
            "resolve_dev_passphrase": resolve_dev_passphrase,
            "validate_dev_passphrase": validate_dev_passphrase,
        }
        return mapping[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__() -> List[str]:
    return sorted(__all__)

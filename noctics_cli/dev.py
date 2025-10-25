"""Developer-mode utilities for the Central CLI."""

from __future__ import annotations

import os
from getpass import getpass
from typing import Optional

try:
    from central.colors import color
    from central.config import get_runtime_config
except ImportError as exc:  # pragma: no cover - dependency missing
    raise ImportError(
        "Noctics CLI developer instruments require the noctics-core package. "
        "Install it with `pip install noctics-core` or ensure the central modules are importable."
    ) from exc

DEFAULT_DEV_PASSPHRASE = "jx0"
CENTRAL_DEV_PASSPHRASE_ENV = "CENTRAL_DEV_PASSPHRASE"
CENTRAL_DEV_PASSPHRASE_ATTEMPT_ENV = "CENTRAL_DEV_PASSWORD_ATTEMPT"

__all__ = [
    "CENTRAL_DEV_PASSPHRASE_ENV",
    "CENTRAL_DEV_PASSPHRASE_ATTEMPT_ENV",
    "DEFAULT_DEV_PASSPHRASE",
    "resolve_dev_passphrase",
    "validate_dev_passphrase",
    "require_dev_passphrase",
]


def resolve_dev_passphrase() -> Optional[str]:
    env_value = os.getenv(CENTRAL_DEV_PASSPHRASE_ENV)
    if env_value:
        return env_value
    config_value = get_runtime_config().developer.passphrase
    if config_value:
        return config_value
    return DEFAULT_DEV_PASSPHRASE


def validate_dev_passphrase(expected: Optional[str], *, attempt: Optional[str]) -> bool:
    if not expected:
        return True
    if attempt is None:
        return False
    return attempt == expected


def require_dev_passphrase(expected: Optional[str], *, interactive: bool) -> bool:
    if not expected:
        return True

    if not interactive:
        attempt = os.getenv(CENTRAL_DEV_PASSPHRASE_ATTEMPT_ENV)
        return validate_dev_passphrase(expected, attempt=attempt)

    for _ in range(3):
        attempt = getpass(color("Developer passphrase: ", fg="yellow"))
        if validate_dev_passphrase(expected, attempt=attempt):
            return True
        print(color("Incorrect developer passphrase.", fg="red"))
    return False

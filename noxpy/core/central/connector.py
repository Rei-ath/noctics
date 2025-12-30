"""Connector utilities for instantiating Nox transports."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional
import os

from .transport import LLMTransport, ProcessTransport

__all__ = ["ConnectorConfig", "NoxConnector", "build_connector"]


@dataclass(slots=True)
class ConnectorConfig:
    """Configuration bundle describing how Nox should connect to an LLM."""

    url: str
    api_key: Optional[str] = None
    runner: Optional[str] = None
    model_path: Optional[str] = None


class NoxConnector:
    """Factory responsible for creating the transport that backs ChatClient."""

    def __init__(self, config: ConnectorConfig) -> None:
        self.config = config

    def connect(self) -> LLMTransport:
        """Return the configured transport for Nox."""

        if self.config.runner:
            return ProcessTransport(self.config.runner, model_path=self.config.model_path)

        return LLMTransport(self.config.url, self.config.api_key)


def build_connector(*, url: Optional[str], api_key: Optional[str]) -> NoxConnector:
    """Return the default connector used by Nox.

    Edit this function (or replace ``NoxConnector``) to swap out the
    transport implementation application-wide without touching other modules.
    """

    runner_path = _resolve_runner_path()
    model_path = _resolve_model_path()
    if runner_path:
        return NoxConnector(ConnectorConfig(url=url or "", api_key=api_key, runner=runner_path, model_path=model_path))

    if url is None:
        raise RuntimeError("NOX_LLM_URL is not configured and no local runner was found.")

    return NoxConnector(ConnectorConfig(url=url, api_key=api_key))


def _resolve_runner_path() -> Optional[str]:
    env_path = os.getenv("NOX_LOCAL_RUNNER")
    if env_path:
        candidate = Path(env_path).expanduser()
        if candidate.exists():
            return str(candidate)
    root = Path(__file__).resolve().parents[2]
    global_bin = root / "bin" / "noxlocal"
    if global_bin.exists():
        return str(global_bin)
    legacy = root / "localrunner" / "noxlocal"
    if legacy.exists():
        return str(legacy)
    return None


def _resolve_model_path() -> Optional[str]:
    env_path = os.getenv("NOX_MODEL_PATH")
    if env_path:
        candidate = Path(env_path).expanduser()
        if candidate.exists():
            return str(candidate)
    root = Path(__file__).resolve().parents[2]
    default = root / "assets" / "models" / "nox.gguf"
    if default.exists():
        return str(default)
    return None

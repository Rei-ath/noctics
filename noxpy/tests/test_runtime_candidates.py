"""Coverage for CLI runtime candidate selection."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CORE_ROOT = PROJECT_ROOT / "core"
if str(CORE_ROOT) not in sys.path:
    sys.path.insert(0, str(CORE_ROOT))
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import nox_env
from noctics_cli import app as noctics_app
from noctics_cli.args import DEFAULT_URL as CLI_DEFAULT_URL


def _args(*, url: object, model: object = "nox:latest", api_key: object = None) -> argparse.Namespace:
    return argparse.Namespace(url=url, model=model, api_key=api_key)


def test_build_runtime_candidates_defaults_to_local_when_url_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(nox_env, "_SECRETS_CACHE", {}, raising=False)
    monkeypatch.delenv("NOX_LLM_FALLBACK_URLS", raising=False)
    monkeypatch.delenv("NOX_LLM_FALLBACK_MODELS", raising=False)
    monkeypatch.delenv("NOX_LLM_FALLBACK_API_KEYS", raising=False)
    monkeypatch.delenv("NOX_LOCAL_LLM_URL", raising=False)
    monkeypatch.delenv("NOX_LOCAL_LLM_MODEL", raising=False)

    candidates = noctics_app._build_runtime_candidates(_args(url=None))

    assert len(candidates) == 1
    assert candidates[0].url == CLI_DEFAULT_URL
    assert candidates[0].source == "local default"
    assert all(candidate.url != "None" for candidate in candidates)


def test_build_runtime_candidates_treats_literal_none_as_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(nox_env, "_SECRETS_CACHE", {}, raising=False)
    monkeypatch.delenv("NOX_LLM_FALLBACK_URLS", raising=False)
    monkeypatch.delenv("NOX_LLM_FALLBACK_MODELS", raising=False)
    monkeypatch.delenv("NOX_LLM_FALLBACK_API_KEYS", raising=False)
    monkeypatch.delenv("NOX_LOCAL_LLM_URL", raising=False)
    monkeypatch.delenv("NOX_LOCAL_LLM_MODEL", raising=False)

    candidates = noctics_app._build_runtime_candidates(_args(url="None"))

    assert len(candidates) == 1
    assert candidates[0].url == CLI_DEFAULT_URL
    assert candidates[0].source == "local default"
    assert all(candidate.url != "None" for candidate in candidates)


def test_build_runtime_candidates_adds_local_fallback_for_remote_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(nox_env, "_SECRETS_CACHE", {}, raising=False)
    monkeypatch.delenv("NOX_LLM_FALLBACK_URLS", raising=False)
    monkeypatch.delenv("NOX_LLM_FALLBACK_MODELS", raising=False)
    monkeypatch.delenv("NOX_LLM_FALLBACK_API_KEYS", raising=False)
    monkeypatch.delenv("NOX_LOCAL_LLM_URL", raising=False)
    monkeypatch.delenv("NOX_LOCAL_LLM_MODEL", raising=False)

    candidates = noctics_app._build_runtime_candidates(
        _args(url="https://api.openai.com/v1/chat/completions", model="gpt-4o-mini")
    )

    assert len(candidates) == 2
    assert candidates[0].url == "https://api.openai.com/v1/chat/completions"
    assert candidates[0].source == "configured"
    assert candidates[1].url == CLI_DEFAULT_URL
    assert candidates[1].source == "local fallback"

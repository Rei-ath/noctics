"""Ensure project root is on sys.path for test imports."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

CORE_ROOT = ROOT / "core"
if str(CORE_ROOT) not in sys.path:
    sys.path.insert(0, str(CORE_ROOT))


@pytest.fixture(autouse=True)
def _nox_env_defaults(monkeypatch):
    """Provide sane defaults for tests that construct ChatClient."""

    monkeypatch.setenv("NOX_LLM_URL", "http://example.com/v1/chat")
    monkeypatch.setenv("NOX_LLM_MODEL", "test-nox")
    monkeypatch.setenv("NOX_OPENAI_MODEL", "gpt-4o-mini")

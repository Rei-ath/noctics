from __future__ import annotations

import importlib
import sys
import types
from typing import Any, Dict

import pytest

from instruments import build_instrument


class _FakeMessages:
    def __init__(self) -> None:
        self.create_calls: list[Dict[str, Any]] = []
        self.stream_calls: list[Dict[str, Any]] = []

    def create(self, **kwargs: Any):
        self.create_calls.append(dict(kwargs))
        return types.SimpleNamespace(content=[types.SimpleNamespace(type="text", text="hello from claude")])

    def stream(self, **kwargs: Any):
        self.stream_calls.append(dict(kwargs))

        class _Stream:
            def __enter__(self_inner):
                return self_inner

            def __exit__(self_inner, exc_type, exc, tb):
                return False

            def __iter__(self_inner):
                yield types.SimpleNamespace(
                    type="content_block_delta",
                    delta=types.SimpleNamespace(text="hello "),
                )
                yield types.SimpleNamespace(
                    type="content_block_delta",
                    delta=types.SimpleNamespace(text="from "),
                )
                yield types.SimpleNamespace(
                    type="content_block_delta",
                    delta=types.SimpleNamespace(text="claude"),
                )

            def get_final_response(self_inner):
                return types.SimpleNamespace(content=[types.SimpleNamespace(type="text", text="hello from claude")])

        return _Stream()


class _FakeAnthropic:
    def __init__(self, api_key: str) -> None:
        self.api_key = api_key
        self.messages = _FakeMessages()


@pytest.fixture(autouse=True)
def _install_fake_anthropic(monkeypatch):
    fake_module = types.ModuleType("anthropic")
    fake_module.Anthropic = _FakeAnthropic
    monkeypatch.setitem(sys.modules, "anthropic", fake_module)
    import instruments.anthropic as anthropic_module

    importlib.reload(anthropic_module)
    importlib.reload(sys.modules["instruments"])
    return fake_module


def _basic_messages():
    return [
        {"role": "system", "content": "Stay cool"},
        {"role": "user", "content": "Yo"},
    ]


def test_anthropic_matches_and_sends(monkeypatch):
    from instruments.anthropic import AnthropicInstrument

    instrument = AnthropicInstrument(url="https://api.anthropic.com", model="claude-3-haiku", api_key="sk-test")
    response = instrument.send_chat(_basic_messages(), stream=False)

    assert response.text == "hello from claude"


def test_anthropic_streaming(monkeypatch):
    from instruments.anthropic import AnthropicInstrument

    chunks: list[str] = []
    instrument = AnthropicInstrument(url="https://api.anthropic.com", model="claude-3-sonnet", api_key="sk-test")
    response = instrument.send_chat(_basic_messages(), stream=True, on_chunk=chunks.append)

    assert response.text == "hello from claude"
    assert "".join(chunks) == "hello from claude"


def test_build_instrument_selects_anthropic(monkeypatch):
    instrument, warning = build_instrument(
        url="https://api.anthropic.com/v1/messages",
        model="claude-3-opus-20240229",
        api_key="sk-test",
    )
    assert warning is None
    assert instrument is not None
    assert instrument.name == "anthropic"

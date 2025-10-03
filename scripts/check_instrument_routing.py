#!/usr/bin/env python3
"""Self-test harness for Central instrument routing."""

from __future__ import annotations

import sys
import types
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "core"))

from central.core.client import ChatClient
from instruments.openai import OpenAIInstrument


class _StubInstrument:
    name = "openai-stub"

    def __init__(self) -> None:
        self.calls: List[Dict[str, Any]] = []

    def send_chat(
        self,
        messages: Iterable[Dict[str, Any]],
        *,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        stream: bool = False,
        on_chunk: Optional[callable] = None,
    ) -> types.SimpleNamespace:
        serialised = [dict(message) for message in messages]
        self.calls.append(
            {
                "messages": serialised,
                "temperature": temperature,
                "max_tokens": max_tokens,
                "stream": stream,
            }
        )
        if stream and on_chunk:
            on_chunk("stub-stream")
        return types.SimpleNamespace(text="stub-response")


class _FakeTransport:
    def __init__(self, url: str) -> None:
        self.url = url
        self.api_key = "sk-test"
        self.sent: List[Dict[str, Any]] = []

    def send(
        self,
        payload: Dict[str, Any],
        *,
        stream: bool = False,
        on_chunk: Optional[callable] = None,
    ) -> tuple[str, Dict[str, Any]]:
        self.sent.append({"payload": payload, "stream": stream})
        if stream and on_chunk:
            on_chunk("transport-stream")
            return "transport-stream", {}
        return "transport-response", {}


def _check_chatclient_instrument_usage() -> None:
    instrument = _StubInstrument()
    transport = _FakeTransport("https://api.openai.com/v1/chat/completions")

    def fake_build_instrument(**_: Any) -> tuple[_StubInstrument, Optional[str]]:
        return instrument, None

    import central.core.client as client_module

    original_builder = getattr(client_module, "_build_instrument", None)
    client_module._build_instrument = fake_build_instrument
    try:
        client = ChatClient(
            url=transport.url,
            model="gpt-4o-mini",
            api_key="sk-test",
            transport=transport,
            stream=True,
        )
        captured: List[str] = []
        reply = client.one_turn("Hello instrument", on_delta=captured.append)
        assert reply == "stub-response"
        assert captured and captured[0]
        assert transport.sent == []
        assert instrument.calls and instrument.calls[0]["messages"][-1]["content"] == "Hello instrument"
    finally:
        client_module._build_instrument = original_builder


def _check_chatclient_openai_rest_payload() -> None:
    transport = _FakeTransport("https://api.openai.com/v1/chat/completions")

    def fake_build_instrument(**_: Any) -> tuple[None, None]:
        return None, None

    import central.core.client as client_module

    original_builder = getattr(client_module, "_build_instrument", None)
    client_module._build_instrument = fake_build_instrument
    try:
        client = ChatClient(
            url=transport.url,
            model="gpt-4o-mini",
            api_key="sk-test",
            transport=transport,
            stream=True,
            max_tokens=77,
        )
        captured: List[str] = []
        reply = client.one_turn("Hello REST", on_delta=captured.append)
        assert reply
        assert captured and captured[0]
        assert transport.sent, "Transport should be exercised"
        payload = transport.sent[0]["payload"]
        assert "modalities" not in payload
        assert "response_format" not in payload
        assert "stream_options" not in payload
        assert payload.get("max_completion_tokens") is None
        assert payload.get("max_tokens") == 77
        messages = payload.get("messages")
        assert isinstance(messages, list)
        assert messages[-1]["content"][0]["text"] == "Hello REST"
    finally:
        client_module._build_instrument = original_builder


def _check_chatclient_ollama_payload() -> None:
    transport = _FakeTransport("http://127.0.0.1:11434/api/generate")

    def fake_build_instrument(**_: Any) -> tuple[None, None]:
        return None, None

    import central.core.client as client_module

    original_builder = getattr(client_module, "_build_instrument", None)
    client_module._build_instrument = fake_build_instrument
    try:
        client = ChatClient(
            url=transport.url,
            model="qwen/qwen3-1.7b",
            transport=transport,
            stream=False,
        )
        reply = client.one_turn("Hello Ollama")
        assert reply == "transport-response"
        assert transport.sent
        payload = transport.sent[0]["payload"]
        assert payload["model"] == "qwen/qwen3-1.7b"
        assert payload["stream"] is False
        messages = payload.get("messages")
        assert isinstance(messages, list)
        assert messages[-1]["content"] == "Hello Ollama"
    finally:
        client_module._build_instrument = original_builder


class _FakeChatCompletions:
    def create(self, **kwargs: Any):
        if kwargs.get("stream"):
            chunk = types.SimpleNamespace(
                choices=[types.SimpleNamespace(delta=types.SimpleNamespace(content="chat-delta"))]
            )
            return [chunk]
        choice = types.SimpleNamespace(message=types.SimpleNamespace(content="chat-complete"))
        return types.SimpleNamespace(choices=[choice])


class _FakeResponses:
    def __init__(self) -> None:
        self.last_create_kwargs: Optional[Dict[str, Any]] = None
        self.last_stream_kwargs: Optional[Dict[str, Any]] = None

    def create(self, **kwargs: Any):
        self.last_create_kwargs = dict(kwargs)
        return types.SimpleNamespace(output_text="responses-complete")

    def stream(self, **kwargs: Any):
        self.last_stream_kwargs = dict(kwargs)
        class _Stream:
            def __enter__(self_inner):
                return self_inner

            def __exit__(self_inner, exc_type, exc, tb):
                return False

            def __iter__(self_inner):
                yield types.SimpleNamespace(type="response.output_text.delta", delta="resp-delta")

            def get_final_response(self_inner):
                return types.SimpleNamespace(output_text="responses-stream-complete")

        return _Stream()


def _fake_openai_module() -> types.ModuleType:
    class FakeOpenAI:
        def __init__(self, api_key: str) -> None:
            self.api_key = api_key
            self.chat = types.SimpleNamespace(completions=_FakeChatCompletions())
            self.responses = _FakeResponses()

    module = types.ModuleType("openai")
    module.OpenAI = FakeOpenAI
    return module


def _check_openai_instrument_with_fake_sdk() -> None:
    previous = sys.modules.get("openai")
    sys.modules["openai"] = _fake_openai_module()
    try:
        instrument = OpenAIInstrument(
            url="https://api.openai.com/v1/chat/completions",
            model="gpt-3.5-turbo",
            api_key="sk-test",
        )
        resp = instrument.send_chat([{ "role": "user", "content": "hi" }])
        assert resp.text == "chat-complete"

        chunks: List[str] = []
        resp_stream = instrument.send_chat(
            [{"role": "user", "content": "hi" }],
            stream=True,
            on_chunk=chunks.append,
        )
        assert chunks == ["chat-delta"]
        assert resp_stream.text == "chat-delta"

        responses_instrument = OpenAIInstrument(
            url="https://api.openai.com/v1/chat/completions",
            model="gpt-4o",
            api_key="sk-test",
        )
        resp2 = responses_instrument.send_chat(
            [{ "role": "user", "content": "hi" }],
            temperature=0.5,
        )
        assert resp2.text == "responses-complete"
        create_kwargs = responses_instrument._client.responses.last_create_kwargs
        assert create_kwargs is not None
        assert create_kwargs["input"][0]["content"][0]["type"] == "input_text"
        assert "temperature" in create_kwargs

        resp2_stream_chunks: List[str] = []
        resp2_stream = responses_instrument.send_chat(
            [{"role": "user", "content": "hi" }],
            stream=True,
            temperature=0.5,
            on_chunk=resp2_stream_chunks.append,
        )
        assert resp2_stream_chunks == ["resp-delta"]
        assert resp2_stream.text in {"resp-delta", "responses-stream-complete"}
        stream_kwargs = responses_instrument._client.responses.last_stream_kwargs
        assert stream_kwargs is not None
        assert stream_kwargs["input"][0]["content"][0]["type"] == "input_text"
        assert "temperature" in stream_kwargs

        gpt5_instrument = OpenAIInstrument(
            url="https://api.openai.com/v1/chat/completions",
            model="gpt-5.0-preview",
            api_key="sk-test",
        )
        gpt5_instrument.send_chat([{ "role": "user", "content": "hi" }], temperature=0.5)
        gpt5_kwargs = gpt5_instrument._client.responses.last_create_kwargs
        assert gpt5_kwargs is not None
        assert "temperature" not in gpt5_kwargs
    finally:
        if previous is not None:
            sys.modules["openai"] = previous
        else:
            del sys.modules["openai"]


def main() -> None:
    _check_chatclient_instrument_usage()
    _check_chatclient_openai_rest_payload()
    _check_chatclient_ollama_payload()
    _check_openai_instrument_with_fake_sdk()
    print("Instrument routing checks passed.")


if __name__ == "__main__":
    main()

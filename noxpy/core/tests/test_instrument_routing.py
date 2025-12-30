from __future__ import annotations

import types
import sys
from typing import Any, Dict, Iterable, List, Optional

import pytest

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


class _FakeChatCompletions:
    def create(self, **kwargs: Any):
        if kwargs.get("stream"):
            chunk = types.SimpleNamespace(
                choices=[types.SimpleNamespace(delta=types.SimpleNamespace(content="chat-delta"))]
            )
            return [chunk]
        choice = types.SimpleNamespace(message=types.SimpleNamespace(content="chat-complete"))
        return types.SimpleNamespace(choices=[choice])


@pytest.mark.parametrize("stream", [False, True])
def test_chatclient_prefers_instrument_for_openai(monkeypatch, stream: bool) -> None:
    instrument = _StubInstrument()
    transport = _FakeTransport("https://api.openai.com/v1/chat/completions")

    def fake_build_instrument(**_: Any) -> tuple[_StubInstrument, Optional[str]]:
        return instrument, None

    monkeypatch.setattr("central.core.client._build_instrument", fake_build_instrument)

    captured: List[str] = []
    client = ChatClient(
        url=transport.url,
        model="gpt-4o-mini",
        api_key="sk-test",
        transport=transport,
        stream=stream,
    )
    reply = client.one_turn("Hello instrument", on_delta=captured.append if stream else None)

    assert reply == "stub-response"
    assert instrument.calls, "Instrument should receive the chat request"
    assert transport.sent == [], "Transport should be bypassed when instrument is present"
    if stream:
        assert captured == ["stub-stream"], "Streaming chunks should flow from instrument"


def test_chatclient_openai_rest_payload(monkeypatch) -> None:
    transport = _FakeTransport("https://api.openai.com/v1/chat/completions")

    def fake_build_instrument(**_: Any) -> tuple[None, None]:
        return None, None

    monkeypatch.setattr("central.core.client._build_instrument", fake_build_instrument)

    captured: List[str] = []
    client = ChatClient(
        url=transport.url,
        model="gpt-4o-mini",
        api_key="sk-test",
        transport=transport,
        stream=True,
        max_tokens=77,
    )
    reply = client.one_turn("Hello REST", on_delta=captured.append)

    assert reply == "transport-stream"
    assert captured == ["transport-stream"]
    assert len(transport.sent) == 1
    payload = transport.sent[0]["payload"]
    assert "modalities" not in payload
    assert "response_format" not in payload
    assert "stream_options" not in payload
    assert payload.get("max_completion_tokens") is None
    assert payload.get("max_tokens") == 77
    assert payload.get("model") == "gpt-4o-mini"
    assert payload.get("stream") is True
    assert "prompt" not in payload
    messages = payload.get("messages")
    assert isinstance(messages, list) and messages
    assert messages[-1]["role"] == "user"
    assert messages[-1]["content"] == "Hello REST"


def test_chatclient_ollama_payload_passthrough(monkeypatch) -> None:
    transport = _FakeTransport("http://127.0.0.1:11434/api/generate")

    def fake_build_instrument(**_: Any) -> tuple[None, None]:
        return None, None

    monkeypatch.setattr("central.core.client._build_instrument", fake_build_instrument)

    client = ChatClient(
        url=transport.url,
        model="qwen/qwen3-1.7b",
        transport=transport,
        stream=False,
    )
    reply = client.one_turn("Hello Ollama")

    assert reply == "transport-response"
    assert len(transport.sent) == 1
    payload = transport.sent[0]["payload"]
    assert payload["model"] == "qwen/qwen3-1.7b"
    assert payload["stream"] is False
    prompt = payload.get("prompt")
    assert isinstance(prompt, str) and "Hello Ollama" in prompt
    messages = payload.get("messages")
    assert isinstance(messages, list) and messages[-1]["content"] == "Hello Ollama"


def test_openai_instrument_response_payload_types(monkeypatch) -> None:
    class FakeResponses:
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

    class FakeOpenAI:
        def __init__(self, api_key: str) -> None:
            self.api_key = api_key
            self.chat = types.SimpleNamespace(completions=_FakeChatCompletions())
            self.responses = FakeResponses()

    fake_module = types.ModuleType("openai")
    fake_module.OpenAI = FakeOpenAI

    monkeypatch.setitem(sys.modules, "openai", fake_module)

    instrument = OpenAIInstrument(
        url="https://api.openai.com/v1/responses",
        model="gpt-4o",
        api_key="sk-test",
    )

    instrument.send_chat([{"role": "user", "content": "hi"}], temperature=0.5)
    create_kwargs = instrument._client.responses.last_create_kwargs
    assert create_kwargs is not None
    assert create_kwargs["input"][0]["content"][0]["type"] == "input_text"
    assert "temperature" in create_kwargs

    chunks: List[str] = []
    instrument.send_chat(
        [{"role": "user", "content": "hi"}],
        stream=True,
        temperature=0.5,
        on_chunk=chunks.append,
    )
    stream_kwargs = instrument._client.responses.last_stream_kwargs
    assert stream_kwargs is not None
    assert stream_kwargs["input"][0]["content"][0]["type"] == "input_text"
    assert chunks == ["resp-delta"]
    assert "temperature" in stream_kwargs

    gpt5_instrument = OpenAIInstrument(
        url="https://api.openai.com/v1/responses",
        model="gpt-5.0-preview",
        api_key="sk-test",
    )

    gpt5_instrument.send_chat([{"role": "user", "content": "hi"}], temperature=0.5)
    gpt5_kwargs = gpt5_instrument._client.responses.last_create_kwargs
    assert gpt5_kwargs is not None
    assert "temperature" not in gpt5_kwargs

    monkeypatch.delitem(sys.modules, "openai")

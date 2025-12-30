from __future__ import annotations

import json
from typing import List, Optional
from urllib.error import URLError

import pytest

from central.transport import LLMTransport


class _Headers:
    def get_content_charset(self) -> str:
        return "utf-8"


class _Response:
    def __init__(self, *, body: str = "", lines: Optional[List[str]] = None) -> None:
        self.headers = _Headers()
        self._body = body.encode("utf-8")
        self._lines = [(line.encode("utf-8")) for line in (lines or [])]
        self._index = 0

    def read(self) -> bytes:
        return self._body

    def readline(self) -> bytes:
        if self._index >= len(self._lines):
            return b""
        line = self._lines[self._index]
        self._index += 1
        return line

    def __enter__(self) -> "_Response":
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        return False


def test_send_supports_ollama_chat_non_streaming(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_urlopen(req):  # noqa: ARG001 - signature matches urllib
        payload = {"message": {"role": "assistant", "content": "hi"}, "done": True}
        return _Response(body=json.dumps(payload))

    monkeypatch.setattr("central.transport.urlopen", fake_urlopen)
    transport = LLMTransport("http://127.0.0.1:11434/api/chat")
    text, meta = transport.send(
        {"model": "test", "messages": [{"role": "user", "content": "yo"}], "stream": False, "options": {}},
        stream=False,
    )
    assert text == "hi"
    assert meta and meta.get("done") is True


def test_send_supports_ollama_chat_streaming(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_urlopen(req):  # noqa: ARG001 - signature matches urllib
        lines = [
            json.dumps({"message": {"content": "Hel"}, "done": False}) + "\n",
            json.dumps({"message": {"content": "lo"}, "done": False}) + "\n",
            json.dumps({"message": {"content": ""}, "done": True}) + "\n",
        ]
        return _Response(lines=lines)

    chunks: List[str] = []

    def on_chunk(piece: str) -> None:
        chunks.append(piece)

    monkeypatch.setattr("central.transport.urlopen", fake_urlopen)
    transport = LLMTransport("http://127.0.0.1:11434/api/chat")
    text, meta = transport.send(
        {"model": "test", "messages": [{"role": "user", "content": "yo"}], "stream": True, "options": {}},
        stream=True,
        on_chunk=on_chunk,
    )
    assert text == "Hello"
    assert "".join(chunks) == "Hello"
    assert meta is None


def test_ollama_chat_error_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_urlopen(req):  # noqa: ARG001 - signature matches urllib
        return _Response(body=json.dumps({"error": "boom"}))

    monkeypatch.setattr("central.transport.urlopen", fake_urlopen)
    transport = LLMTransport("http://127.0.0.1:11434/api/chat")
    with pytest.raises(URLError, match="boom"):
        transport.send({"model": "test", "messages": [{"role": "user", "content": "yo"}], "options": {}}, stream=False)


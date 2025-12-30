from __future__ import annotations

from typing import List

from central.core import ChatClient, _extract_public_segments, strip_chain_of_thought
from central.transport import LLMTransport


def test_strip_chain_of_thought_removes_block() -> None:
    text = "<think>internal</think> Visible answer."
    assert strip_chain_of_thought(text) == "Visible answer."


def test_strip_chain_of_thought_empty_when_only_think() -> None:
    assert strip_chain_of_thought("<think>internal</think>") == ""


def test_extract_public_segments_handles_partial_open() -> None:
    public, remainder = _extract_public_segments("Hello <think>secret")
    assert public == "Hello "
    assert remainder == "<think>secret"


def test_extract_public_segments_multiple_blocks() -> None:
    buf = "A<think>x</think>B<think>y</think>C"
    public, remainder = _extract_public_segments(buf)
    assert public == "ABC"
    assert remainder == ""


class _StreamingStub(LLMTransport):
    def __init__(self) -> None:
        super().__init__("http://example.com")

    def send(self, payload, *, stream=False, on_chunk=None):  # type: ignore[override]
        if stream and on_chunk:
            on_chunk("<think>hidden</think>")
            on_chunk("Visible output")
        return "<think>hidden</think>Visible output", None


def test_streaming_delta_strips_reasoning() -> None:
    stub = _StreamingStub()
    deltas: List[str] = []

    client = ChatClient(stream=True, enable_logging=False, transport=stub)
    reply = client.one_turn("hello", on_delta=lambda chunk: deltas.append(chunk))

    assert reply == "Visible output"
    assert deltas == ["Visible output"]

from __future__ import annotations

import pytest

from central.core import ChatClient
from central.transport import LLMTransport


class _StubTransport(LLMTransport):
    def __init__(self) -> None:
        super().__init__("http://example.com")
        self.messages: list[dict[str, object]] | None = None

    def send(self, payload, *, stream=False, on_chunk=None):  # type: ignore[override]
        self.messages = payload["messages"]
        return "ok", {}


@pytest.mark.usefixtures("tmp_path")
def test_instrument_result_injects_system_prompt():
    stub = _StubTransport()

    client = ChatClient(stream=False, enable_logging=False, transport=stub)
    client.process_instrument_result("instrument text")

    msgs = stub.messages
    assert msgs is not None
    assert msgs[-2]["role"] == "system"
    assert "Do you want the explanation" in msgs[-2]["content"]

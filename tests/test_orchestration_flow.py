"""Unit and integration coverage for Nox instrument orchestration."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CORE_ROOT = PROJECT_ROOT / "core"
if str(CORE_ROOT) not in sys.path:
    sys.path.insert(0, str(CORE_ROOT))
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from central.connector import NoxConnector
from central.core.client import ChatClient
from central.transport import LLMTransport
from instruments.base import BaseInstrument, InstrumentResponse


class _QueueTransport(LLMTransport):
    """Deterministic transport that replays canned responses for tests."""

    def __init__(self, replies: Iterable[str]) -> None:
        super().__init__("https://api.test/v1/chat/completions")
        self._replies: List[str] = list(replies)
        self.payloads: List[Dict[str, Any]] = []

    def send(
        self,
        payload: Dict[str, Any],
        *,
        stream: bool = False,
        on_chunk=None,
    ) -> Tuple[Optional[str], Optional[Dict[str, Any]]]:
        self.payloads.append(payload)
        if not self._replies:
            raise AssertionError("No more canned replies available in _QueueTransport")
        return self._replies.pop(0), None


class _StubConnector(NoxConnector):
    """Connector that always returns a provided transport instance."""

    def __init__(self, transport: LLMTransport) -> None:
        self._transport = transport

    def connect(self) -> LLMTransport:  # type: ignore[override]
        return self._transport


class _StubInstrument(BaseInstrument):
    """Minimal instrument for isolating ChatClient instrumentation flow."""

    name = "stub"

    def __init__(self, *, url: Optional[str], model: Optional[str], api_key: Optional[str]) -> None:
        super().__init__(url=url, model=model, api_key=api_key)
        self.calls: List[List[Dict[str, Any]]] = []

    def send_chat(
        self,
        messages: Iterable[Dict[str, Any]],
        *,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        stream: bool = False,
        on_chunk=None,
    ) -> InstrumentResponse:
        payload = list(messages)
        self.calls.append(payload)
        return InstrumentResponse(text="instrument-output")


def test_wants_instrument_detection() -> None:
    assert not ChatClient.wants_instrument("Regular answer without control tags")
    assert ChatClient.wants_instrument("[INSTRUMENT QUERY]Do a thing[/INSTRUMENT QUERY]")
    assert ChatClient.wants_instrument("Requires an instrument to proceed; paste response.")


def test_process_instrument_result_roundtrip(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NOCTICS_SKIP_DOTENV", "1")
    transport = _QueueTransport(
        replies=[
            (
                "[INSTRUMENT QUERY]Source data needed[/INSTRUMENT QUERY]\n"
                "Requires an instrument to proceed; paste response."
            ),  # initial turn
            "Final response with instrument context.",  # follow-up after instrument result
        ]
    )
    client = ChatClient(
        url="https://api.openai.com/v1/chat/completions",
        model="gpt-4o-mini",
        api_key="dummy-key",
        stream=False,
        enable_logging=False,
        connector=_StubConnector(transport),
        transport=transport,
    )

    initial = client.one_turn("Please fetch external data.")
    assert isinstance(initial, str)
    assert ChatClient.wants_instrument(initial)

    final = client.process_instrument_result("External summary from instrument.")
    assert final == "Final response with instrument context."

    # Ensure the instrument result was threaded back into the follow-up payload.
    assert transport.payloads[-1]["messages"][-1]["content"].endswith("[/INSTRUMENT RESULT]")


def test_client_uses_registered_instrument(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NOCTICS_SKIP_DOTENV", "1")
    stub = _StubInstrument(url=None, model=None, api_key=None)

    def _build_stub_instrument(*, url: Optional[str], model: Optional[str], api_key: Optional[str]):
        return stub, None

    monkeypatch.setattr("central.core.client._build_instrument", _build_stub_instrument, raising=False)

    transport = _QueueTransport(replies=["ignored-response"])
    client = ChatClient(
        url="https://api.openai.com/v1/chat/completions",
        model="gpt-4o-mini",
        api_key="dummy-key",
        stream=False,
        enable_logging=False,
        connector=_StubConnector(transport),
        transport=transport,
    )

    result = client.one_turn("Use the instrument please.")
    assert result == "instrument-output"
    assert stub.calls, "Instrument should have been invoked"


def test_client_falls_back_when_instrument_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NOCTICS_SKIP_DOTENV", "1")

    class _FaultyInstrument(BaseInstrument):
        name = "faulty"

        def send_chat(self, *args: Any, **kwargs: Any) -> InstrumentResponse:
            raise RuntimeError("instrument boom")

    def _build_faulty_instrument(*, url: Optional[str], model: Optional[str], api_key: Optional[str]):
        return _FaultyInstrument(url=url, model=model, api_key=api_key), None

    monkeypatch.setattr("central.core.client._build_instrument", _build_faulty_instrument, raising=False)

    transport = _QueueTransport(replies=["fallback-response"])
    client = ChatClient(
        url="https://api.openai.com/v1/chat/completions",
        model="gpt-4o-mini",
        api_key="dummy-key",
        stream=False,
        enable_logging=False,
        connector=_StubConnector(transport),
        transport=transport,
    )

    result = client.one_turn("Should fallback to transport")
    assert result == "fallback-response"
    assert client.instrument_warning and "instrument boom" in client.instrument_warning


def test_orchestrate_eval_simulate(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NO_NETWORK", "1")
    monkeypatch.setenv("NOCTICS_SKIP_DOTENV", "1")
    env = os.environ.copy()
    env["PYTHONPATH"] = os.pathsep.join(
        [
            str(Path.cwd()),
            str(Path.cwd() / "core"),
        ]
    )
    out_path = tmp_path / "orch.json"
    proc = subprocess.run(
        [
            sys.executable,
            "scripts/orchestrate_eval.py",
            "--simulate",
            "--out",
            str(out_path),
        ],
        cwd=str(Path.cwd()),
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )
    assert out_path.exists(), proc.stdout + proc.stderr
    payload = json.loads(out_path.read_text(encoding="utf-8"))
    assert payload["cases"], "Simulated orchestration should produce case results"
    assert any(case["wants_instrument"] for case in payload["cases"])

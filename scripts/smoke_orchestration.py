#!/usr/bin/env python3
from __future__ import annotations

# ruff: noqa: E402

import sys
from typing import Any, Dict, Optional, Tuple

sys.path.insert(0, str((__file__)))  # no-op to placate some linters

from pathlib import Path

CORE_ROOT = Path(__file__).resolve().parents[1] / "core"
if str(CORE_ROOT) not in sys.path:
    sys.path.insert(0, str(CORE_ROOT))

from central.core import ChatClient, clean_public_reply  # type: ignore
from central.transport import LLMTransport  # type: ignore


def assert_eq(a, b, msg: str = "") -> None:
    if a != b:
        raise AssertionError(msg or f"Expected {b!r}, got {a!r}")


def test_clean_public_reply_instrument_unwrap() -> None:
    src = """
    [INSTRUMENT RESULT]
    Final output
    [/INSTRUMENT RESULT]
    """.strip()
    out = clean_public_reply(src)
    assert_eq(out, "Final output", "INSTRUMENT RESULT should be unwrapped")


def test_clean_public_reply_instrument_aux_strip() -> None:
    src = "Before [INSTRUMENT QUERY]secret[/INSTRUMENT QUERY] After"
    out = clean_public_reply(src)
    if "secret" in out:
        raise AssertionError("Instrument QUERY block should be stripped")


def test_clean_public_reply_preserves_code_fences() -> None:
    src = (
        "Here is code:\n"
        "```python\n"
        "print('hi')\n"
        "```\n"
        "Done."
    )
    out = clean_public_reply(src)
    if out.count("```") != 2 or "print('hi')" not in out:
        raise AssertionError("Triple backticks should be preserved")


class _StubTransport(LLMTransport):
    def __init__(self) -> None:
        super().__init__("http://127.0.0.1:11434/api/generate")

    def send(self, payload: Dict[str, Any], *, stream: bool = False, on_chunk=None) -> Tuple[Optional[str], Optional[Dict[str, Any]]]:  # type: ignore[override]
        # Simulate a model reply that wraps instrument results; ensure client cleans it
        reply = "[INSTRUMENT RESULT]Answer[/INSTRUMENT RESULT]"
        if stream and on_chunk:
            on_chunk("[INSTRUMENT RESULT]")
            on_chunk("Answer")
            on_chunk("[/INSTRUMENT RESULT]")
        return reply, None


def test_client_process_instrument_result_path() -> None:
    stub = _StubTransport()
    client = ChatClient(stream=False, enable_logging=False, transport=stub)
    out = client.process_instrument_result("instrument text")
    assert_eq(out, "Answer")


def main() -> int:
    tests = [
        test_clean_public_reply_instrument_unwrap,
        test_clean_public_reply_instrument_aux_strip,
        test_clean_public_reply_preserves_code_fences,
        test_client_process_instrument_result_path,
    ]
    for fn in tests:
        fn()
    print("smoke_orchestration: OK (", len(tests), "checks)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

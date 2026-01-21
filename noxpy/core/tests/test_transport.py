from __future__ import annotations

import json

from central.transport import _extract_sse_piece


def test_extract_sse_piece_delta_content() -> None:
    event = {
        "choices": [
            {
                "delta": {
                    "content": "Hello",
                }
            }
        ]
    }
    assert _extract_sse_piece(json.dumps(event)) == "Hello"


def test_extract_sse_piece_uses_message_fallback() -> None:
    event = {
        "choices": [
            {
                "message": {
                    "content": "Hi there",
                }
            }
        ]
    }
    assert _extract_sse_piece(json.dumps(event)) == "Hi there"


def test_extract_sse_piece_handles_plain_text() -> None:
    assert _extract_sse_piece("partial chunk") == "partial chunk"


def test_extract_sse_piece_invalid_json_returns_none() -> None:
    assert _extract_sse_piece("{") is None

from __future__ import annotations

from noxl import compute_title_from_messages


def test_compute_title_skips_instrument_and_limits_words():
    msgs = [
        {"role": "system", "content": "sys"},
        {
            "role": "user",
            "content": "[INSTRUMENT RESULT]\nsome long instrument output\n[/INSTRUMENT RESULT]",
        },
        {
            "role": "user",
            "content": "This is a concise title source that has many words beyond eight",
        },
    ]

    title = compute_title_from_messages(msgs)
    assert title is not None
    # Should take the first meaningful user message, capped to ~8 words
    assert title.split()[:8] == [
        "This",
        "is",
        "a",
        "concise",
        "title",
        "source",
        "that",
        "has",
    ]


def test_compute_title_returns_none_when_no_user():
    msgs = [{"role": "system", "content": "sys"}]
    assert compute_title_from_messages(msgs) is None

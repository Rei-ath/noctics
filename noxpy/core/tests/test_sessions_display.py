from __future__ import annotations

from central.commands.sessions import _pair_messages_for_display


def test_pair_messages_for_display_groups_user_assistant():
    messages = [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": "hello"},
        {"role": "user", "content": "bye"},
        {"role": "assistant", "content": "cya"},
    ]

    pairs = _pair_messages_for_display(messages)
    assert len(pairs) == 2
    assert pairs[0][0]["content"] == "hi"
    assert pairs[0][1]["content"] == "hello"
    assert pairs[1][0]["content"] == "bye"
    assert pairs[1][1]["content"] == "cya"

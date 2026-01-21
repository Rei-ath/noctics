from __future__ import annotations

from noctics_cli.tui import format_messages


def test_format_messages_wraps_and_limits():
    messages = [
        {"role": "user", "content": "hello world"},
        {"role": "assistant", "content": "this is a very long message that should wrap nicely across multiple lines"},
    ]
    lines = format_messages(messages, width=20, max_lines=5)
    assert lines
    assert lines[0].startswith("USER:")
    assert any(line.startswith("ASSISTANT:") for line in lines)
    assert len(lines) <= 5


def test_format_messages_handles_structured_content():
    messages = [
        {"role": "assistant", "content": [{"type": "text", "text": "first"}, {"type": "text", "text": "second"}]},
    ]
    lines = format_messages(messages, width=40, max_lines=3)
    assert "first" in " ".join(lines)
    assert "second" in " ".join(lines)

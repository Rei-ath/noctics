from __future__ import annotations

from central.commands.instrument import extract_instrument_query, anonymize_for_instrument


def test_extract_instrument_query_basic():
    text = (
        "Some intro...\n"
        "[INSTRUMENT QUERY]\n"
        "Please summarize the following input from the user: foo bar.\n"
        "[/INSTRUMENT QUERY]\n"
        "Other text"
    )
    q = extract_instrument_query(text)
    assert q is not None
    assert q.startswith("Please summarize")


def test_anonymize_for_instrument_redacts_pii_and_names(monkeypatch):
    monkeypatch.setenv("NOX_REDACT_NAMES", "Alice")
    src = (
        "From: Alice <alice@example.com>\n"
        "Call me at +1-415-555-1212, IP 192.168.0.1.\n"
        "Card: 4111 1111 1111 1111\n"
    )
    out = anonymize_for_instrument(src, user_name="Jang")
    assert "[REDACTED:EMAIL]" in out
    assert "[REDACTED:PHONE]" in out
    assert "[REDACTED:IP]" in out
    assert "[REDACTED:CARD]" in out
    assert "Alice" not in out

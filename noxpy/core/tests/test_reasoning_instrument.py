from __future__ import annotations

from central.core import clean_public_reply


def test_clean_public_reply_unwraps_instrument_result() -> None:
    src = """
    [INSTRUMENT RESULT]
    Final output
    [/INSTRUMENT RESULT]
    """.strip()
    assert clean_public_reply(src) == "Final output"


def test_clean_public_reply_strips_instrument_aux_blocks() -> None:
    src = "Before [INSTRUMENT QUERY]secret[/INSTRUMENT QUERY] After"
    out = clean_public_reply(src)
    assert "secret" not in out
    assert out.replace("  ", " ").strip() in {"Before After", "Before  After"}


def test_clean_public_reply_preserves_code_fences() -> None:
    src = (
        "Here is code:\n"
        "```python\n"
        "print('hi')\n"
        "```\n"
        "Done."
    )
    out = clean_public_reply(src)
    assert "```python" in out and out.count("```") == 2
    assert "print('hi')" in out


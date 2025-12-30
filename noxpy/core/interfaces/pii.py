"""
Simple PII redaction utilities (no external deps).

Goal: keep it tiny and readable. Use conservative regexes to redact
common high-risk items: email, phone, credit card numbers, IPv4.
"""

from __future__ import annotations

import re

# Precompile minimal regexes
EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
PHONE_RE = re.compile(r"\b(?:\+?\d{1,3}[\s.-]?)?(?:\(\d{2,4}\)[\s.-]?|\d{2,4}[\s.-]?)?\d{3,4}[\s.-]?\d{3,4}\b")
CARD_RE = re.compile(r"\b(?:\d[ -]?){13,19}\b")
IPV4_RE = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")


def _luhn_like_ok(s: str) -> bool:
    digits = [int(c) for c in s if c.isdigit()]
    if len(digits) < 13 or len(digits) > 19:
        return False
    # Lightweight Luhn check to reduce false positives
    total = 0
    parity = len(digits) % 2
    for i, d in enumerate(digits):
        if i % 2 == parity:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return total % 10 == 0


def _redact_card(match: re.Match[str]) -> str:
    raw = match.group(0)
    digits = ''.join(ch for ch in raw if ch.isdigit())
    return "[REDACTED:CARD]" if _luhn_like_ok(digits) else raw


def sanitize(text: str) -> str:
    """Redact common PII tokens from text.

    Replacements:
      - EMAIL -> [REDACTED:EMAIL]
      - PHONE -> [REDACTED:PHONE]
      - CREDIT CARD -> [REDACTED:CARD] (only if passes a Luhn-like check)
      - IPv4 -> [REDACTED:IP]
    """
    text = EMAIL_RE.sub("[REDACTED:EMAIL]", text)
    text = CARD_RE.sub(_redact_card, text)
    text = IPV4_RE.sub("[REDACTED:IP]", text)
    text = PHONE_RE.sub("[REDACTED:PHONE]", text)
    return text

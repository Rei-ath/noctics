from __future__ import annotations

import re
from typing import List, Optional

from central.colors import color
from central.config import get_runtime_config
from interfaces.pii import sanitize as pii_sanitize
from nox_env import get_env

# -----------------------------
# Instrument query anonymization
# -----------------------------

_INSTRUMENT_QUERY_RE = re.compile(r"\[INSTRUMENT\s+QUERY\](.*?)\[/INSTRUMENT\s+QUERY\]", re.IGNORECASE | re.DOTALL)


def extract_instrument_query(text: str) -> Optional[str]:
    """Extract the content of a [INSTRUMENT QUERY]... block.

    Returns None if no block is present.
    """
    if not text:
        return None
    m = _INSTRUMENT_QUERY_RE.search(text)
    if not m:
        return None
    return m.group(1).strip()


def anonymize_for_instrument(text: str, *, user_name: Optional[str] = None) -> str:
    """Sanitize an instrument query to avoid leaking user identity.

    - Applies PII redaction (emails, phones, cards via Luhn-like, IPv4).
    - Optionally redacts configured names from env `NOX_REDACT_NAMES` (comma-separated).
    - Optionally redacts the interactive prompt label if provided via `user_name`.
    """
    # Base PII sanitization
    out = pii_sanitize(text)

    # Redact interactive label (avoid over-redacting the generic "You")
    label = (user_name or "").strip()
    if label and label.lower() not in {"you", "user"}:
        out = re.sub(re.escape(label), "[REDACTED:NAME]", out, flags=re.IGNORECASE)

    # Redact additional names from env
    extra = get_env("NOX_REDACT_NAMES") or ""
    for raw in [s.strip() for s in extra.split(",") if s.strip()]:
        out = re.sub(re.escape(raw), "[REDACTED:NAME]", out, flags=re.IGNORECASE)

    return out


def print_sanitized_instrument_query(block: str, *, user_name: Optional[str]) -> None:
    """Utility to display a sanitized instrument query block."""
    print()
    print(color("Instrument Query (sanitized):", fg="blue", bold=True))
    print(anonymize_for_instrument(block, user_name=user_name))


# -----------------------------
# Instrument selection utilities
# -----------------------------

def get_instrument_candidates() -> List[str]:
    """Return a list of instrument names from env, config, or defaults."""

    env_instruments = [
        s.strip()
        for s in (get_env("NOX_INSTRUMENTS") or "").split(",")
        if s.strip()
    ]
    if env_instruments:
        return env_instruments

    cfg = get_runtime_config().instrument
    config_instruments = cfg.roster
    if config_instruments:
        return config_instruments

    # Popular LLM/provider names as convenient defaults; override via env/config
    return [
        "claude",      # Anthropic
        "gpt-4o",      # OpenAI
        "gpt-4",       # OpenAI
        "grok",        # xAI
        "gemini",      # Google
        "llama",       # Meta
        "mistral",     # Mistral AI
        "cohere",      # Cohere
        "deepseek",    # DeepSeek
    ]


def instrument_automation_enabled() -> bool:
    """Return True if automatic instrument stitching is available."""

    value = (get_env("NOX_INSTRUMENT_AUTOMATION") or "").strip()
    if value:
        return value.lower() in {"1", "true", "on", "yes"}
    return get_runtime_config().instrument.automation


def describe_instrument_status() -> str:
    """Return a concise description of instrument availability."""

    instruments = get_instrument_candidates()
    roster = ", ".join(instruments) if instruments else "none configured"
    if instrument_automation_enabled():
        return f"Automation enabled. Available instruments: {roster}."
    return (
        "Automation disabled. Available instrument labels: "
        f"{roster}. Install the full Noctics suite (with the router service) to enable automatic instrument routing."
    )


def choose_instrument_interactively(current: Optional[str] = None) -> Optional[str]:
    """Prompt the user to choose an instrument if none is set.

    - Returns the chosen instrument name (or None if skipped).
    - Accepts a number (index) or a free-form name.
    - If stdin is not interactive, returns current unchanged.
    """
    try:
        import sys

        if not sys.stdin.isatty():
            return current
    except Exception:
        return current

    candidates = get_instrument_candidates()
    print(color("Choose an instrument:", fg="yellow", bold=True))
    print(color("(press Enter to skip; type a number or name)", fg="yellow"))
    for i, h in enumerate(candidates, 1):
        print(f"  {i}. {h}")
    print(color("instrument>", fg="blue", bold=True) + " ", end="", flush=True)
    try:
        choice = input().strip()
    except EOFError:
        return current
    if not choice:
        return current
    if choice.isdigit():
        idx = int(choice)
        if 1 <= idx <= len(candidates):
            return candidates[idx - 1]
        return current
    return choice

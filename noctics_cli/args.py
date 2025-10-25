"""Argument parsing utilities for the Central CLI."""

from __future__ import annotations

import argparse
import os
from typing import List

DEFAULT_URL = "http://127.0.0.1:11434/api/chat"

__all__ = ["DEFAULT_URL", "parse_args"]


def parse_args(argv: List[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Interactive Chat Completions CLI",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  python main.py --stream\n"
            "  python main.py --instrument claude --stream\n"
            "  python main.py --user 'Explain X' --stream\n"
            "  python main.py --messages msgs.json --stream\n"
            "  python main.py --sessions-ls\n"
            "  python main.py --sessions-load session-20250913-234409\n"
            "  python main.py --sessions-rename session-20250914-010016 'My Title'\n"
        ),
    )
    parser.add_argument(
        "-U", "--url",
        default=os.getenv("CENTRAL_LLM_URL", DEFAULT_URL),
        help="Endpoint URL (env CENTRAL_LLM_URL)",
    )
    parser.add_argument(
        "-M", "--model",
        default=os.getenv("CENTRAL_LLM_MODEL", "centi-nox"),
        help="Model name (env CENTRAL_LLM_MODEL)",
    )
    parser.add_argument(
        "-S", "--system",
        default=None,
        help="System message (defaults to memory/system_prompt.md; ignored if --messages is used)",
    )
    parser.add_argument("-u", "--user", default=None, help="Optional initial user message")
    parser.add_argument(
        "-F", "--messages",
        dest="messages_file",
        default=None,
        help="Path to JSON file containing a messages array to send",
    )
    parser.add_argument("-t", "--temperature", type=float, default=0.2, help="Sampling temperature")
    parser.add_argument(
        "-T", "--max-tokens",
        dest="max_tokens",
        type=int,
        default=-1,
        help="Max tokens (-1 for unlimited if supported)",
    )
    parser.add_argument(
        "-s",
        "--stream",
        dest="stream",
        action="store_true",
        default=None,
        help="Enable streaming (SSE)",
    )
    parser.add_argument(
        "--no-stream",
        dest="stream",
        action="store_false",
        help="Disable streaming (skips the interactive prompt)",
    )
    parser.add_argument(
        "-z", "--sanitize",
        action="store_true",
        help="Redact common PII from user text before sending",
    )
    parser.add_argument("-r", "--raw", action="store_true", help="Also print raw JSON in non-streaming mode")
    parser.add_argument(
        "--show-think",
        action="store_true",
        help="Include assistant <think> blocks in console output and session logs.",
    )
    parser.add_argument(
        "-k", "--api-key",
        default=(os.getenv("CENTRAL_LLM_API_KEY") or os.getenv("OPENAI_API_KEY")),
        help="Optional API key for Authorization header (env CENTRAL_LLM_API_KEY | OPENAI_API_KEY)",
    )
    parser.add_argument(
        "-H",
        "--instrument",
        dest="instrument",
        default=None,
        help=(
            "Optional instrument name label used when Central requests an external instrument; "
            "does not skip API calls."
        ),
    )
    parser.add_argument(
        "-L", "--sessions-ls",
        dest="sessions_ls",
        action="store_true",
        help="List saved sessions with titles and exit",
    )
    parser.add_argument(
        "-D", "--sessions-load",
        metavar="ID_OR_PATH",
        default=None,
        help="Load a session's messages before starting chat (by id or path)",
    )
    parser.add_argument(
        "--sessions-show",
        dest="sessions_show",
        default=None,
        help="Display a stored session then exit",
    )
    parser.add_argument(
        "--sessions-rename",
        nargs=2,
        metavar=("IDENT", "TITLE"),
        default=None,
        help="Rename a stored session",
    )
    parser.add_argument(
        "--sessions-merge",
        nargs="+",
        metavar="IDENT",
        default=None,
        help="Merge multiple sessions into one",
    )
    parser.add_argument(
        "--sessions-latest",
        action="store_true",
        help="Show information about the most recent session",
    )
    parser.add_argument(
        "--sessions-archive-early",
        action="store_true",
        help="Archive older sessions and keep the latest",
    )
    parser.add_argument(
        "--sessions-browse",
        action="store_true",
        help="Interactively browse saved sessions",
    )
    parser.add_argument(
        "--user-name",
        dest="user_name",
        default=os.getenv("CENTRAL_USER_NAME", "You"),
        help="Name to display for your prompt label (env CENTRAL_USER_NAME)",
    )
    parser.add_argument(
        "--dev",
        action="store_true",
        help="Run as the project developer (skip user onboarding and log as developer)",
    )
    default_anon = (
        os.getenv("CENTRAL_INSTRUMENT_ANON", "1").lower() not in {"0", "false", "off", "no"}
    )
    parser.add_argument(
        "--anon-instrument",
        dest="anon_instrument",
        action="store_true",
        default=default_anon,
        help="Reserved sanitization toggle for future instrument integration",
    )
    parser.add_argument(
        "--no-anon-instrument",
        dest="anon_instrument",
        action="store_false",
        help="Disable the reserved instrument sanitization toggle",
    )
    parser.add_argument(
        "--version",
        action="store_true",
        help="Print the Central version and exit",
    )
    return parser.parse_args(argv)

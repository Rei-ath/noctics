from __future__ import annotations

from typing import List, Optional

try:
    import readline  # type: ignore
except Exception:  # pragma: no cover
    readline = None  # type: ignore

from noxl import list_sessions
from central.commands.instrument import get_instrument_candidates


def setup_completions() -> None:
    if readline is None:
        return
    try:
        import sys

        if not sys.stdin.isatty():
            return
    except Exception:
        return

    # Canonical, de-duplicated slash commands
    commands = [
        "/help",
        "/reset",
        "/ls",
        "/last",
        "/iam",
        "/instrument",
        "/anon",
        "/load",
        "/title",
        "/rename",
        "/merge",
        "/name",
        "/archive",
        "/show",
        "/browse",
    ]

    instrument_candidates = get_instrument_candidates()

    def session_suggestions() -> List[str]:
        items = list_sessions()
        out: List[str] = []
        out.extend([str(i) for i in range(1, len(items) + 1)])
        out.extend([it.get("id") for it in items if it.get("id")])
        return [s for s in out if s]

    def complete(text: str, state: int) -> Optional[str]:
        try:
            line = readline.get_line_buffer()  # type: ignore[attr-defined]
            beg = readline.get_begidx()  # type: ignore[attr-defined]
        except Exception:
            line, beg = "", 0

        if not line or line.startswith("/") and (" " not in line[:beg]):
            matches = [c for c in commands if c.startswith(text or "")]
            return matches[state] if state < len(matches) else None

        head = line.split(" ", 1)[0]
        arg_region = line[len(head):]
        arg_text = arg_region.lstrip()
        arg_index = 0 if not arg_text or arg_text.endswith(" ") else len(arg_text.split()) - 1

        if head == "/instrument":
            if beg >= len(head) + 1:
                matches = [h for h in instrument_candidates if h.startswith(text or "")]
                return matches[state] if state < len(matches) else None
            return None

        if head in {"/load", "/rename", "/merge", "/show"}:
            if beg >= len(head) + 1 and arg_index == 0:
                candidates = session_suggestions()
                matches = [c for c in candidates if c.startswith(text or "")]
                return matches[state] if state < len(matches) else None
            return None

        return None

    try:
        readline.parse_and_bind("tab: complete")  # type: ignore[attr-defined]
        readline.set_completer(complete)  # type: ignore[attr-defined]
    except Exception:
        pass

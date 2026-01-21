from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

from central.colors import color
import noxl
from interfaces.session_logger import format_session_display_name


_ARCHIVE_AVAILABLE = hasattr(noxl, "archive_early_sessions")
noxl_archive_early_sessions = getattr(noxl, "archive_early_sessions", None)
noxl_list_sessions = noxl.list_sessions
load_session_messages = noxl.load_session_messages
merge_sessions_paths = noxl.merge_sessions_paths
resolve_session = noxl.resolve_session
set_session_title_for = noxl.set_session_title_for


def list_sessions(
    *,
    root: Optional[Path] = None,
    user: Optional[str] = None,
) -> List[Dict[str, object]]:
    """Return session metadata, optionally scoped to a specific root/user."""

    kwargs: Dict[str, object] = {}
    if root is not None:
        kwargs["root"] = root
    if user is not None:
        kwargs["user"] = user
    if not kwargs:
        return noxl_list_sessions()
    return noxl_list_sessions(**kwargs)


def latest_session() -> Optional[Dict[str, object]]:
    items = noxl_list_sessions()
    return items[0] if items else None


def print_latest_session(info: Dict[str, object]) -> None:
    display_name = info.get("display_name") or info.get("id")
    turns = info.get("turns")
    title = info.get("title") or "(untitled)"
    updated = info.get("updated") or color("unknown", fg="yellow")
    print(color("Most recent session:", fg="yellow", bold=True))
    print(f"  {display_name} ({info.get('id')})")
    print(f"  Turns: {turns}")
    print(f"  Title: {title}")
    print(f"  Path: {info.get('path')}")
    print(f"  Last updated: {updated}")


def print_sessions(items: List[Dict[str, object]]) -> None:
    if not items:
        print(color("No sessions found.", fg="yellow"))
        return
    for i, it in enumerate(items, 1):
        ident = it.get("id")
        turns = it.get("turns")
        title = it.get("title") or "(untitled)"
        display_name = it.get("display_name") or ident
        updated = it.get("updated") or "—"
        print(color(f"{i:>2}. {display_name}", fg="cyan", bold=True))
        print(f"     id: {ident}")
        print(f"     title: {title}")
        print(f"     turns: {turns}    updated: {updated}")
        print(f"     path: {it.get('path')}")


def resolve_by_ident_or_index(
    ident: str,
    items: Optional[List[Dict[str, object]]] = None,
    *,
    root: Optional[Path] = None,
) -> Optional[Path]:
    """Resolve a session path by numeric index, id, or filesystem path."""

    if items is None:
        items = noxl_list_sessions(root=root) if root is not None else noxl_list_sessions()
    p: Optional[Path] = None
    if ident.isdigit():
        idx = int(ident)
        if 1 <= idx <= len(items):
            return Path(items[idx - 1]["path"])  # type: ignore[index]
    p = resolve_session(ident, root=root) if root is not None else resolve_session(ident)
    return p


def load_into_context(ident: str, *, messages: List[Dict[str, object]]) -> Optional[List[Dict[str, object]]]:
    items = noxl_list_sessions()
    path = resolve_by_ident_or_index(ident, items)
    if not path:
        print(color(f"No session found for: {ident}", fg="red"))
        return None
    loaded = load_session_messages(path)
    if not loaded:
        print(color("Session is empty or unreadable.", fg="red"))
        return None
    return loaded


def rename_session(ident: str, new_title: str) -> bool:
    items = noxl_list_sessions()
    path = resolve_by_ident_or_index(ident, items)
    if not path:
        print(color(f"No session found for: {ident}", fg="red"))
        return False
    set_session_title_for(path, new_title, custom=True)
    print(color(f"Renamed session {path.stem} -> '{new_title}'", fg="yellow"))
    return True


def merge_sessions(idents: List[str]) -> Optional[Path]:
    items = noxl_list_sessions()
    paths: List[Path] = []
    for ident in idents:
        p = resolve_by_ident_or_index(ident, items)
        if not p:
            print(color(f"Skipping unknown session: {ident}", fg="red"))
            continue
        paths.append(p)
    if len(paths) < 2:
        print(color("Need at least two sessions to merge.", fg="yellow"))
        return None
    out = merge_sessions_paths(paths)
    print(color(f"Merged into: {out}", fg="yellow"))
    return out


def archive_early_sessions() -> Optional[Path]:
    if not _ARCHIVE_AVAILABLE or noxl_archive_early_sessions is None:
        print(
            color(
                "Archive logic not available in this runtime; upgrade core_pinaries to enable it.",
                fg="yellow",
            )
        )
        return None
    out = noxl_archive_early_sessions()
    if out is None:
        print(color("Nothing to archive (need at least two sessions).", fg="yellow"))
        return None
    print(color(f"Early sessions archived at: {out}", fg="yellow"))
    print(color("Source sessions removed (latest retained).", fg="yellow"))
    return out


def show_session(ident: str, *, raw: bool = False) -> bool:
    items = noxl_list_sessions()
    path = resolve_by_ident_or_index(ident, items)
    if not path:
        print(color(f"No session found for: {ident}", fg="red"))
        return False
    messages = load_session_messages(path)
    if not messages:
        print(color("Session is empty or unreadable.", fg="red"))
        return False
    meta = _meta_for(path)
    display = meta.get("display_name") or format_session_display_name(path.stem)
    title = meta.get("title") or "(untitled)"
    turns = meta.get("turns") or len(messages) // 2
    model = meta.get("model") or "?"
    updated = meta.get("updated") or "?"
    sanitized = meta.get("sanitized")

    print(color(f"Session: {display}", fg="magenta", bold=True))
    print(color(f"Title: {title}", fg="yellow"))
    print(f"Model: {model}    Turns: {turns}    Updated: {updated}")
    if sanitized is not None:
        print(f"Sanitized: {sanitized}")
    print(f"Path: {meta.get('path')}")
    print()

    system_messages = [m for m in messages if m.get("role") == "system"]
    if system_messages:
        print(color("System:", fg="yellow", bold=True))
        for sys_msg in system_messages:
            print(sys_msg.get("content", "").strip())
        print()

    if raw:
        for msg in messages:
            print(json.dumps(msg, ensure_ascii=False))
        return True

    for idx, (user_msg, asst_msg) in enumerate(_pair_messages_for_display(messages), 1):
        print(color(f"Turn {idx}", fg="cyan", bold=True))
        print(color("User:", fg="green", bold=True))
        print(user_msg.get("content", "").strip())
        print()
        print(color("Assistant:", fg="#ffefff", bold=True))
        print(asst_msg.get("content", "").strip())
        print()
    return True


def browse_sessions() -> None:
    while True:
        items = noxl_list_sessions()
        if not items:
            print(color("No sessions found.", fg="yellow"))
            return
        print(color("\nSaved sessions:", fg="yellow", bold=True))
        print_sessions(items)
        print(color("Select a session number to view (Enter to exit, 'r' to refresh):", fg="yellow"))
        try:
            choice = input(color("sessions> ", fg="cyan", bold=True)).strip()
        except EOFError:
            print()
            return
        if not choice:
            return
        if choice.lower() in {"r", "refresh"}:
            continue
        if choice.lower() in {"q", "quit", "exit"}:
            return
        if not show_session(choice):
            continue
        print(color("(Enter to continue browsing, or type 'exit' to finish)", fg="yellow"))
        try:
            cont = input(color("sessions> ", fg="cyan", bold=True)).strip()
        except EOFError:
            print()
            return
        if cont.lower() in {"q", "quit", "exit"}:
            return
def _meta_for(path: Path) -> Dict[str, object]:
    meta_path = path.with_name(path.stem + ".meta.json")
    if meta_path.exists():
        try:
            return json.loads(meta_path.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {
        "id": path.stem,
        "path": str(path),
        "file_name": path.name,
        "display_name": format_session_display_name(path.stem),
    }


def _pair_messages_for_display(messages: Sequence[Dict[str, object]]) -> List[Tuple[Dict[str, object], Dict[str, object]]]:
    pairs: List[Tuple[Dict[str, object], Dict[str, object]]] = []
    pending_user: Optional[Dict[str, object]] = None
    for msg in messages:
        role = msg.get("role")
        if role == "system":
            continue
        if role == "user":
            pending_user = msg
        elif role == "assistant" and pending_user is not None:
            pairs.append((pending_user, msg))
            pending_user = None
    return pairs

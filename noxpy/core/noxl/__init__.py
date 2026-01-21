"""Importable session tooling and CLI utilities for the Noxl toolkit."""

from __future__ import annotations

import json
import argparse
from pathlib import Path
from typing import Any, Dict, Iterable, Iterator, List, Optional

from .sessions import (
    ARCHIVE_ROOT,
    SESSION_ROOT,
    USERS_ROOT,
    archive_early_sessions,
    append_session_to_day_log,
    compute_title_from_messages,
    delete_session_if_empty,
    list_sessions,
    load_session_messages,
    load_session_records,
    merge_sessions_paths,
    resolve_session,
    session_has_dialogue,
    set_session_title_for,
    user_meta_for_path,
)
from ._compat import color, format_session_display_name


def load_meta(log_path: Path) -> Dict[str, Any]:
    """Load meta sidecar data or synthesize a minimal metadata dict."""
    meta_path = log_path.with_name(log_path.stem + ".meta.json")
    meta: Dict[str, Any]
    if meta_path.exists():
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except Exception:
            meta = {}
    else:
        meta = {}

    meta.setdefault("id", log_path.stem)
    meta.setdefault("path", str(log_path))
    meta.setdefault("display_name", format_session_display_name(log_path.stem))
    meta.setdefault("turns", _count_lines(log_path))

    user_meta = user_meta_for_path(log_path)
    meta.setdefault("user_id", user_meta.get("id"))
    meta.setdefault("user_display", user_meta.get("display_name"))
    meta.setdefault("user_meta", user_meta)

    return meta


def list_session_infos(
    root: Path = SESSION_ROOT, *, user: Optional[str] = None
) -> List[Dict[str, Any]]:
    """Return session metadata dictionaries sorted newest first."""
    return list_sessions(root, user=user)


def iter_sessions(
    search: Optional[str] = None,
    *,
    root: Path = SESSION_ROOT,
    user: Optional[str] = None,
) -> Iterator[Dict[str, Any]]:
    """Yield session dictionaries from ``root``, optionally filtered by content."""
    needle = (search or "").strip().lower()
    for info in list_sessions(root, user=user):
        if not needle:
            yield info
            continue
        if any(
            needle in str(info.get(key, "")).lower()
            for key in ("id", "title", "display_name", "user_id", "user_display")
        ):
            yield info
            continue
        path_str = info.get("path")
        if not path_str:
            continue
        try:
            with Path(path_str).open("r", encoding="utf-8") as handle:
                for line in handle:
                    if needle in line.lower():
                        yield info
                        break
        except FileNotFoundError:
            continue


def print_session_table(
    items: Iterable[Dict[str, Any]], *, limit: Optional[int] = None
) -> None:
    """Pretty-print a compact table of session metadata."""
    count = 0
    for idx, info in enumerate(items, 1):
        if limit is not None and count >= limit:
            break
        count += 1
        ident = info.get("id", "?")
        display = info.get("display_name") or format_session_display_name(str(ident))
        turns = info.get("turns", "?")
        title = info.get("title") or "(untitled)"
        updated = info.get("updated") or "?"
        user_display = info.get("user_display") or info.get("user_id") or "?"
        print(color(f"{idx:>3}. {display}", fg="cyan", bold=True))
        print(color(f"     user: {user_display}", fg="magenta"))
        print(f"     title: {title}")
        print(f"     turns: {turns}    updated: {updated}")
        print(f"     path: {info.get('path')}")
    if count == 0:
        print("No sessions found.")


def print_latest_session(info: Dict[str, Any]) -> None:
    """Print a summary of the latest session entry."""
    display = info.get("display_name") or format_session_display_name(str(info.get("id")))
    title = info.get("title") or "(untitled)"
    updated = info.get("updated") or "?"
    turns = info.get("turns") or "?"
    user_display = info.get("user_display") or info.get("user_id") or "?"
    print(color(f"Most recent session: {display}", fg="cyan", bold=True))
    print(color(f"  user: {user_display}", fg="magenta"))
    print(f"  id: {info.get('id')}")
    print(f"  title: {title}")
    print(f"  turns: {turns}")
    print(f"  updated: {updated}")
    print(f"  path: {info.get('path')}")


def show_session(
    ident: str, *, raw: bool = False, root: Path = SESSION_ROOT
) -> int:
    """Display a session conversation resolved within ``root``."""
    path = resolve_session(ident, root)
    if path is None:
        print(f"No session matches '{ident}'.")
        return 1
    messages = load_session_messages(path)
    if not messages:
        print(f"Session '{path.stem}' is empty or unreadable.")
        return 0
    meta = load_meta(path)
    user_display = meta.get("user_display") or meta.get("user_id")
    header = meta.get("display_name", path.stem)
    if user_display:
        print(color(f"== {header} == (user: {user_display})", fg="cyan", bold=True))
    else:
        print(color(f"== {header} ==", fg="cyan", bold=True))
    if meta.get("title"):
        print(color(f"Title: {meta['title']}", fg="yellow"))
    print(color(f"Model: {meta.get('model', '?')}  Turns: {meta.get('turns', len(messages)//2)}", fg="yellow"))
    print("-")
    if raw:
        for msg in messages:
            print(json.dumps(msg, ensure_ascii=False))
        return 0
    for msg in messages:
        role = msg.get("role", "?").upper()
        content = str(msg.get("content", "")).rstrip()
        if role == "USER":
            print(color(f"{role:>8}:", fg="green", bold=True), color(content, fg="green"))
        elif role == "ASSISTANT":
            print(color(f"{role:>8}:", fg="magenta", bold=True), color(content, fg="magenta"))
        else:
            print(color(f"{role:>8}:", fg="yellow", bold=True), content)
        print()
    return 0


def _count_lines(path: Path) -> int:
    try:
        with path.open("r", encoding="utf-8") as handle:
            return sum(1 for _ in handle)
    except FileNotFoundError:
        return 0

def browse_sessions(
    *,
    root: Path = SESSION_ROOT,
    user: Optional[str] = None,
    raw: bool = False,
) -> None:
    """Interactively browse sessions for the given root/user."""

    while True:
        items = list_session_infos(root, user=user)
        if not items:
            print("No sessions found.")
            return

        print()
        print_session_table(items)
        prompt = "(Enter to exit, 'r' to refresh, or choose a number/id)"
        print(prompt)
        try:
            choice = input("noxl> ").strip()
        except EOFError:
            print()
            return

        if not choice:
            return
        if choice.lower() in {"r", "refresh"}:
            continue
        if choice.lower() in {"q", "quit", "exit"}:
            return

        ident = choice
        if choice.isdigit():
            idx = int(choice)
            if 1 <= idx <= len(items):
                ident = str(items[idx - 1].get("path", ""))
            else:
                print(f"Index {choice} out of range (1-{len(items)}).")
                continue

        result = show_session(ident, raw=raw, root=root)
        if result != 0:
            continue

        print("(Press Enter to continue browsing, or type 'exit' to finish)")
        try:
            cont = input("noxl> ").strip()
        except EOFError:
            print()
            return
        if cont.lower() in {"q", "quit", "exit"}:
            return


__all__ = [
    "ARCHIVE_ROOT",
    "SESSION_ROOT",
    "USERS_ROOT",
    "append_session_to_day_log",
    "archive_early_sessions",
    "browse_sessions",
    "cli_build_parser",
    "cli_main",
    "cli_parse_args",
    "compute_title_from_messages",
    "delete_session_if_empty",
    "iter_sessions",
    "list_session_infos",
    "list_sessions",
    "load_meta",
    "load_session_messages",
    "load_session_records",
    "merge_sessions_paths",
    "print_latest_session",
    "print_session_table",
    "resolve_session",
    "session_has_dialogue",
    "set_session_title_for",
    "show_session",
]


def cli_build_parser(prog: str = "noxl") -> argparse.ArgumentParser:
    """Return the argparse parser used by the Noxl CLI."""

    from .cli import build_parser as _build_parser

    return _build_parser(prog=prog)


def cli_parse_args(argv: Optional[List[str]] = None, *, prog: str = "noxl") -> argparse.Namespace:
    """Parse command-line arguments using the CLI parser."""

    from .cli import parse_args as _parse_args

    return _parse_args(argv, prog=prog)


def cli_main(argv: Optional[List[str]] = None) -> int:
    """Run the Noxl CLI programmatically."""

    from .cli import main as _main

    return _main(argv)

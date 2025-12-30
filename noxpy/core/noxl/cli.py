"""Command-line interface tooling for the Noxl memory browser."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Optional

from . import (
    ARCHIVE_ROOT,
    SESSION_ROOT,
    archive_early_sessions,
    iter_sessions,
    list_session_infos,
    merge_sessions_paths,
    print_latest_session,
    print_session_table,
    resolve_session,
    set_session_title_for,
    show_session,
)

DEFAULT_SESSION_ROOT_STR = str(SESSION_ROOT)
DEFAULT_ARCHIVE_ROOT_STR = str(ARCHIVE_ROOT)


def _add_list_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--search",
        metavar="TEXT",
        help="Filter sessions whose metadata or content contains TEXT.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=20,
        help="Maximum sessions to list (default: 20).",
    )
    parser.add_argument(
        "--root",
        metavar="PATH",
        type=_path_arg,
        default=SESSION_ROOT,
        help=f"Sessions root directory (default: {DEFAULT_SESSION_ROOT_STR}).",
    )


def _path_arg(value: str) -> Path:
    return Path(value).expanduser()


def build_parser(prog: str = "noxl") -> argparse.ArgumentParser:
    """Construct the Noxl CLI argument parser."""
    parser = argparse.ArgumentParser(
        prog=prog,
        description="Browse or manage persisted Noctics chat memories.",
    )
    _add_list_options(parser)
    parser.add_argument(
        "--show",
        metavar="SESSION",
        help="Show the contents of a session by id, stem, or path (compat mode).",
    )
    parser.add_argument(
        "--latest",
        action="store_true",
        help="Display only the most recently updated session summary and exit.",
    )
    parser.add_argument(
        "--raw",
        action="store_true",
        help="Print raw JSON messages when used with --show.",
    )

    subparsers = parser.add_subparsers(dest="command")

    list_parser = subparsers.add_parser(
        "list",
        help="List saved sessions (default command).",
    )
    _add_list_options(list_parser)

    latest_parser = subparsers.add_parser(
        "latest",
        help="Show the most recently updated session and exit.",
    )
    latest_parser.add_argument(
        "--json",
        action="store_true",
        help="Print the raw metadata JSON instead of a friendly summary.",
    )
    latest_parser.add_argument(
        "--root",
        metavar="PATH",
        type=_path_arg,
        default=SESSION_ROOT,
        help=f"Sessions root directory (default: {DEFAULT_SESSION_ROOT_STR}).",
    )

    show_parser = subparsers.add_parser(
        "show",
        help="Pretty-print a session conversation by id or path.",
    )
    show_parser.add_argument("session", metavar="SESSION")
    show_parser.add_argument(
        "--raw",
        action="store_true",
        help="Print raw JSON messages instead of a formatted view.",
    )
    show_parser.add_argument(
        "--root",
        metavar="PATH",
        type=_path_arg,
        default=SESSION_ROOT,
        help=f"Sessions root directory (default: {DEFAULT_SESSION_ROOT_STR}).",
    )

    rename_parser = subparsers.add_parser(
        "rename",
        help="Rename a saved session's title.",
    )
    rename_parser.add_argument("session", metavar="SESSION")
    rename_parser.add_argument("title", nargs="+", metavar="TITLE")
    rename_parser.add_argument(
        "--auto",
        action="store_true",
        help="Mark the title as auto-generated instead of custom.",
    )
    rename_parser.add_argument(
        "--root",
        metavar="PATH",
        type=_path_arg,
        default=SESSION_ROOT,
        help=f"Sessions root directory (default: {DEFAULT_SESSION_ROOT_STR}).",
    )

    merge_parser = subparsers.add_parser(
        "merge",
        help="Merge multiple sessions into a new combined log.",
    )
    merge_parser.add_argument("sessions", nargs="+", metavar="SESSION")
    merge_parser.add_argument(
        "--title",
        metavar="TEXT",
        help="Optional title to apply to the merged session.",
    )
    merge_parser.add_argument(
        "--root",
        metavar="PATH",
        type=_path_arg,
        default=SESSION_ROOT,
        help=f"Destination root directory for the merged session (default: {DEFAULT_SESSION_ROOT_STR}).",
    )

    archive_parser = subparsers.add_parser(
        "archive",
        help="Archive all but the most recent session into early-archives.",
    )
    archive_parser.add_argument(
        "--keep-sources",
        action="store_true",
        help="Do not delete the original session files after archiving.",
    )
    archive_parser.add_argument(
        "--root",
        metavar="PATH",
        type=_path_arg,
        default=SESSION_ROOT,
        help=f"Sessions root directory (default: {DEFAULT_SESSION_ROOT_STR}).",
    )
    archive_parser.add_argument(
        "--archive-root",
        metavar="PATH",
        type=_path_arg,
        default=ARCHIVE_ROOT,
        help=f"Archive destination directory (default: {DEFAULT_ARCHIVE_ROOT_STR}).",
    )

    meta_parser = subparsers.add_parser(
        "meta",
        help="Show the stored metadata for a session as JSON.",
    )
    meta_parser.add_argument("session", metavar="SESSION")
    meta_parser.add_argument(
        "--root",
        metavar="PATH",
        type=_path_arg,
        default=SESSION_ROOT,
        help=f"Sessions root directory (default: {DEFAULT_SESSION_ROOT_STR}).",
    )

    count_parser = subparsers.add_parser(
        "count",
        help="Print the number of known sessions (after optional filtering).",
    )
    count_parser.add_argument(
        "--search",
        metavar="TEXT",
        help="Filter sessions before counting (matches metadata fields).",
    )
    count_parser.add_argument(
        "--root",
        metavar="PATH",
        type=_path_arg,
        default=SESSION_ROOT,
        help=f"Sessions root directory (default: {DEFAULT_SESSION_ROOT_STR}).",
    )

    parser.set_defaults(command="list")
    return parser


def parse_args(argv: Optional[List[str]] = None, *, prog: str = "noxl") -> argparse.Namespace:
    """Parse CLI arguments for the Noxl memory browser."""
    parser = build_parser(prog=prog)
    return parser.parse_args(argv)


def _handle_list(search: Optional[str], limit: int, root: Path) -> int:
    items = iter_sessions(search, root=root)
    print_session_table(items, limit=limit)
    return 0


def _handle_latest(*, raw_json: bool = False, root: Path = SESSION_ROOT) -> int:
    latest = list_session_infos(root)
    if not latest:
        print("No sessions found.")
        return 0
    info = latest[0]
    if raw_json:
        import json

        print(json.dumps(info, ensure_ascii=False, indent=2))
        return 0
    print_latest_session(info)
    return 0


def _handle_show(session_ident: str, *, raw: bool, root: Path) -> int:
    return show_session(session_ident, raw=raw, root=root)


def _handle_rename(
    session_ident: str,
    title_parts: Iterable[str],
    *,
    auto: bool,
    root: Path,
) -> int:
    path = resolve_session(session_ident, root)
    if path is None:
        print(f"No session matches '{session_ident}'.")
        return 1
    title = " ".join(str(part) for part in title_parts).strip()
    if not title:
        print("Title cannot be empty.")
        return 1
    set_session_title_for(path, title, custom=not auto)
    flag = "(auto)" if auto else "(custom)"
    print(f"Renamed {path.stem} -> '{title}' {flag}")
    return 0


def _handle_merge(idents: List[str], *, title: Optional[str], root: Path) -> int:
    paths = []
    for ident in idents:
        path = resolve_session(ident, root)
        if path is None:
            print(f"Skipping unknown session: {ident}")
            continue
        paths.append(path)
    if len(paths) < 2:
        print("Need at least two sessions to merge.")
        return 1
    out_path = merge_sessions_paths(paths, title=title, root=root)
    print(f"Merged {len(paths)} sessions into: {out_path}")
    return 0


def _handle_archive(*, keep_sources: bool, root: Path, archive_root: Path) -> int:
    out_path = archive_early_sessions(
        root=root,
        archive_root=archive_root,
        delete_sources=not keep_sources,
    )
    if out_path is None:
        print("Nothing to archive (need at least two sessions).")
        return 0
    print(f"Archived early sessions at: {out_path}")
    if keep_sources:
        print("Sources retained (keep-sources).")
    return 0


def _handle_meta(session_ident: str, root: Path) -> int:
    path = resolve_session(session_ident, root)
    if path is None:
        print(f"No session matches '{session_ident}'.")
        return 1
    from . import load_meta

    info = load_meta(path)
    import json

    print(json.dumps(info, ensure_ascii=False, indent=2))
    return 0


def _handle_count(search: Optional[str], root: Path) -> int:
    count = sum(1 for _ in iter_sessions(search, root=root))
    print(count)
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    """Run the Noxl CLI entrypoint."""
    args = parse_args(argv)

    # Compatibility flags for legacy usage
    if args.show:
        return _handle_show(args.show, raw=args.raw, root=args.root)
    if args.latest:
        return _handle_latest(raw_json=False, root=args.root)

    dispatch: Dict[str, Callable[[argparse.Namespace], int]] = {
        "list": lambda a: _handle_list(a.search, a.limit, a.root),
        "latest": lambda a: _handle_latest(raw_json=a.json, root=a.root),
        "show": lambda a: _handle_show(a.session, raw=a.raw, root=a.root),
        "rename": lambda a: _handle_rename(a.session, a.title, auto=a.auto, root=a.root),
        "merge": lambda a: _handle_merge(a.sessions, title=a.title, root=a.root),
        "archive": lambda a: _handle_archive(
            keep_sources=a.keep_sources,
            root=a.root,
            archive_root=a.archive_root,
        ),
        "meta": lambda a: _handle_meta(a.session, a.root),
        "count": lambda a: _handle_count(a.search, a.root),
    }

    command = args.command or "list"
    handler = dispatch.get(command)
    if handler is None:
        return _handle_list(args.search, args.limit, args.root)
    return handler(args)


__all__ = ["build_parser", "parse_args", "main"]

"""Multitool entrypoint that mirrors the Codex CLI UX while delegating to the
existing Noctics chat client and session tooling."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import List, Optional, Sequence


def _ensure_local_core_path() -> None:
    """Add local source tree copies of the core packages to sys.path when present."""

    repo_root = Path(__file__).resolve().parents[1]
    source_root = repo_root / "core"
    binary_root = repo_root / "core_pinaries"

    if source_root.is_dir():
        source_path = str(source_root)
        binary_resolved = binary_root.resolve() if binary_root.exists() else None

        # Prefer pure-Python sources for local development.
        if binary_resolved:
            sys.path = [p for p in sys.path if Path(p).resolve() != binary_resolved]
        if source_path not in sys.path:
            sys.path.insert(0, source_path)

        # Drop modules that might have been imported from the binary bundle.
        for name, module in list(sys.modules.items()):
            module_path = getattr(module, "__file__", "")
            if module_path and binary_root.as_posix() in module_path:
                sys.modules.pop(name, None)

    if binary_root.is_dir():
        binary_path = str(binary_root)
        if binary_path not in sys.path:
            sys.path.append(binary_path)
        try:
            import core_pinaries

            core_pinaries.ensure_modules()
        except Exception:
            pass


def _import_core_dependencies() -> None:
    global color, cmd_archive_early_sessions, cmd_browse_sessions, cmd_latest_session
    global cmd_list_sessions, cmd_merge_sessions, cmd_print_latest_session
    global cmd_print_sessions, cmd_rename_session, cmd_show_session, __version__, load_local_dotenv

    from central.colors import color
    from central.commands.sessions import (
        archive_early_sessions as cmd_archive_early_sessions,
        browse_sessions as cmd_browse_sessions,
        latest_session as cmd_latest_session,
        list_sessions as cmd_list_sessions,
        merge_sessions as cmd_merge_sessions,
        print_latest_session as cmd_print_latest_session,
        print_sessions as cmd_print_sessions,
        rename_session as cmd_rename_session,
        show_session as cmd_show_session,
    )
    from central.version import __version__
    from interfaces.dotenv import load_local_dotenv


try:
    _import_core_dependencies()
except ImportError:
    _ensure_local_core_path()
    try:
        _import_core_dependencies()
    except ImportError as exc:  # pragma: no cover - dependency missing
        raise ImportError(
            "Noctics CLI requires the noctics-core package. "
            "Install it with `pip install noctics-core` or make sure the central modules are importable."
        ) from exc
from noctics_cli.app import main as chat_main
from noctics_cli.tui import main as tui_main


def _print_root_help() -> None:
    print(
        color("Noctics CLI", fg="magenta", bold=True),
        "- multitool wrapper\n",
        sep=" ",
        end="",
    )
    print(
        "Usage:\n"
        "  noctics [chat options]\n"
        "  noctics chat [options]\n"
        "  noctics sessions <subcommand>\n"
        "  noctics tui\n"
        "  noctics version\n"
        "\n"
        "Common commands:\n"
        "  chat               launch the interactive chat client (default)\n"
        "  sessions list      list stored sessions with titles\n"
        "  sessions show ID   display a specific session transcript\n"
        "  version            print the current version and exit\n"
        "\n"
        "Run `noctics sessions --help` for additional session tooling.",
    )


def _run_chat(argv: Sequence[str]) -> int:
    return chat_main(list(argv))


def _build_sessions_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="noctics sessions",
        description="Manage saved Noctics sessions.",
    )
    sub = parser.add_subparsers(dest="action")
    sub.required = True

    list_parser = sub.add_parser("list", help="List saved sessions.")
    list_parser.add_argument("--limit", type=int, default=None, help="Limit the number of sessions shown.")
    list_parser.add_argument("--user", default=None, help="Filter by recorded user label.")
    list_parser.add_argument("--root", default=None, help="Override the sessions root directory.")
    list_parser.add_argument(
        "--tip",
        action="store_true",
        help="Show the legacy tip about loading by index (enabled by default when run without --tip/--no-tip).",
    )
    list_parser.add_argument(
        "--no-tip",
        dest="tip",
        action="store_false",
        help="Suppress the legacy loading tip.",
    )
    list_parser.set_defaults(tip=None)

    show_parser = sub.add_parser("show", help="Show a stored session transcript.")
    show_parser.add_argument("ident", help="Session id, index, or path.")
    show_parser.add_argument("--raw", action="store_true", help="Print raw JSON instead of formatted turns.")

    rename_parser = sub.add_parser("rename", help="Rename a stored session.")
    rename_parser.add_argument("ident", help="Session id, index, or path.")
    rename_parser.add_argument("title", help="New session title.")

    merge_parser = sub.add_parser("merge", help="Merge multiple sessions together.")
    merge_parser.add_argument("idents", nargs="+", help="Session ids, indices, or paths to merge.")

    latest_parser = sub.add_parser("latest", help="Show the most recent session summary.")
    latest_parser.add_argument(
        "--show",
        action="store_true",
        help="Print the full transcript of the most recent session.",
    )
    latest_parser.add_argument(
        "--raw",
        action="store_true",
        help="When used with --show, print raw JSON messages.",
    )

    sub.add_parser("browse", help="Interactively browse saved sessions.")
    sub.add_parser("archive-early", help="Archive all but the most recent session.")

    return parser


def _resolve_root(path_arg: Optional[str]) -> Optional[Path]:
    if not path_arg:
        return None
    candidate = Path(path_arg).expanduser()
    return candidate


def _run_sessions(argv: Sequence[str]) -> int:
    parser = _build_sessions_parser()
    args = parser.parse_args(list(argv))

    if args.action == "list":
        items = cmd_list_sessions(root=_resolve_root(args.root), user=args.user)
        if args.limit is not None:
            items = items[: args.limit]
        cmd_print_sessions(items)
        should_tip = args.tip if args.tip is not None else True
        if items and should_tip:
            print("\nTip: load by index with `noctics chat --sessions-load N`")
        return 0

    if args.action == "show":
        ok = cmd_show_session(args.ident, raw=bool(args.raw))
        return 0 if ok else 1

    if args.action == "rename":
        ok = cmd_rename_session(args.ident, args.title)
        return 0 if ok else 1

    if args.action == "merge":
        flattened: List[str] = []
        for token in args.idents:
            flattened.extend(t.strip() for t in token.split(",") if t.strip())
        if len(flattened) < 2:
            print(color("Provide at least two sessions to merge.", fg="red"))
            return 1
        out = cmd_merge_sessions(flattened)
        return 0 if out else 1

    if args.action == "latest":
        latest = cmd_latest_session()
        if not latest:
            print(color("No sessions found.", fg="yellow"))
            return 0
        cmd_print_latest_session(latest)
        if getattr(args, "show", False):
            ident = str(latest.get("id") or latest.get("path") or "")
            if not ident:
                print(color("Unable to determine session id for display.", fg="red"))
                return 1
            ok = cmd_show_session(ident, raw=bool(args.raw))
            return 0 if ok else 1
        return 0

    if args.action == "browse":
        cmd_browse_sessions()
        return 0

    if args.action == "archive-early":
        out = cmd_archive_early_sessions()
        return 0 if out else 1

    parser.error(f"Unhandled action: {args.action}")
    return 1


def main(argv: Sequence[str]) -> int:
    """Entrypoint mirroring the Codex CLI multitool UX."""

    load_local_dotenv(Path(__file__).resolve().parent)

    if not argv:
        return _run_chat([])

    first = argv[0]
    if first in {"-h", "--help", "help"}:
        _print_root_help()
        return 0

    if first in {"-V", "--version", "version"}:
        print(__version__)
        return 0

    if first == "chat":
        return _run_chat(argv[1:])

    if first == "sessions":
        return _run_sessions(argv[1:])

    if first == "tui":
        return tui_main(argv[1:])

    # Compatibility: fall back to the legacy chat parser when no subcommand is used.
    return _run_chat(argv)

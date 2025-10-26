"""
Interactive CLI to talk to a local OpenAI-like chat completions endpoint.

Defaults mirror the provided curl and post to http://localhost:1234/v1/chat/completions.
Supports both non-streaming and streaming (SSE) responses via --stream.

No external dependencies (stdlib only).
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Dict, Any, Iterable, List, Optional
from urllib.parse import urlparse
try:
    import readline  # type: ignore
except Exception:  # pragma: no cover - platform without readline
    readline = None  # type: ignore
from pathlib import Path

try:
    # No direct HTTP in the CLI; core handles requests
    from central.colors import color
    from central.core import (
        ChatClient,
        DEFAULT_URL as CORE_DEFAULT_URL,
        build_payload,
        strip_chain_of_thought,
    )
    from central.core import clean_public_reply
    from central.persona import resolve_persona, render_system_prompt
    from central.runtime_identity import (
        RuntimeIdentity as _RuntimeIdentity,
        resolve_runtime_identity as _resolve_runtime_identity,
    )
    from noxl import (
        compute_title_from_messages,
        load_session_messages,
        list_sessions as noxl_list_sessions,
    )
    from central.commands.completion import setup_completions
    from central.commands.instrument import (
        choose_instrument_interactively,
        describe_instrument_status,
        get_instrument_candidates,
        instrument_automation_enabled,
    )
    from central.config import get_runtime_config
    from central.commands.sessions import (
        list_sessions as cmd_list_sessions,
        print_sessions as cmd_print_sessions,
        resolve_by_ident_or_index as cmd_resolve_by_ident_or_index,
        load_into_context as cmd_load_into_context,
        rename_session as cmd_rename_session,
        merge_sessions as cmd_merge_sessions,
        latest_session as cmd_latest_session,
        print_latest_session as cmd_print_latest_session,
        archive_early_sessions as cmd_archive_early_sessions,
        show_session as cmd_show_session,
        browse_sessions as cmd_browse_sessions,
    )
    from central.commands.help_cmd import print_help as cmd_print_help
    from interfaces.dotenv import load_local_dotenv
    from interfaces.dev_identity import resolve_developer_identity
    from interfaces.paths import resolve_memory_root, resolve_sessions_root
    from central.system_info import hardware_summary
    from central.version import __version__
except ImportError as exc:  # pragma: no cover - dependency missing
    raise ImportError(
        "Noctics CLI requires the noctics-core package. "
        "Install it with `pip install noctics-core` or ensure the central modules are on PYTHONPATH."
    ) from exc
from .metrics import record_cli_run
from .args import DEFAULT_URL, parse_args
from .dev import (
    CENTRAL_DEV_PASSPHRASE_ATTEMPT_ENV,
    require_dev_passphrase,
    resolve_dev_passphrase,
)
from .hud import resolve_logo_lines

RuntimeIdentity = _RuntimeIdentity
resolve_runtime_identity = _resolve_runtime_identity

__all__ = [
    "main",
    "parse_args",
    "RuntimeIdentity",
    "resolve_runtime_identity",
]


DEFAULT_URL = CORE_DEFAULT_URL


THINK_OPEN = "<think>"
THINK_CLOSE = "</think>"
THINK_OPEN_L = THINK_OPEN.lower()
THINK_CLOSE_L = THINK_CLOSE.lower()
THINK_BLOCK_RE = re.compile(r"<think>.*?</think>", re.IGNORECASE | re.DOTALL)


def _read_first_prompt(candidates: Iterable[Path]) -> Optional[str]:
    """Return the first non-empty prompt from the provided candidate paths."""

    for candidate in candidates:
        try:
            if candidate.exists():
                text = candidate.read_text(encoding="utf-8").strip()
                if text:
                    return text
        except OSError:
            continue
    return None


def _configured_instrument_roster() -> List[str]:
    """Return explicitly configured instrument names (env or config only)."""

    env_tokens = [
        token.strip()
        for token in (os.getenv("CENTRAL_INSTRUMENTS") or "").split(",")
        if token.strip()
    ]
    if env_tokens:
        return env_tokens

    cfg = get_runtime_config().instrument
    if cfg.roster:
        return list(cfg.roster)

    return []


def _describe_runtime_target(url: str) -> tuple[str, str]:
    """Return human-readable runtime label and endpoint summary for status output."""

    parsed = urlparse(url)
    host = parsed.hostname or "unknown"
    port = parsed.port
    path = parsed.path or "/"

    location = "local" if host in {"127.0.0.1", "localhost"} else "remote"
    runtime = "HTTP"
    lowered_host = host.lower()
    lowered_path = path.lower()

    if "api/generate" in lowered_path or port == 11434:
        runtime = "Ollama"
    elif "openai" in lowered_host:
        runtime = "OpenAI"
    elif lowered_path.startswith("/v1"):
        runtime = "OpenAI-like"

    if location == "local":
        runtime = f"{runtime} (local)"

    endpoint = f"{host}:{port}" if port else host
    return runtime, endpoint


@dataclass(slots=True)
class RuntimeCandidate:
    url: str
    model: str
    api_key: Optional[str]
    source: str


MEMORY_PAGE_SIZE = 15


@dataclass(slots=True)
class MemoryOption:
    key: str
    label: str
    root: Path
    sessions: List[Dict[str, Any]]
    aliases: tuple[str, ...] = ()

    @property
    def count(self) -> int:
        return len(self.sessions)


def _urls_equivalent(left: Optional[str], right: Optional[str]) -> bool:
    if not left and not right:
        return True
    if not left or not right:
        return False
    return left.rstrip("/") == right.rstrip("/")


def _build_runtime_candidates(args: argparse.Namespace) -> List[RuntimeCandidate]:
    """Return runtime candidates ordered by preference, including fallbacks."""

    primary = RuntimeCandidate(
        url=str(args.url),
        model=str(args.model),
        api_key=args.api_key,
        source="configured",
    )
    candidates: List[RuntimeCandidate] = [primary]

    fallback_urls_env = os.getenv("CENTRAL_LLM_FALLBACK_URLS", "")
    fallback_models_env = os.getenv("CENTRAL_LLM_FALLBACK_MODELS", "")
    fallback_api_keys_env = os.getenv("CENTRAL_LLM_FALLBACK_API_KEYS", "")

    fallback_urls = [value.strip() for value in fallback_urls_env.split(",") if value.strip()]
    fallback_models = [value.strip() for value in fallback_models_env.split(",") if value.strip()]
    fallback_api_keys = [value.strip() for value in fallback_api_keys_env.split(",") if value.strip()]

    for index, url in enumerate(fallback_urls):
        if any(_urls_equivalent(url, existing.url) for existing in candidates):
            continue
        model = fallback_models[index] if index < len(fallback_models) else primary.model
        api_key = fallback_api_keys[index] if index < len(fallback_api_keys) else primary.api_key
        candidates.append(
            RuntimeCandidate(
                url=url,
                model=model or primary.model,
                api_key=api_key or None,
                source=f"fallback #{index + 1}",
            )
        )

    local_url = os.getenv("CENTRAL_LOCAL_LLM_URL", DEFAULT_URL)
    local_model = os.getenv("CENTRAL_LOCAL_LLM_MODEL", "")
    if local_url and not any(_urls_equivalent(local_url, existing.url) for existing in candidates):
        candidates.append(
            RuntimeCandidate(
                url=local_url,
                model=(local_model or primary.model),
                api_key=None,
                source="local fallback",
            )
        )

    return candidates


def _partial_prefix_len(segment: str, token: str) -> int:
    segment_lower = segment.lower()
    token_lower = token.lower()
    max_len = min(len(segment), len(token) - 1)
    for length in range(max_len, 0, -1):
        if segment_lower[-length:] == token_lower[:length]:
            return length
    return 0


def _extract_visible_reply(text: str) -> tuple[str, bool]:
    tokens = text.lower()
    if THINK_OPEN_L not in tokens:
        return text, False
    cleaned = THINK_BLOCK_RE.sub("", text)
    return cleaned.strip(), True


def _parse_timestamp(value: Optional[str]) -> Optional[datetime]:
    if not value or not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    if text.endswith("Z") and "+" not in text[-6:]:
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except Exception:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _session_order_key(info: Dict[str, Any]) -> float:
    dt = _parse_timestamp(info.get("updated")) or _parse_timestamp(info.get("created"))
    if dt:
        return dt.timestamp()
    path_str = info.get("path")
    if isinstance(path_str, str) and path_str:
        try:
            return Path(path_str).stat().st_mtime
        except Exception:
            pass
    return 0.0


def _sort_sessions(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return sorted(items, key=_session_order_key, reverse=True)


def _coerce_turns(info: Dict[str, Any]) -> int:
    turns = info.get("turns")
    if turns is None:
        return 0
    try:
        return int(turns)
    except (TypeError, ValueError):
        return 0


def _format_timestamp(info: Dict[str, Any]) -> str:
    dt = _parse_timestamp(info.get("updated")) or _parse_timestamp(info.get("created"))
    path_str = info.get("path") if not dt else None
    if dt is None and isinstance(path_str, str) and path_str:
        try:
            dt = datetime.fromtimestamp(Path(path_str).stat().st_mtime, tz=timezone.utc)
        except Exception:
            dt = None
    if dt is None:
        return "unknown"
    return dt.strftime("%Y-%m-%d %H:%M UTC")


def _session_label(info: Dict[str, Any]) -> str:
    return str(
        info.get("title")
        or info.get("display_name")
        or info.get("id")
        or "(untitled)"
    )


def _memory_statistics(sessions: List[Dict[str, Any]]) -> Dict[str, Any]:
    if not sessions:
        return {
            "count": 0,
            "avg_turns": 0.0,
            "latest": None,
            "oldest": None,
        }
    total_turns = sum(_coerce_turns(info) for info in sessions)
    avg_turns = total_turns / len(sessions) if sessions else 0.0
    latest = sessions[0]
    oldest = sessions[-1]
    return {
        "count": len(sessions),
        "avg_turns": avg_turns,
        "latest": latest,
        "oldest": oldest,
    }


def _collect_memory_options(default_sessions: List[Dict[str, Any]]) -> List[MemoryOption]:
    """Discover available memory roots (default + imported archives)."""

    options: List[MemoryOption] = []
    default_root = resolve_sessions_root()
    default_sessions_sorted = _sort_sessions(list(default_sessions))
    try:
        default_resolved = default_root.resolve()
    except Exception:
        default_resolved = default_root
    seen_roots: set[Path] = {default_resolved}
    options.append(
        MemoryOption(
            key="noctics",
            label="Noctics (default)",
            root=default_root,
            sessions=default_sessions_sorted,
            aliases=("default", "noctics"),
        )
    )

    memory_root = resolve_memory_root()

    def _sessions_for_root(candidate: Path) -> List[Dict[str, Any]]:
        try:
            return _sort_sessions(noxl_list_sessions(root=candidate))
        except Exception:
            return []

    imported_root = memory_root / "imported"
    if imported_root.exists():
        for child in sorted(imported_root.iterdir()):
            if not child.is_dir():
                continue
            try:
                resolved = child.resolve()
            except Exception:
                resolved = child
            if resolved in seen_roots:
                continue
            sessions = _sessions_for_root(child)
            if not sessions:
                continue
            slug = re.sub(r"[^a-z0-9]+", "-", child.name.lower()).strip("-") or child.name.lower()
            options.append(
                MemoryOption(
                    key=slug,
                    label=f"Imported: {child.name}",
                    root=child,
                    sessions=sessions,
                    aliases=(child.name.lower(), slug),
                )
            )
            seen_roots.add(resolved)

    archives_root = memory_root / "early-archives"
    if archives_root.exists():
        try:
            resolved_archives = archives_root.resolve()
        except Exception:
            resolved_archives = archives_root
        if resolved_archives not in seen_roots:
            sessions = _sessions_for_root(archives_root)
            if sessions:
                options.append(
                    MemoryOption(
                        key="archives",
                        label="Early archives",
                        root=archives_root,
                        sessions=sessions,
                        aliases=("archives", "archive"),
                    )
                )
                seen_roots.add(resolved_archives)

    return options


def _print_session_page(
    option: MemoryOption, offset: int, page_size: int
) -> List[Dict[str, Any]]:
    total = len(option.sessions)
    if total == 0:
        print(color(f"No saved sessions in {option.label} yet.", fg="yellow"))
        return []

    start_idx = offset + 1
    end_idx = min(total, offset + page_size)
    print()
    print(
        color(
            f"{option.label} — showing {start_idx}-{end_idx} of {total} sessions",
            fg="yellow",
            bold=True,
        )
    )

    page_items = option.sessions[offset:end_idx]
    for local_index, info in enumerate(page_items, start=1):
        global_index = offset + local_index
        ident = info.get("id")
        turns = info.get("turns")
        title = info.get("title") or "(untitled)"
        display_name = info.get("display_name") or ident or "(unknown)"
        updated = info.get("updated") or "—"
        path_str = info.get("path") or "?"
        print(
            color(
                f"{local_index:>3}. {display_name} (#{global_index})",
                fg="cyan",
                bold=True,
            )
        )
        print(f"     id: {ident}")
        print(f"     title: {title}")
        print(f"     turns: {turns}    updated: {updated}")
        print(f"     path: {path_str}")

    return page_items

def _make_stream_printer(show_think: bool):
    state = {
        "raw": "",
        "clean": "",
        "thinking": False,
        "indicator_shown": False,
    }

    def emit(piece: str) -> None:
        if not piece:
            return

        state["raw"] += piece
        lower_raw = state["raw"].lower()

        if show_think and not state["indicator_shown"] and THINK_OPEN_L in lower_raw:
            print(color("[thinking…]", fg="yellow", bold=True))
            state["indicator_shown"] = True

        cleaned = clean_public_reply(state["raw"]) or ""
        if cleaned.startswith(state["clean"]):
            delta = cleaned[len(state["clean"]):]
        else:
            delta = cleaned
        if delta:
            print(delta, end="", flush=True)
            state["clean"] = cleaned

    def finish() -> None:
        cleaned = clean_public_reply(state["raw"]) or ""
        if cleaned.startswith(state["clean"]):
            delta = cleaned[len(state["clean"]):]
        else:
            delta = cleaned
        if delta:
            print(delta, end="", flush=True)
        state["raw"] = ""
        state["clean"] = cleaned or ""

    return emit, finish


def request_initial_title_from_central(client: ChatClient) -> Optional[str]:
    """Ask the active model for a concise initial session title."""

    messages_for_title = list(client.messages)
    prompt_text = (
        "Before we begin, suggest a short friendly session title (max 6 words). "
        "Respond with the title only."
    )
    messages_for_title.append({"role": "user", "content": prompt_text})
    try:
        reply, _ = client.transport.send(
            build_payload(
                model=client.model,
                messages=messages_for_title,
                temperature=0.0,
                max_tokens=32 if client.max_tokens == -1 else min(client.max_tokens, 64),
                stream=False,
            ),
            stream=False,
        )
    except Exception:
        return None
    if not reply:
        return None
    reply = strip_chain_of_thought(reply)
    title = reply.strip().strip('"')
    return title[:80] if title else None


def select_session_interactively(
    items: List[Dict[str, Any]], *, show_transcript: bool = False
) -> tuple[Optional[List[Dict[str, Any]]], Optional[Path]]:
    """Prompt the operator to choose a memory source and session."""

    options = _collect_memory_options(items)
    if not options:
        return None, None

    while True:
        print()
        print(color("Available memories:", fg="yellow", bold=True))
        for idx, option in enumerate(options, 1):
            root_display = option.root.expanduser()
            print(color(f" {idx}. {option.label}", fg="cyan", bold=True))
            stats = _memory_statistics(option.sessions)
            latest_info = stats.get("latest")
            oldest_info = stats.get("oldest")
            latest_desc = _session_label(latest_info) if latest_info else "—"
            latest_ts = _format_timestamp(latest_info) if latest_info else "unknown"
            oldest_ts = _format_timestamp(oldest_info) if oldest_info else "unknown"
            avg_turns = stats.get("avg_turns", 0.0)
            print(f"    sessions: {option.count}    avg turns: {avg_turns:.1f}    root: {root_display}")
            if latest_info:
                print(f"    latest: {latest_desc} @ {latest_ts}")
            if oldest_info and option.count > 1:
                print(f"    oldest: {_session_label(oldest_info)} @ {oldest_ts}")

        try:
            raw_choice = input(
                color(
                    "Select memory number or name (Enter for new conversation): ",
                    fg="yellow",
                )
            ).strip()
        except EOFError:
            return None, None

        if not raw_choice:
            return None, None

        lowered_choice = raw_choice.lower()
        if lowered_choice in {"new", "q", "quit"}:
            return None, None

        selected: Optional[MemoryOption] = None
        if raw_choice.isdigit():
            index = int(raw_choice)
            if 1 <= index <= len(options):
                selected = options[index - 1]
        if selected is None:
            for option in options:
                names = {option.key.lower(), option.label.lower(), *(alias.lower() for alias in option.aliases)}
                if lowered_choice in names:
                    selected = option
                    break
        if selected is None:
            print(color("No memory source matched that selection.", fg="red"))
            continue

        offset = 0
        while True:
            total_sessions = len(selected.sessions)
            page_items = _print_session_page(selected, offset, MEMORY_PAGE_SIZE)

            if total_sessions == 0:
                try:
                    empty_choice = input(
                        color(
                            "Enter to start a new conversation, or 'b' to choose another memory: ",
                            fg="yellow",
                        )
                    ).strip()
                except EOFError:
                    return None, None
                if not empty_choice:
                    return None, None
                if empty_choice.lower() in {"b", "back"}:
                    break
                print(color("No stored sessions to load in this memory.", fg="yellow"))
                continue

            try:
                session_choice = input(
                    color(
                        "Select session number/id, 'n' next, 'p' previous, 'b' back, or Enter for new: ",
                        fg="yellow",
                    )
                ).strip()
            except EOFError:
                return None, None

            if not session_choice:
                return None, None

            lowered_session = session_choice.lower()
            if lowered_session in {"b", "back"}:
                break
            if lowered_session in {"n", "next", "more"}:
                if offset + MEMORY_PAGE_SIZE >= total_sessions:
                    print(color("Already showing the oldest sessions.", fg="yellow"))
                else:
                    new_offset = offset + MEMORY_PAGE_SIZE
                    if new_offset >= total_sessions:
                        offset = max(total_sessions - MEMORY_PAGE_SIZE, 0)
                    else:
                        offset = new_offset
                continue
            if lowered_session in {"p", "prev", "previous"}:
                if offset == 0:
                    print(color("Already at the newest sessions.", fg="yellow"))
                else:
                    offset = max(0, offset - MEMORY_PAGE_SIZE)
                continue

            if session_choice.isdigit():
                local_num = int(session_choice)
                if 1 <= local_num <= len(page_items):
                    global_index = offset + local_num
                    session_choice = str(global_index)

            path = cmd_resolve_by_ident_or_index(
                session_choice,
                selected.sessions,
                root=selected.root,
            )
            if not path:
                print(color("No session found for that selection.", fg="red"))
                continue
            loaded = load_session_messages(path)
            if not loaded:
                print(color("Session is empty or unreadable.", fg="red"))
                continue
            print(color(f"Loaded session: {path.stem}", fg="yellow"))
            if show_transcript:
                print()
                cmd_show_session(path.as_posix())
            return loaded, path



def main(argv: List[str]) -> int:
    # Load environment from a local .env file by default
    load_local_dotenv(Path(__file__).resolve().parent)

    args = parse_args(argv)
    persona = resolve_persona(args.model)

    if getattr(args, "dev", False):
        dev_passphrase = resolve_dev_passphrase()
        interactive = sys.stdin.isatty() and os.getenv(CENTRAL_DEV_PASSPHRASE_ATTEMPT_ENV) is None
        if not require_dev_passphrase(dev_passphrase, interactive=interactive):
            print(color("Developer mode locked.", fg="red", bold=True))
            return 1

    try:
        record_cli_run(resolve_memory_root(), __version__)
    except Exception:
        pass

    if getattr(args, "version", False):
        print(__version__)
        return 0

    interactive = sys.stdin.isatty()
    original_label = (args.user_name or "").strip()
    identity = resolve_runtime_identity(
        dev_mode=bool(getattr(args, "dev", False)),
        initial_label=original_label,
        interactive=interactive,
    )
    args.user_name = identity.display_name
    if interactive:
        if getattr(args, "dev", False):
            print(color("Running in developer mode as Rei.", fg="yellow"))
        else:
            if identity.created_user:
                print(
                    color(
                        f"Registered user '{identity.display_name}' (id: {identity.user_id}).",
                        fg="yellow",
                    )
                )
            else:
                print(
                    color(
                        f"Signed in as '{identity.display_name}' (id: {identity.user_id}).",
                        fg="yellow",
                    )
                )

    instrument_status_line = describe_instrument_status()
    instrument_auto_on = instrument_automation_enabled()
    if interactive:
        print(color(f"Instruments: {instrument_status_line}", fg="yellow"))
    hardware_info = hardware_summary()
    hardware_line = f"Hardware context: {hardware_info}"
    instrument_auto_line = f"Instrument automation: {'ON' if instrument_auto_on else 'OFF'}"
    persona_line = (
        f"Central persona: {persona.central_name} ({persona.scale_label}) — model target {persona.model_target}"
    )

    if args.stream is None:
        if interactive:
            prompt = color("Enable streaming? [y/N]: ", fg="yellow")
            try:
                choice = input(prompt).strip().lower()
            except EOFError:
                choice = ""
            args.stream = choice in {"y", "yes"}
        else:
            args.stream = False
    else:
        args.stream = bool(args.stream)

    # Session management commands (non-interactive)
    if args.sessions_ls:
        items = cmd_list_sessions()
        if not items:
            print("No sessions found.")
            return 0
        cmd_print_sessions(items)
        print("\nTip: load by index with --sessions-load N")
        return 0

    if args.sessions_rename is not None:
        ident, new_title = args.sessions_rename
        ok = cmd_rename_session(ident, new_title)
        return 0 if ok else 1

    if args.sessions_merge is not None:
        # Accept indices and ids; allow comma-separated in args
        raw_tokens: List[str] = []
        for tok in args.sessions_merge:
            raw_tokens.extend([t for t in tok.split(",") if t])
        if not raw_tokens:
            print("No sessions specified to merge.")
            return 1
        out = cmd_merge_sessions(raw_tokens)
        if out is None:
            return 1
        return 0

    if args.sessions_latest:
        latest = cmd_latest_session()
        if not latest:
            print("No sessions found.")
            return 0
        cmd_print_latest_session(latest)
        return 0

    if args.sessions_archive_early:
        out = cmd_archive_early_sessions()
        return 0 if out else 1

    if args.sessions_show:
        ok = cmd_show_session(args.sessions_show, raw=bool(args.raw))
        return 0 if ok else 1

    if args.sessions_browse:
        cmd_browse_sessions()
        return 0

    sessions_snapshot = cmd_list_sessions()
    first_run_global = not sessions_snapshot

    # Load default system prompt from file if not provided
    if args.system is None and not args.messages_file:
        if getattr(args, "dev", False):
            args.system = _read_first_prompt(
                [
                    Path("memory/system_prompt.dev.local.md"),
                    Path("memory/system_prompt.dev.local.txt"),
                    Path("memory/system_prompt.dev.md"),
                    Path("memory/system_prompt.dev.txt"),
                ]
            )
        if args.system is None:
            args.system = _read_first_prompt(
                [
                    Path("memory/system_prompt.local.md"),
                    Path("memory/system_prompt.local.txt"),
                    Path("memory/system_prompt.md"),
                    Path("memory/system_prompt.txt"),
                ]
            )

    if args.system:
        args.system = render_system_prompt(args.system, persona)

    session_path_to_adopt: Optional[Path] = None
    messages: List[Dict[str, Any]] = []
    if args.messages_file:
        with open(args.messages_file, "r", encoding="utf-8") as f:
            messages = json.load(f)
            if not isinstance(messages, list):
                raise SystemExit("--messages must point to a JSON array of messages")
        for msg in messages:
            if isinstance(msg, dict) and msg.get("role") == "system":
                content = str(msg.get("content") or "")
                msg["content"] = render_system_prompt(content, persona)
    else:
        if args.sessions_load:
            path: Optional[Path] = None
            if str(args.sessions_load).isdigit():
                items = sessions_snapshot
                idx = int(args.sessions_load)
                if 1 <= idx <= len(items):
                    path = Path(items[idx - 1]["path"])  # type: ignore[index]
            if path is None:
                candidate = Path(args.sessions_load)
                if candidate.exists():
                    path = candidate
            if path is None:
                path = cmd_resolve_by_ident_or_index(str(args.sessions_load))
            if not path:
                raise SystemExit(f"--sessions-load: not found: {args.sessions_load}")
            loaded = load_session_messages(path)
            if loaded:
                messages = loaded
                sys_msgs = [m for m in messages if m.get("role") == "system"]
                if sys_msgs:
                    args.system = sys_msgs[0].get("content")
                    if args.system:
                        args.system = render_system_prompt(str(args.system), persona)
                        sys_msgs[0]["content"] = args.system
            session_path_to_adopt = path
            print(color(f"Loaded session: {path.stem}", fg="yellow"))
        elif interactive and not args.messages_file:
            loaded_messages, chosen_path = select_session_interactively(
                sessions_snapshot,
                show_transcript=bool(getattr(args, "dev", False)),
            )
            if loaded_messages is not None:
                messages = loaded_messages
                session_path_to_adopt = chosen_path
                sys_msgs = [m for m in messages if m.get("role") == "system"]
                if sys_msgs:
                    args.system = sys_msgs[0].get("content")
                    if args.system:
                        args.system = render_system_prompt(str(args.system), persona)
                        sys_msgs[0]["content"] = args.system
        if not messages and args.system:
            messages.append({"role": "system", "content": args.system})

    # Determine and display system prompt at startup (colored)
    sys_prompt_text: Optional[str] = None
    if args.messages_file:
        # Take the last system message if present
        sys_msgs = [m for m in messages if isinstance(m, dict) and m.get("role") == "system"]
        if sys_msgs:
            sys_prompt_text = str(sys_msgs[-1].get("content", "")).strip() or None
    else:
        sys_prompt_text = args.system

    # Inject identity context if not already present
    identity_line = identity.context_line()
    if identity_line:
        already_tagged = False
        for msg in messages:
            if isinstance(msg, dict) and msg.get("role") == "system":
                content = str(msg.get("content") or "")
                if identity_line in content:
                    already_tagged = True
                    break
        if not already_tagged:
            inserted = False
            for i in range(len(messages) - 1, -1, -1):
                msg = messages[i]
                if isinstance(msg, dict) and msg.get("role") == "system":
                    content = str(msg.get("content") or "").strip()
                    content = (content + ("\n\n" if content else "") + identity_line).strip()
                    messages[i]["content"] = content
                    inserted = True
                    break
            if not inserted:
                messages.insert(0, {"role": "system", "content": identity_line})
            if args.system:
                content = args.system.strip()
                if identity_line not in content:
                    args.system = (content + ("\n\n" if content else "") + identity_line).strip()
            else:
                args.system = identity_line

    persona_inserted = False
    for msg in messages:
        if isinstance(msg, dict) and msg.get("role") == "system" and persona_line in str(msg.get("content") or ""):
            persona_inserted = True
            break
    if not persona_inserted:
        inserted = False
        for i in range(len(messages) - 1, -1, -1):
            msg = messages[i]
            if isinstance(msg, dict) and msg.get("role") == "system":
                content = str(msg.get("content") or "").strip()
                content = (content + ("\n\n" if content else "") + persona_line).strip()
                messages[i]["content"] = content
                inserted = True
                break
        if not inserted:
            messages.insert(0, {"role": "system", "content": persona_line})
        if args.system:
            content = args.system.strip()
            if persona_line not in content:
                args.system = (content + ("\n\n" if content else "") + persona_line).strip()
        else:
            args.system = persona_line

    hardware_inserted = False
    for msg in messages:
        if isinstance(msg, dict) and msg.get("role") == "system":
            content = str(msg.get("content") or "")
            if hardware_line in content:
                hardware_inserted = True
                break
    if not hardware_inserted:
        inserted = False
        for i in range(len(messages) - 1, -1, -1):
            msg = messages[i]
            if isinstance(msg, dict) and msg.get("role") == "system":
                content = str(msg.get("content") or "").strip()
                content = (content + ("\n\n" if content else "") + hardware_line).strip()
                messages[i]["content"] = content
                inserted = True
                break
        if not inserted:
            messages.insert(0, {"role": "system", "content": hardware_line})
        if args.system:
            content = args.system.strip()
            if hardware_line not in content:
                args.system = (content + ("\n\n" if content else "") + hardware_line).strip()
        else:
            args.system = hardware_line
    # Expose instrument automation status to Central as part of the system preamble
    instrument_status_inserted = False
    for msg in messages:
        if isinstance(msg, dict) and msg.get("role") == "system" and instrument_auto_line in str(msg.get("content") or ""):
            instrument_status_inserted = True
            break
    if not instrument_status_inserted:
        inserted = False
        for i in range(len(messages) - 1, -1, -1):
            msg = messages[i]
            if isinstance(msg, dict) and msg.get("role") == "system":
                content = str(msg.get("content") or "").strip()
                content = (content + ("\n\n" if content else "") + instrument_auto_line).strip()
                messages[i]["content"] = content
                inserted = True
                break
        if not inserted:
            messages.insert(0, {"role": "system", "content": instrument_auto_line})
        if args.system:
            content = args.system.strip()
            if instrument_auto_line not in content:
                args.system = (content + ("\n\n" if content else "") + instrument_auto_line).strip()
        else:
            args.system = instrument_auto_line

    instrument_roster_line: Optional[str] = None
    configured_roster = _configured_instrument_roster()
    if configured_roster:
        roster_clause = ", ".join(configured_roster)
        instrument_roster_line = (
            f"Instrument roster ready: {roster_clause}. Use [INSTRUMENT QUERY] blocks when you truly need to escalate."
        )
    if instrument_roster_line:
        instrument_roster_inserted = False
        for msg in messages:
            if (
                isinstance(msg, dict)
                and msg.get("role") == "system"
                and instrument_roster_line in str(msg.get("content") or "")
            ):
                instrument_roster_inserted = True
                break
        if not instrument_roster_inserted:
            inserted = False
            for i in range(len(messages) - 1, -1, -1):
                msg = messages[i]
                if isinstance(msg, dict) and msg.get("role") == "system":
                    content = str(msg.get("content") or "").strip()
                    content = (content + ("\n\n" if content else "") + instrument_roster_line).strip()
                    messages[i]["content"] = content
                    inserted = True
                    break
            if not inserted:
                messages.insert(0, {"role": "system", "content": instrument_roster_line})
            if args.system:
                content = args.system.strip()
                if instrument_roster_line not in content:
                    args.system = (content + ("\n\n" if content else "") + instrument_roster_line).strip()
            else:
                args.system = instrument_roster_line

    user_line = f"User handle: {args.user_name}"
    user_inserted = False
    for msg in messages:
        if isinstance(msg, dict) and msg.get("role") == "system" and user_line in str(msg.get("content") or ""):
            user_inserted = True
            break
    if not user_inserted:
        inserted = False
        for i in range(len(messages) - 1, -1, -1):
            msg = messages[i]
            if isinstance(msg, dict) and msg.get("role") == "system":
                content = str(msg.get("content") or "").strip()
                content = (content + ("\n\n" if content else "") + user_line).strip()
                messages[i]["content"] = content
                inserted = True
                break
        if not inserted:
            messages.insert(0, {"role": "system", "content": user_line})
        if args.system:
            content = args.system.strip()
            if user_line not in content:
                args.system = (content + ("\n\n" if content else "") + user_line).strip()
        else:
            args.system = user_line

    instrument_roster = get_instrument_candidates()
    hardware_brief = hardware_info.replace("OS: ", "").split(";")[0].strip()
    if instrument_roster:
        roster_display = ", ".join(instrument_roster)
        automation_display = "ON" if instrument_automation_enabled() else "OFF"
    else:
        roster_display = "coming soon"
        automation_display = "coming soon"
    operator_name = identity.display_name

    runtime_meta = {
        "runtime": "",
        "endpoint": "",
        "model": str(args.model),
        "source": "configured",
    }

    def update_runtime_meta(url: str, model: str, source: str) -> None:
        runtime_label, runtime_endpoint = _describe_runtime_target(url)
        runtime_meta["runtime"] = runtime_label
        runtime_meta["endpoint"] = runtime_endpoint
        runtime_meta["model"] = str(model)
        runtime_meta["source"] = source

    update_runtime_meta(args.url, args.model, "configured")

    def print_status_block() -> None:
        if not interactive:
            return
        term_columns = shutil.get_terminal_size(fallback=(80, 24)).columns
        session_info = cmd_list_sessions()
        session_count = len(session_info)
        header = persona.central_name
        logo_lines = resolve_logo_lines(style_hint=persona.variant_name)
        automation = automation_display
        roster_text = roster_display or "coming soon"
        info_fields = [
            ("Version", __version__),
            ("Operator", operator_name),
            ("Hardware", hardware_brief),
            ("Runtime", runtime_meta["runtime"]),
            ("Runtime Source", runtime_meta["source"]),
            ("Endpoint", runtime_meta["endpoint"]),
            ("Model", runtime_meta["model"]),
            ("Model Target", persona.model_target),
            ("Persona", persona.central_name),
            ("Scale", persona.scale_label),
            ("Variant", persona.variant_name),
            ("Tagline", persona.tagline),
            ("Instrument Auto", automation),
            ("Instrument Roster", roster_text),
            ("Sessions Saved", str(session_count)),
        ]

        developer_line: Optional[str] = None
        if getattr(args, "dev", False):
            dev_identity = resolve_developer_identity()
            developer_line = f"Developer      : {dev_identity.display_name}"

        footer_text = f"{persona.central_name.upper()} · {persona.variant_display}"

        content_specs: List[Dict[str, Any]] = []
        content_specs.append({"text": header, "align": "center", "bold": True})
        if developer_line:
            content_specs.append({"text": developer_line, "align": "left", "bold": False})
        content_specs.append({"separator": True})
        for art_line in logo_lines:
            content_specs.append({"text": art_line, "align": "center", "bold": True})
        content_specs.append({"separator": True})
        for label, value in info_fields:
            content_specs.append(
                {
                    "text": f"{label:<16}: {value}",
                    "align": "left",
                    "bold": False,
                }
            )
        content_specs.append({"separator": True})
        content_specs.append({"text": footer_text, "align": "center", "bold": True})

        plain_lines = [
            spec["text"]
            for spec in content_specs
            if not spec.get("separator") and isinstance(spec.get("text"), str)
        ]
        if not plain_lines:
            return

        max_line_length = max(len(line) for line in plain_lines)
        available_width = max(term_columns - 4, 10)
        inner_width = min(max_line_length, available_width)
        preferred_min_width = 40
        if available_width >= preferred_min_width:
            inner_width = max(inner_width, min(preferred_min_width, available_width))
        line_width = inner_width + 4
        margin = max((term_columns - line_width) // 2, 0)

        def truncate(text: str) -> str:
            if len(text) <= inner_width:
                return text
            if inner_width <= 1:
                return text[:inner_width]
            return text[: inner_width - 1] + "…"

        def render_content(text: str, *, align: str, bold: bool) -> str:
            clipped = truncate(text)
            if align == "center":
                padded = clipped.center(inner_width)
            elif align == "right":
                padded = clipped.rjust(inner_width)
            else:
                padded = clipped.ljust(inner_width)
            return color(f"║ {padded} ║", fg="cyan", bold=bold)

        separator_line = color("╠" + "═" * (inner_width + 2) + "╣", fg="cyan")
        top_border = color("╔" + "═" * (inner_width + 2) + "╗", fg="cyan", bold=True)
        bottom_border = color("╚" + "═" * (inner_width + 2) + "╝", fg="cyan", bold=True)

        rendered_lines: List[str] = [top_border]
        for spec in content_specs:
            if spec.get("separator"):
                rendered_lines.append(separator_line)
                continue
            text = spec["text"]
            align = spec.get("align", "left")
            bold = bool(spec.get("bold", False))
            rendered_lines.append(render_content(text, align=align, bold=bold))
        rendered_lines.append(bottom_border)

        seen: set[str] = set()
        for raw_line in rendered_lines:
            if raw_line in seen:
                continue
            seen.add(raw_line)
            print(" " * margin + raw_line)

    if (sys_prompt_text or identity_line):
        # Recompute for display after any identity injection
        if args.messages_file:
            sys_msgs = [m for m in messages if isinstance(m, dict) and m.get("role") == "system"]
            sys_prompt_text = str(sys_msgs[-1].get("content", "")).strip() if sys_msgs else None
        else:
            sys_prompt_text = args.system

    show_sys_prompt = os.getenv("CENTRAL_SHOW_SYSTEM_PROMPT", "")
    if sys_prompt_text and show_sys_prompt.lower() in {"1", "true", "yes", "on"}:
        print(color("System Prompt:", fg="magenta", bold=True))
        print(color(sys_prompt_text, fg="magenta"))
        print()

    runtime_candidates = _build_runtime_candidates(args)
    connection_errors: List[tuple[RuntimeCandidate, Exception]] = []
    client: Optional[ChatClient] = None
    current_candidate_index = -1
    last_persona_line: Optional[str] = None

    def _remove_persona_line_from_text(text: Optional[str], persona_line: Optional[str]) -> Optional[str]:
        if not text or not persona_line:
            return text
        cleaned = text.replace(f"\n\n{persona_line}", "")
        cleaned = cleaned.replace(f"{persona_line}\n\n", "")
        cleaned = cleaned.replace(persona_line, "")
        cleaned = cleaned.strip()
        return cleaned or None

    def _remove_persona_from_messages(target_messages: List[Dict[str, Any]], persona_line: Optional[str]) -> None:
        if not persona_line:
            return
        for msg in target_messages:
            if isinstance(msg, dict) and msg.get("role") == "system":
                content = str(msg.get("content") or "")
                if persona_line not in content:
                    continue
                cleaned = content.replace(f"\n\n{persona_line}", "")
                cleaned = cleaned.replace(f"{persona_line}\n\n", "")
                cleaned = cleaned.replace(persona_line, "")
                msg["content"] = cleaned.strip()

    def activate_runtime(start_index: int, *, show_fallback: bool) -> bool:
        nonlocal client, persona, messages, current_candidate_index, last_persona_line, args
        prior_client = client
        prior_log_path: Optional[Path] = None
        if prior_client:
            try:
                prior_log_path = prior_client.log_path()
            except Exception:
                prior_log_path = None

        for idx in range(start_index, len(runtime_candidates)):
            candidate = runtime_candidates[idx]
            base_messages = deepcopy(prior_client.messages) if prior_client else deepcopy(messages)
            client_candidate: Optional[ChatClient] = None
            try:
                client_candidate = ChatClient(
                    url=candidate.url,
                    model=candidate.model,
                    api_key=candidate.api_key,
                    temperature=args.temperature,
                    max_tokens=args.max_tokens,
                    stream=bool(args.stream),
                    sanitize=bool(args.sanitize),
                    messages=base_messages,
                    enable_logging=True,
                    strip_reasoning=not bool(args.show_think),
                    memory_user=identity.user_id,
                    memory_user_display=identity.display_name,
                )
                client_candidate.check_connectivity()
            except Exception as exc:
                connection_errors.append((candidate, exc))
                if client_candidate is not None:
                    try:
                        client_candidate.maybe_delete_empty_session()
                    except Exception:
                        pass
                label, endpoint = _describe_runtime_target(candidate.url)
                target_stream = sys.stdout if interactive else sys.stderr
                print(color(f"Runtime unavailable ({label} @ {endpoint}): {exc}", fg="red"), file=target_stream)
            continue

            client = client_candidate
            persona = client.persona
            current_candidate_index = idx
            args.url = candidate.url
            args.model = candidate.model
            args.api_key = candidate.api_key
            update_runtime_meta(candidate.url, candidate.model, candidate.source)

            if prior_log_path:
                try:
                    client.adopt_session_log(prior_log_path)
                except Exception:
                    pass

            if last_persona_line:
                _remove_persona_from_messages(client.messages, last_persona_line)
                args.system = _remove_persona_line_from_text(args.system, last_persona_line)

            persona_line = (
                f"Central persona: {persona.central_name} ({persona.scale_label}) — model target {persona.model_target}"
            )
            last_persona_line = persona_line
            if args.system:
                content = args.system.strip()
                if persona_line not in content:
                    args.system = (content + ("\n\n" if content else "") + persona_line).strip()
            else:
                args.system = persona_line

            inserted = False
            for i in range(len(client.messages) - 1, -1, -1):
                msg = client.messages[i]
                if isinstance(msg, dict) and msg.get("role") == "system":
                    content = str(msg.get("content") or "").strip()
                    if persona_line in content:
                        inserted = True
                        break
                    content = (content + ("\n\n" if content else "") + persona_line).strip()
                    client.messages[i]["content"] = content
                    inserted = True
                    break
            if not inserted:
                client.messages.insert(0, {"role": "system", "content": persona_line})
            messages = client.messages

            instrument_info = client.describe_target()
            instrument_name = instrument_info.get("instrument")
            instrument_warning = instrument_info.get("instrument_warning")
            status_stream = sys.stdout if interactive else sys.stderr
            if instrument_warning:
                print(
                    color(
                        f"Instrument unavailable: {instrument_warning}",
                        fg="yellow",
                    ),
                    file=status_stream,
                )
            if instrument_name:
                print(
                    color(
                        f"Instrument engaged: {instrument_name}",
                        fg="yellow",
                    ),
                    file=status_stream,
                )
            if (idx > start_index or show_fallback):
                label, endpoint = _describe_runtime_target(candidate.url)
                print(color(f"Runtime fallback engaged: {label} ({endpoint}).", fg="yellow"), file=status_stream)
            return True

        return False

    if not activate_runtime(0, show_fallback=False):
        status_stream = sys.stdout if interactive else sys.stderr
        print(color("Unable to reach any configured runtime.", fg="red", bold=True), file=status_stream)
        for candidate, exc in connection_errors:
            label, endpoint = _describe_runtime_target(candidate.url)
            print(color(f"  {candidate.source}: {label} ({endpoint}) -> {exc}", fg="red"), file=status_stream)
        return 2

    if interactive:
        print_status_block()
        print(color(persona.summary_line, fg="cyan"))

    def adopt_session(path: Path) -> None:
        nonlocal title_confirmed, first_prompt_handled
        client.maybe_delete_empty_session()
        client.adopt_session_log(path)
        title_confirmed = bool(client.get_session_title())
        first_prompt_handled = True

    if session_path_to_adopt is not None:
        adopt_session(session_path_to_adopt)

    if first_run_global and session_path_to_adopt is None and not client.get_session_title():
        auto_title = request_initial_title_from_central(client)
        if auto_title:
            client.set_session_title(auto_title, custom=True)
            print(color(f"Session titled: {auto_title}", fg="yellow"))

    title_confirmed = bool(client.get_session_title())
    first_prompt_handled = any(m.get("role") == "user" for m in client.messages)
    if session_path_to_adopt is not None:
        first_prompt_handled = True

    def prepare_first_prompt_text(user_text: str, *, allow_interactive: bool) -> str:
        nonlocal title_confirmed, first_prompt_handled
        if first_prompt_handled:
            return user_text

        if not title_confirmed:
            auto_title = compute_title_from_messages(
                client.messages + [{"role": "user", "content": user_text}]
            )
            if auto_title:
                client.set_session_title(auto_title, custom=False)
                print(color(f"Session title set: {auto_title}", fg="yellow"))
                title_confirmed = True

        first_prompt_handled = True
        return user_text

    # ----------
    # Tab completion (interactive only)
    # ----------
    setup_completions()

    dev_shell_pattern = re.compile(r"\[DEV\s*SHELL\s*COMMAND\](.*?)\[/DEV\s*SHELL\s*COMMAND\]", re.IGNORECASE | re.DOTALL)
    set_title_pattern = re.compile(r"\[SET\s*TITLE\](.*?)\[/SET\s*TITLE\]", re.IGNORECASE | re.DOTALL)

    def handle_dev_shell_commands(assistant_text: Optional[str]) -> None:
        if not assistant_text or not getattr(args, "dev", False):
            return
        matches = dev_shell_pattern.findall(assistant_text)
        if not matches:
            return
        for raw in matches:
            command = raw.strip()
            if not command:
                continue
            print(color(f"[dev shell] Running: {command}", fg="yellow"))
            try:
                proc = subprocess.run(
                    command,
                    shell=True,
                    check=False,
                    capture_output=True,
                    text=True,
                )
                output = (proc.stdout or "") + (proc.stderr or "")
            except Exception as exc:  # pragma: no cover - defensive
                output = f"Command failed: {exc}"
            output = output.strip() or "(no output)"
            print(color("[dev shell output]", fg="yellow", bold=True))
            print(output)

            result_text = (
                "[DEV SHELL RESULT]\n"
                f"{output}\n"
                "[/DEV SHELL RESULT]"
            )
            client.messages.append({"role": "assistant", "content": result_text})
            if client.logger:
                sys_msgs = [m for m in client.messages if m.get("role") == "system"]
                to_log = (sys_msgs[-1:] if sys_msgs else []) + [
                    {"role": "assistant", "content": result_text},
                ]
                client.logger.log_turn(to_log)

    def handle_title_change(assistant_text: Optional[str]) -> Optional[str]:
        nonlocal title_confirmed
        if not assistant_text:
            return assistant_text
        matches = set_title_pattern.findall(assistant_text)
        if not matches:
            return assistant_text
        for raw in matches:
            new_title = raw.strip()
            if new_title:
                client.set_session_title(new_title, custom=True)
                title_confirmed = True
                print(color(f"Session title set: {new_title}", fg="yellow"))
        cleaned = set_title_pattern.sub("", assistant_text).strip()
        if client.messages and client.messages[-1].get("role") == "assistant":
            client.messages[-1]["content"] = cleaned or assistant_text
        return cleaned or assistant_text

    def notify_instrument_needed() -> None:
        status_line = describe_instrument_status()
        message = f"Central requested an external instrument. {status_line}"
        if instrument_auto_on:
            message += " Central will attempt to call the configured instrument automatically when available."
        else:
            if not args.instrument and sys.stdin.isatty():
                chosen = choose_instrument_interactively(args.instrument)
                if chosen:
                    args.instrument = chosen
            message += " Instrument automation is unavailable, so instruments cannot be reached right now. Central must respond with a local fallback."
        print(color(message, fg="yellow"))

    def one_turn(user_text: str) -> Optional[str]:
        nonlocal client, current_candidate_index
        show_think = bool(args.show_think)

        while True:
            if show_think:
                print(color("[processing…]", fg="yellow", bold=True), flush=True)

            if args.stream:
                stream_emit, stream_finish = _make_stream_printer(show_think)
            else:
                stream_emit = None
                stream_finish = None

            try:
                if args.stream:
                    assistant = client.one_turn(user_text, on_delta=stream_emit)
                else:
                    assistant = client.one_turn(user_text)
            except Exception as exc:
                if args.stream and stream_finish:
                    stream_finish()
                    print()
                failing_label, failing_endpoint = _describe_runtime_target(args.url)
                target_stream = sys.stdout if interactive else sys.stderr
                print(color(f"Runtime error ({failing_label} @ {failing_endpoint}): {exc}", fg="red"), file=target_stream)
                error_text = str(exc)
                missing_match = re.search(r"model '([^']+)' not found", error_text)
                if missing_match:
                    missing_model = missing_match.group(1)
                    hint = (
                        f"Model '{missing_model}' is unavailable at {failing_endpoint}. "
                        f"Start your runtime and run `ollama pull {missing_model}` (or adjust CENTRAL_LLM_MODEL)."
                    )
                    print(color(hint, fg="yellow"), file=target_stream)
                next_index = current_candidate_index + 1 if current_candidate_index >= 0 else 0
                if not activate_runtime(next_index, show_fallback=True):
                    print(color("Request failed:", fg="red", bold=True), file=target_stream)
                    print(color(f"{exc}", fg="red"), file=target_stream)
                    print(
                        color(
                            "Central could not process the request. Ensure the model endpoint is available and try again.",
                            fg="yellow",
                        ),
                        file=target_stream,
                    )
                    return None
                print(color("Retrying request with fallback runtime…", fg="yellow"), file=target_stream)
                continue

            if args.stream:
                if stream_finish:
                    stream_finish()
                print()
                if assistant is not None and ChatClient.wants_instrument(assistant):
                    notify_instrument_needed()
                handle_dev_shell_commands(assistant)
                assistant = handle_title_change(assistant)
                return assistant

            if assistant is not None:
                if ChatClient.wants_instrument(assistant):
                    notify_instrument_needed()
                handle_dev_shell_commands(assistant)
                assistant = handle_title_change(assistant)
                if assistant:
                    display_text = assistant
                    if show_think:
                        display_text, had_think = _extract_visible_reply(display_text)
                        if had_think:
                            print(color("[thinking…]", fg="yellow", bold=True))
                    else:
                        had_think = False
                    if display_text:
                        print(display_text)
            return assistant

    # Non-interactive one-shot if stdin is piped and no --user provided
    if args.user is None and not sys.stdin.isatty():
        initial = sys.stdin.read().strip()
        if initial:
            initial = prepare_first_prompt_text(initial, allow_interactive=False)
            one_turn(initial)
        # Auto title for non-interactive runs
        try:
            title = client.ensure_auto_title()
            if title:
                print(color(f"Saved session title: {title}", fg="yellow"))
        except Exception:
            pass
        return 0

    # Optional initial user message via flag
    if args.user:
        initial_user = prepare_first_prompt_text(args.user, allow_interactive=False)
        one_turn(initial_user)

    # Interactive loop
    show_help_env = os.getenv("CENTRAL_SHOW_HELP", "")
    if show_help_env.lower() in {"1", "true", "yes", "on"}:
        cmd_print_help(client, user_name=args.user_name)
        if sys.stdin.isatty() and readline is not None:
            print(color("[Tab completion enabled: type '/' then press Tab]", fg="yellow"))
    try:
        while True:
            try:
                prompt = input(color(f"{args.user_name}:", fg="cyan", bold=True) + " ").strip()
            except EOFError:
                break
            if not prompt:
                continue
            if prompt.lower() in {"exit", "quit"}:
                break
            if prompt.lower() in {"/help"}:
                cmd_print_help(client, user_name=args.user_name)
                continue
            if prompt.strip() == "/reset":
                # Reset to just system message if present
                client.reset_messages(system=args.system)
                print(color("Context reset.", fg="yellow"))
                continue
            if prompt.startswith("/iam ") or prompt.strip() == "/iam":
                parts = prompt.split(maxsplit=1)
                new_name = parts[1].strip() if len(parts) > 1 else args.user_name
                if not new_name:
                    print(color("Usage: /iam NAME", fg="yellow"))
                    continue
                args.user_name = new_name
                # Update developer identity context and append as latest system message
                project = os.getenv("NOCTICS_PROJECT_NAME", "Noctics")
                ident = build_identity_context(new_name, project)
                client.messages.append({"role": "system", "content": ident})
                # Also reflect in args.system for future resets
                if args.system:
                    args.system = (args.system + "\n\n" + ident).strip()
                else:
                    args.system = ident
                print(color(f"Developer identity set: {new_name}", fg="yellow"))
                continue
            if prompt.startswith("/instrument"):
                parts = prompt.split(maxsplit=1)
                if len(parts) == 1:
                    # Clear instrument preference
                    args.instrument = None
                    print(color("Instrument cleared. API mode unchanged.", fg="yellow"))
                else:
                    args.instrument = parts[1].strip()
                    print(color(f"Instrument set to '{args.instrument}'.", fg="yellow"))
                continue

            if prompt.startswith("/shell"):
                if not getattr(args, "dev", False):
                    print(color("/shell is only available in developer mode.", fg="red"))
                    continue
                parts = prompt.split(maxsplit=1)
                if len(parts) == 1 or not parts[1].strip():
                    print(color("Usage: /shell COMMAND", fg="yellow"))
                    continue
                command = parts[1].strip()
                try:
                    result = subprocess.run(
                        command,
                        shell=True,
                        check=False,
                        capture_output=True,
                        text=True,
                    )
                    combined = (result.stdout or "") + (result.stderr or "")
                    combined = combined.strip()
                    if not combined:
                        combined = "(no output)"
                    print(color("[shell output]", fg="yellow", bold=True))
                    print(combined)
                except Exception as exc:  # pragma: no cover - defensive
                    combined = f"Command failed: {exc}"
                    print(color(combined, fg="red"))

                user_text = (
                    "[DEV SHELL COMMAND]\n"
                    f"{command}\n"
                    "[/DEV SHELL COMMAND]"
                )
                assistant_text = (
                    "[DEV SHELL RESULT]\n"
                    f"{combined}\n"
                    "[/DEV SHELL RESULT]"
                )
                client.record_turn(user_text, assistant_text)
                continue

            if prompt.startswith("/name "):
                new_name = prompt.split(maxsplit=1)[1].strip()
                if new_name:
                    args.user_name = new_name
                    print(color(f"Prompt label set to: {args.user_name}", fg="yellow"))
                continue

            if prompt.startswith("/anon"):
                tokens = prompt.split()
                if len(tokens) == 1:
                    args.anon_instrument = not bool(args.anon_instrument)
                else:
                    val = tokens[1].lower()
                    args.anon_instrument = val in {"1", "true", "on", "yes"}
                state = "ON" if args.anon_instrument else "OFF"
                print(color(f"Instrument anonymization: {state}", fg="yellow"))
                continue

            if prompt.strip() == "/ls":
                items = cmd_list_sessions()
                cmd_print_sessions(items)
                print(color("Tip: load by index: /load N", fg="yellow"))
                continue

            if prompt.strip() == "/last":
                latest = cmd_latest_session()
                if not latest:
                    print(color("No sessions found.", fg="yellow"))
                else:
                    cmd_print_latest_session(latest)
                continue

            if prompt.strip() == "/archive":
                cmd_archive_early_sessions()
                continue

            if prompt.startswith("/show "):
                ident = prompt.split(maxsplit=1)[1].strip()
                if not cmd_show_session(ident):
                    continue
                continue

            if prompt.strip() == "/browse":
                cmd_browse_sessions()
                continue

            if prompt.startswith("/load "):
                ident = prompt.split(maxsplit=1)[1].strip()
                loaded = cmd_load_into_context(ident, messages=messages)
                if not loaded:
                    continue
                messages = loaded
                client.set_messages(messages)
                sys_msgs = [m for m in messages if m.get("role") == "system"]
                args.system = sys_msgs[0].get("content") if sys_msgs else None
                # print name by resolving for display
                p = cmd_resolve_by_ident_or_index(ident)
                print(color(f"Loaded session: {p.stem if p else ident}", fg="yellow"))
                path_for_adopt = p if p else (Path(ident) if Path(ident).exists() else None)
                if path_for_adopt is not None:
                    adopt_session(path_for_adopt)
                    if getattr(args, "dev", False):
                        print()
                        cmd_show_session(path_for_adopt.as_posix())
                else:
                    if getattr(args, "dev", False):
                        print()
                        cmd_show_session(ident)
                continue

            if prompt.strip() == "/load":
                items = cmd_list_sessions()
                if not items:
                    print(color("No sessions found.", fg="yellow"))
                    continue
                cmd_print_sessions(items)
                try:
                    selection = input(color("Select session number (Enter to cancel): ", fg="yellow")).strip()
                except EOFError:
                    print()
                    continue
                if not selection or selection.lower() in {"q", "quit", "exit"}:
                    continue
                loaded = cmd_load_into_context(selection, messages=messages)
                if not loaded:
                    continue
                messages = loaded
                client.set_messages(messages)
                sys_msgs = [m for m in messages if m.get("role") == "system"]
                args.system = sys_msgs[0].get("content") if sys_msgs else None
                p = cmd_resolve_by_ident_or_index(selection)
                display = p.stem if p else selection
                print(color(f"Loaded session: {display}", fg="yellow"))
                path_for_adopt = p if p else (Path(selection) if Path(selection).exists() else None)
                if path_for_adopt is not None:
                    adopt_session(path_for_adopt)
                    if getattr(args, "dev", False):
                        print()
                        cmd_show_session(path_for_adopt.as_posix())
                else:
                    if getattr(args, "dev", False):
                        print()
                        cmd_show_session(selection)
                continue

            if prompt.startswith("/merge "):
                rest = prompt.split(maxsplit=1)[1].strip()
                if not rest:
                    print(color("Usage: /merge ID [ID ...] (supports indices)", fg="yellow"))
                    continue
                tokens = [t for part in rest.split() for t in part.split(",") if t]
                cmd_merge_sessions(tokens)
                continue
            if prompt.startswith("/title "):
                title = prompt.split(maxsplit=1)[1].strip()
                # Set title on the current active session
                if title:
                    # Use ChatClient to persist on current logger
                    # Note: this names the active session, not a past one
                    try:
                        client.set_session_title(title, custom=True)
                        print(color(f"Session titled: {title}", fg="yellow"))
                    except Exception:
                        print(color("Failed to set session title.", fg="red"))
                continue

            if prompt.startswith("/rename "):
                rest = prompt.split(maxsplit=1)[1]
                ident, sep, new_title = rest.partition(" ")
                if not sep or not new_title.strip():
                    print(color("Usage: /rename ID New Title", fg="yellow"))
                    continue
                if not cmd_rename_session(ident, new_title.strip()):
                    continue
                continue

            instrument_suffix = f" [{args.instrument}]" if args.instrument else ""
            prompt_text = prepare_first_prompt_text(prompt, allow_interactive=True)
            prompt_label = f"{persona.central_name}{instrument_suffix}:"
            print("\n" + color(prompt_label, fg="#ffefff", bold=True) + " ", end="", flush=True)
            one_turn(prompt_text)
    except KeyboardInterrupt:
        print("\n" + color("Interrupted.", fg="yellow"))
    finally:
        deleted = False
        # Auto-generate a session title if not user-provided
        try:
            title = client.ensure_auto_title()
            if title:
                print(color(f"Saved session title: {title}", fg="yellow"))
            else:
                if client.maybe_delete_empty_session():
                    print(color("Session empty; removed log.", fg="yellow"))
                    deleted = True
        except Exception:
            pass
        if not deleted:
            try:
                day_log = client.append_session_to_day_log()
                if day_log:
                    print(color(f"Appended session to {day_log}", fg="yellow"))
            except Exception:
                pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

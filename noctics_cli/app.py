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
import subprocess
import sys
from dataclasses import dataclass
from typing import Dict, Any, List, Optional
from urllib.parse import urlparse
try:
    import readline  # type: ignore
except Exception:  # pragma: no cover - platform without readline
    readline = None  # type: ignore
from pathlib import Path

_CORE_ROOT = Path(__file__).resolve().parents[1] / "core"
if str(_CORE_ROOT) not in sys.path:
    sys.path.insert(0, str(_CORE_ROOT))

# No direct HTTP in the CLI; core handles requests
from central.colors import color
from central.core import ChatClient, DEFAULT_URL as CORE_DEFAULT_URL, build_payload, strip_chain_of_thought
from central.core import clean_public_reply
from central.runtime_identity import (
    RuntimeIdentity as _RuntimeIdentity,
    resolve_runtime_identity as _resolve_runtime_identity,
)
from noxl import compute_title_from_messages, load_session_messages
from central.commands.completion import setup_completions
from central.commands.instrument import (
    choose_instrument_interactively,
    describe_instrument_status,
    get_instrument_candidates,
    instrument_automation_enabled,
)
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
from central.system_info import hardware_summary
from central.version import __version__
from .args import DEFAULT_URL, parse_args
from .dev import (
    CENTRAL_DEV_PASSPHRASE_ATTEMPT_ENV,
    require_dev_passphrase,
    resolve_dev_passphrase,
)

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
    local_model = os.getenv("CENTRAL_LOCAL_LLM_MODEL", "noxllm-05b:latest")
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
    """Prompt the operator to choose a saved session, returning messages and path."""

    if not items:
        return None, None
    print(color("Saved sessions:", fg="yellow", bold=True))
    cmd_print_sessions(items)
    while True:
        try:
            choice = input(color("Select session number or id (Enter for new): ", fg="yellow")).strip()
        except EOFError:
            return None, None
        if not choice:
            return None, None
        path = cmd_resolve_by_ident_or_index(choice, items)
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

    if getattr(args, "dev", False):
        dev_passphrase = resolve_dev_passphrase()
        interactive = sys.stdin.isatty() and os.getenv(CENTRAL_DEV_PASSPHRASE_ATTEMPT_ENV) is None
        if not require_dev_passphrase(dev_passphrase, interactive=interactive):
            print(color("Developer mode locked.", fg="red", bold=True))
            return 1

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
        local_path = Path("memory/system_prompt.local.txt")
        default_path = Path("memory/system_prompt.txt")
        if local_path.exists():
            args.system = local_path.read_text(encoding="utf-8").strip()
        elif default_path.exists():
            args.system = default_path.read_text(encoding="utf-8").strip()

    session_path_to_adopt: Optional[Path] = None
    messages: List[Dict[str, Any]] = []
    if args.messages_file:
        with open(args.messages_file, "r", encoding="utf-8") as f:
            messages = json.load(f)
            if not isinstance(messages, list):
                raise SystemExit("--messages must point to a JSON array of messages")
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
    hardware_brief = hardware_info.replace("OS: ", "").split(";")[0][:22]
    roster_brief = ", ".join(instrument_roster) if instrument_roster else "(none)"
    roster_brief = roster_brief[:22]
    operator_name = identity.display_name[:22]

    runtime_meta = {
        "runtime": "",
        "endpoint": "",
        "model": str(args.model)[:22],
        "source": "configured"[:22],
    }

    def update_runtime_meta(url: str, model: str, source: str) -> None:
        runtime_label, runtime_endpoint = _describe_runtime_target(url)
        runtime_meta["runtime"] = runtime_label[:22]
        runtime_meta["endpoint"] = runtime_endpoint[:22]
        runtime_meta["model"] = str(model)[:22]
        runtime_meta["source"] = source[:22]

    update_runtime_meta(args.url, args.model, "configured")

    def print_status_block() -> None:
        if not interactive:
            return
        automation = "ON" if instrument_automation_enabled() else "OFF"
        roster = ", ".join(instrument_roster) if instrument_roster else "(none)"
        session_info = cmd_list_sessions()
        session_count = len(session_info)
        title = "n0x"
        logo_lines = [
            " _   _   ___    __  __  ",
            "| \\ | | / _ \\  \\ \\/ /  ",
            "|  \\| || | | |  >  <   ",
            "| |\\  || |_| | / /\\ \\  ",
            "|_| \\_| \\___/ /_/  \\_\\ ",
        ]
        status_lines = [
            color("╔════════════════════════════════════════════════════════╗", fg="cyan", bold=True),
            color(f"║ {title.center(52)} ║", fg="cyan", bold=True),
            color("╠════════════════════════════════════════════════════════╣", fg="cyan"),
        ]
        status_lines.extend(
            color(f"║ {line.center(52)} ║", fg="cyan", bold=True) for line in logo_lines
        )
        status_lines.extend([
            color("╠════════════════════════════════════════════════════════╣", fg="cyan"),
            color(f"║ Version        : {__version__:<38}║", fg="cyan"),
            color(f"║ Operator       : {operator_name:<38}║", fg="cyan"),
            color(f"║ Hardware       : {hardware_brief:<38}║", fg="cyan"),
            color(f"║ Runtime        : {runtime_meta['runtime']:<38}║", fg="cyan"),
            color(f"║ Runtime Source : {runtime_meta['source']:<38}║", fg="cyan"),
            color(f"║ Endpoint       : {runtime_meta['endpoint']:<38}║", fg="cyan"),
            color(f"║ Model          : {runtime_meta['model']:<38}║", fg="cyan"),
            color(f"║ Instrument Auto    : {automation:<38}║", fg="cyan"),
            color(f"║ Instrument Roster  : {roster_brief:<38}║", fg="cyan"),
            color(f"║ Sessions Saved : {session_count:<38}║", fg="cyan"),
            color("╠════════════════════════════════════════════════════════╣", fg="cyan"),
            color("║        Personal Intelligence Kernel — Noctics          ║", fg="cyan", bold=True),
            color("╚════════════════════════════════════════════════════════╝", fg="cyan", bold=True),
        ])

        if getattr(args, "dev", False):
            dev_identity = resolve_developer_identity()
            developer_name = dev_identity.display_name[:22]
            status_lines.insert(2, color(f"║ Developer      : {developer_name:<22}║", fg="cyan"))
        seen = set()
        for line in status_lines:
            if line in seen:
                continue
            seen.add(line)
            print(line)

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

    for index, candidate in enumerate(runtime_candidates):
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
                messages=messages,
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
            if interactive:
                label, endpoint = _describe_runtime_target(candidate.url)
                print(color(f"Runtime unavailable ({label} @ {endpoint}): {exc}", fg="red"))
            continue

        client = client_candidate
        args.url = candidate.url
        args.model = candidate.model
        args.api_key = candidate.api_key
        update_runtime_meta(candidate.url, candidate.model, candidate.source)
        instrument_info = client.describe_target()
        instrument_name = instrument_info.get("instrument")
        instrument_warning = instrument_info.get("instrument_warning")
        if instrument_warning and interactive:
            print(
                color(
                    f"Instrument unavailable: {instrument_warning}",
                    fg="yellow",
                )
            )
        if instrument_name and interactive:
            print(
                color(
                    f"Instrument engaged: {instrument_name}",
                    fg="yellow",
                )
            )
        if index > 0 and interactive:
            label, endpoint = _describe_runtime_target(candidate.url)
            print(color(f"Runtime fallback engaged: {label} ({endpoint}).", fg="yellow"))
        break

    if client is None:
        if interactive:
            print(color("Unable to reach any configured runtime.", fg="red", bold=True))
            for candidate, exc in connection_errors:
                label, endpoint = _describe_runtime_target(candidate.url)
                print(color(f"  {candidate.source}: {label} ({endpoint}) -> {exc}", fg="red"))
        return 2

    if interactive:
        print_status_block()

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
        # Normal API mode via core client
        show_think = bool(args.show_think)
        if show_think:
            print(color("[processing…]", fg="yellow", bold=True), flush=True)
        if args.stream:
            stream_emit, stream_finish = _make_stream_printer(show_think)
            # print("errrrroor is here11")

            try:
                assistant = client.one_turn(user_text, on_delta=stream_emit)
                
            except Exception as e:
                stream_finish()
                print()
                print(color("Request failed:", fg="red", bold=True))
                print(color(f"{e}", fg="red"))
                print(
                    color(
                        "Central could not process the request. Ensure the model endpoint is available and try again.",
                        fg="yellow",
                    )
                )
                return None
            stream_finish()
            print()
            if assistant is not None and ChatClient.wants_helper(assistant):
                notify_instrument_needed()
            handle_dev_shell_commands(assistant)
            assistant = handle_title_change(assistant)
            return assistant
        else:
            try:
                # print("errrrroor is here")
                assistant = client.one_turn(user_text)
            except Exception as e:
                print(color("Request failed:", fg="red", bold=True))
                print(color(f"{e}", fg="red"))
                print(
                    color(
                        "Central could not process the request. Ensure the model endpoint is available and try again.",
                        fg="yellow",
                    )
                )
                return None
            if assistant is not None:
                if ChatClient.wants_helper(assistant):
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
            print("\n" + color(f"Noctics Central{instrument_suffix}:", fg="#ffefff", bold=True) + " ", end="", flush=True)
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

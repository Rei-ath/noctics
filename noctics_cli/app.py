"""
Interactive CLI to talk to the local runox runner (nox.gguf).
No external network dependencies (stdlib only).
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
try:
    import readline  # type: ignore
except Exception:  # pragma: no cover - platform without readline
    readline = None  # type: ignore
from pathlib import Path

from nox_env import get_env

try:
    # No direct HTTP in the CLI; core handles requests
    from central.colors import color
    from central.core import (
        ChatClient,
    )
    from central.core import clean_public_reply
    from central.persona import resolve_persona, render_system_prompt
    from central.runtime_identity import (
        RuntimeIdentity as _RuntimeIdentity,
        resolve_runtime_identity as _resolve_runtime_identity,
    )
    from noxl import (
        compute_title_from_messages,
        load_session_context,
        list_sessions as noxl_list_sessions,
    )
    from central.commands.completion import setup_completions
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
from .args import parse_args, DEFAULT_URL as CLI_DEFAULT_URL
from .dev import (
    NOX_DEV_PASSPHRASE_ATTEMPT_ENV,
    require_dev_passphrase,
    resolve_dev_passphrase,
)
from .hud import build_hud_content

RuntimeIdentity = _RuntimeIdentity
resolve_runtime_identity = _resolve_runtime_identity

__all__ = [
    "main",
    "parse_args",
    "RuntimeIdentity",
    "resolve_runtime_identity",
]




THINK_OPEN = "<think>"
THINK_CLOSE = "</think>"
THINK_OPEN_L = THINK_OPEN.lower()
THINK_CLOSE_L = THINK_CLOSE.lower()
THINK_BLOCK_RE = re.compile(r"<think>.*?</think>", re.IGNORECASE | re.DOTALL)

USER_LABEL = "rei"
ASSISTANT_LABEL = "nox"
CODEX_LABEL = "codex"
CODEX_TAG_RE = re.compile(r"@codex\b[ \t:,-]*", re.IGNORECASE)
INSTRUCTION_BLOCK_RE = re.compile(r"\[(run|cmd|py)\](.*?)\[/\1\]", re.IGNORECASE | re.DOTALL)


def _extract_codex_prompt(text: str) -> Optional[str]:
    if not text or not CODEX_TAG_RE.search(text):
        return None
    cleaned = CODEX_TAG_RE.sub("", text).strip()
    return cleaned


def _resolve_noxdex_command() -> Optional[List[str]]:
    override = get_env("NOXDEX_BIN")
    if override:
        candidate = Path(override).expanduser()
        if candidate.exists():
            return [str(candidate)]

    repo_root = Path(__file__).resolve().parents[1]
    wrapper = repo_root / "bin" / "noxdex"
    if wrapper.exists():
        return [str(wrapper)]

    script = repo_root / "experiments" / "noxdex" / "noxdex.py"
    if script.exists():
        python = get_env("NOXDEX_PYTHON") or sys.executable or "python3"
        return [python, str(script)]

    home_wrapper = Path.home() / "bin" / "noxdex"
    if home_wrapper.exists():
        return [str(home_wrapper)]

    return None


def _run_noxdex(prompt: str, *, stream: bool) -> str:
    cmd = _resolve_noxdex_command()
    if not cmd:
        raise RuntimeError("noxdex not found. Build bin/noxdex or set NOXDEX_BIN.")

    args = list(cmd)
    if stream:
        args.append("--stream")
    args.append(prompt)

    if stream:
        proc = subprocess.Popen(
            args,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )
        if proc.stdout is None or proc.stderr is None:
            raise RuntimeError("noxdex output streams are unavailable.")
        acc: List[str] = []
        for chunk in iter(lambda: proc.stdout.read(1), ""):
            if not chunk:
                break
            acc.append(chunk)
            sys.stdout.write(chunk)
            sys.stdout.flush()
        stderr_text = proc.stderr.read()
        code = proc.wait()
        if code != 0:
            raise RuntimeError(stderr_text.strip() or "noxdex failed.")
        return "".join(acc).strip()

    result = subprocess.run(args, capture_output=True, text=True)
    if result.returncode != 0:
        message = (result.stderr or result.stdout or "").strip() or "noxdex failed."
        raise RuntimeError(message)
    return (result.stdout or "").strip()

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


def _read_positive_int(raw: Optional[str]) -> int:
    if raw is None:
        return 0
    try:
        value = int(str(raw).strip())
    except (TypeError, ValueError):
        return 0
    return value if value > 0 else 0


def _resolve_session_context_limits() -> tuple[int, int]:
    raw_turns = get_env("NOX_SESSION_CONTEXT_TURNS")
    raw_messages = get_env("NOX_SESSION_CONTEXT_MESSAGES")
    turns = _read_positive_int(raw_turns)
    messages = _read_positive_int(raw_messages)
    if raw_turns is None and raw_messages is None:
        turns = 0
    return turns, messages


def _resolve_cwd(raw: Optional[str]) -> Path:
    if not raw:
        return Path.cwd()
    candidate = Path(raw).expanduser()
    if not candidate.exists():
        raise SystemExit(f"--cwd not found: {candidate}")
    if not candidate.is_dir():
        raise SystemExit(f"--cwd must be a directory: {candidate}")
    return candidate.resolve()


def _read_file_context(paths: Iterable[str], *, cwd: Path) -> tuple[str, List[str]]:
    blocks: List[str] = []
    labels: List[str] = []
    for raw in paths:
        name = (raw or "").strip()
        if not name:
            continue
        path = Path(name).expanduser()
        if not path.is_absolute():
            path = (cwd / path).resolve()
        if not path.exists():
            raise SystemExit(f"--file not found: {path}")
        if not path.is_file():
            raise SystemExit(f"--file must be a file: {path}")
        try:
            content = path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            raise SystemExit(f"--file read failed ({path}): {exc}") from exc
        try:
            label = str(path.relative_to(cwd))
        except ValueError:
            label = str(path)
        blocks.append(f"[FILE] {label}\n{content}\n[/FILE]")
        labels.append(label)
    return "\n\n".join(blocks), labels


def _append_file_context(system_prompt: Optional[str], file_context: str) -> str:
    base = (system_prompt or "").strip()
    file_context = (file_context or "").strip()
    if not file_context:
        return base
    if base and file_context in base:
        return base
    if not base:
        return f"File context:\n{file_context}"
    return f"{base}\n\nFile context:\n{file_context}"


def _apply_file_context_to_messages(
    messages: List[Dict[str, Any]],
    *,
    file_context: str,
) -> None:
    if not file_context:
        return
    sys_msgs = [m for m in messages if isinstance(m, dict) and m.get("role") == "system"]
    if sys_msgs:
        sys_msgs[0]["content"] = _append_file_context(
            str(sys_msgs[0].get("content") or ""),
            file_context,
        )
    else:
        messages.insert(0, {"role": "system", "content": _append_file_context(None, file_context)})


def _extract_instruction_blocks(text: str) -> List[Dict[str, str]]:
    if not text:
        return []
    return [
        {"kind": match.group(1).lower(), "content": match.group(2)}
        for match in INSTRUCTION_BLOCK_RE.finditer(text)
    ]


def _strip_instruction_blocks(text: str) -> str:
    if not text:
        return ""
    return INSTRUCTION_BLOCK_RE.sub("", text).strip()


def _parse_run_block(block: str) -> Dict[str, Any]:
    instructions: Dict[str, Any] = {
        "cmds": [],
        "py": [],
        "cwd": None,
        "env": {},
        "use": "context",
        "label": None,
        "lang": None,
    }
    for raw_line in block.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        key = key.strip().lower()
        value = value.strip()
        if key == "cmd":
            if value:
                instructions["cmds"].append(value)
        elif key in {"py", "code"}:
            if value:
                instructions["py"].append(value)
        elif key in {"cwd", "dir"}:
            instructions["cwd"] = value or None
        elif key == "env":
            if "=" in value:
                env_key, env_val = value.split("=", 1)
                env_key = env_key.strip()
                if env_key:
                    instructions["env"][env_key] = env_val.strip()
        elif key == "use":
            instructions["use"] = value.lower() or "context"
        elif key == "label":
            instructions["label"] = value or None
        elif key in {"lang", "language"}:
            instructions["lang"] = value.lower() or None
    return instructions


def _resolve_run_cwd(raw: Optional[str], *, base: Path) -> Path:
    if not raw:
        return base
    candidate = Path(raw).expanduser()
    if not candidate.is_absolute():
        candidate = (base / candidate).resolve()
    if not candidate.exists():
        raise RuntimeError(f"run cwd not found: {candidate}")
    if not candidate.is_dir():
        raise RuntimeError(f"run cwd is not a directory: {candidate}")
    return candidate


def _build_run_env(overrides: Dict[str, str]) -> Dict[str, str]:
    env = dict(os.environ)
    for key, value in overrides.items():
        env[key] = value
    return env


def _run_shell_command(cmd: str, *, cwd: Path, env: Dict[str, str]) -> Dict[str, Any]:
    proc = subprocess.run(
        cmd,
        shell=True,
        cwd=str(cwd),
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )
    return {
        "kind": "cmd",
        "cmd": cmd,
        "cwd": str(cwd),
        "code": proc.returncode,
        "stdout": proc.stdout or "",
        "stderr": proc.stderr or "",
    }


def _run_python_block(code: str, *, cwd: Path, env: Dict[str, str]) -> Dict[str, Any]:
    proc = subprocess.run(
        [sys.executable, "-"],
        input=code,
        cwd=str(cwd),
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )
    return {
        "kind": "py",
        "cmd": f"{sys.executable} -",
        "cwd": str(cwd),
        "code": proc.returncode,
        "stdout": proc.stdout or "",
        "stderr": proc.stderr or "",
    }


def _format_run_result(result: Dict[str, Any], *, label: Optional[str] = None) -> str:
    lines: List[str] = []
    if label:
        lines.append(f"label: {label}")
    lines.append(f"kind: {result.get('kind')}")
    lines.append(f"cmd: {result.get('cmd')}")
    lines.append(f"cwd: {result.get('cwd')}")
    lines.append(f"exit: {result.get('code')}")
    stdout = str(result.get("stdout") or "").rstrip()
    stderr = str(result.get("stderr") or "").rstrip()
    if stdout:
        lines.append("stdout:")
        lines.append(stdout)
    if stderr:
        lines.append("stderr:")
        lines.append(stderr)
    return "\n".join(lines)


def _describe_runtime_target(url: str) -> tuple[str, str]:
    """Return human-readable runtime label and endpoint summary for status output."""

    if url.startswith("process://"):
        return "Local Runner", url.replace("process://", "", 1) or "runox"
    if url:
        return "Runtime", url
    return "Runtime", "unknown"


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

def _build_runtime_candidates(args: argparse.Namespace) -> List[RuntimeCandidate]:
    """Return the single local runner runtime candidate."""

    configured_model = (getattr(args, "model", None) or "").strip()
    if configured_model.lower() in {"none", "null"}:
        configured_model = ""
    if not configured_model:
        configured_model = "nox"

    return [
        RuntimeCandidate(
            url=CLI_DEFAULT_URL,
            model=configured_model,
            api_key=None,
            source="local runner",
        )
    ]


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

    def _resolve_noxdex_memory_root() -> Optional[Path]:
        override = (get_env("NOXDEX_MEMORY_HOME") or get_env("CODEX_MEMORY_HOME") or "").strip()
        if override:
            candidate = Path(override).expanduser()
            if candidate.exists():
                return candidate
        repo_root = Path(__file__).resolve().parents[1]
        candidate = repo_root / "experiments" / "noxdex" / "memory"
        if candidate.exists():
            return candidate
        return None

    def _sessions_for_root(candidate: Path) -> List[Dict[str, Any]]:
        try:
            return _sort_sessions(noxl_list_sessions(root=candidate))
        except Exception:
            return []

    noxdex_root = _resolve_noxdex_memory_root()
    if noxdex_root is not None:
        try:
            resolved_noxdex = noxdex_root.resolve()
        except Exception:
            resolved_noxdex = noxdex_root
        if resolved_noxdex not in seen_roots:
            sessions = _sessions_for_root(noxdex_root)
            if sessions:
                options.append(
                    MemoryOption(
                        key="noxdex",
                        label="NoxdEx (Codex)",
                        root=noxdex_root,
                        sessions=sessions,
                        aliases=("noxdex", "codex"),
                    )
                )
                seen_roots.add(resolved_noxdex)

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


def _resolve_memory_option(raw: str, options: List[MemoryOption]) -> Optional[MemoryOption]:
    key = (raw or "").strip().lower()
    if not key:
        return None
    for option in options:
        if key == option.key or key in option.aliases:
            return option
    return None


def _split_memory_prefix(raw: str, options: List[MemoryOption]) -> tuple[Optional[MemoryOption], str]:
    text = (raw or "").strip()
    if not text or ":" not in text:
        return None, text
    prefix, remainder = text.split(":", 1)
    option = _resolve_memory_option(prefix, options)
    if option is None:
        return None, text
    return option, remainder.strip()


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
            loaded = load_session_context(path)
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
    cwd = _resolve_cwd(getattr(args, "cwd", None))
    file_context, _ = _read_file_context(getattr(args, "files", []) or [], cwd=cwd)
    if getattr(args, "auto_run", None) is None:
        auto_run_env = (get_env("NOX_AUTO_RUN") or "").strip().lower()
        if auto_run_env:
            args.auto_run = auto_run_env in {"1", "true", "yes", "on"}
        else:
            args.auto_run = True

    if getattr(args, "version", False):
        print(__version__)
        return 0

    persona = resolve_persona(args.model)

    if getattr(args, "dev", False):
        dev_passphrase = resolve_dev_passphrase()
        interactive = sys.stdin.isatty() and get_env(NOX_DEV_PASSPHRASE_ATTEMPT_ENV) is None
        if not require_dev_passphrase(dev_passphrase, interactive=interactive):
            print(color("Developer mode locked.", fg="red", bold=True))
            return 1

    try:
        record_cli_run(resolve_memory_root(), __version__)
    except Exception:
        pass

    interactive = sys.stdin.isatty()
    if getattr(args, "stream", None) is None:
        args.stream = interactive
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

    hardware_info = hardware_summary()

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
    memory_options_cache: Optional[List[MemoryOption]] = None

    def get_memory_options() -> List[MemoryOption]:
        nonlocal memory_options_cache
        if memory_options_cache is None:
            memory_options_cache = _collect_memory_options(sessions_snapshot)
        return memory_options_cache

    def resolve_session_path(raw_ident: str) -> Optional[Path]:
        ident = (raw_ident or "").strip()
        if not ident:
            return None
        options = get_memory_options()
        memory_option, ident = _split_memory_prefix(ident, options)
        candidate = Path(ident).expanduser()
        if candidate.exists():
            return candidate
        if memory_option:
            return cmd_resolve_by_ident_or_index(ident, memory_option.sessions, root=memory_option.root)
        path = cmd_resolve_by_ident_or_index(ident, sessions_snapshot)
        if path:
            return path
        if ident.isdigit():
            return None
        for option in options:
            if option.key == "noctics":
                continue
            path = cmd_resolve_by_ident_or_index(ident, option.sessions, root=option.root)
            if path:
                return path
        return None
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
    if file_context and not args.messages_file:
        args.system = _append_file_context(args.system, file_context)

    session_path_to_adopt: Optional[Path] = None
    loaded_session_context = False
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
        if file_context:
            _apply_file_context_to_messages(messages, file_context=file_context)
    else:
        if args.sessions_load:
            path = resolve_session_path(str(args.sessions_load))
            if not path:
                raise SystemExit(f"--sessions-load: not found: {args.sessions_load}")
            loaded = load_session_context(path)
            if loaded:
                messages = loaded
                loaded_session_context = True
                sys_msgs = [m for m in messages if m.get("role") == "system"]
                if sys_msgs:
                    args.system = sys_msgs[0].get("content")
                    if args.system:
                        args.system = render_system_prompt(str(args.system), persona)
                        sys_msgs[0]["content"] = args.system
                if file_context:
                    _apply_file_context_to_messages(messages, file_context=file_context)
                    sys_msgs = [m for m in messages if m.get("role") == "system"]
                    args.system = sys_msgs[0].get("content") if sys_msgs else None
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
                loaded_session_context = True
                sys_msgs = [m for m in messages if m.get("role") == "system"]
                if sys_msgs:
                    args.system = sys_msgs[0].get("content")
                    if args.system:
                        args.system = render_system_prompt(str(args.system), persona)
                        sys_msgs[0]["content"] = args.system
                if file_context:
                    _apply_file_context_to_messages(messages, file_context=file_context)
                    sys_msgs = [m for m in messages if m.get("role") == "system"]
                    args.system = sys_msgs[0].get("content") if sys_msgs else None
        if not messages and args.system:
            messages.append({"role": "system", "content": args.system})

    context_turns: Optional[int] = None
    context_messages: Optional[int] = None
    if loaded_session_context:
        context_turns, context_messages = _resolve_session_context_limits()

    # Determine and display system prompt at startup (colored)
    sys_prompt_text: Optional[str] = None
    if args.messages_file:
        # Take the last system message if present
        sys_msgs = [m for m in messages if isinstance(m, dict) and m.get("role") == "system"]
        if sys_msgs:
            sys_prompt_text = str(sys_msgs[-1].get("content", "")).strip() or None
    else:
        sys_prompt_text = args.system

    # Keep system context minimal for local inference speed.

    hardware_brief = hardware_info.replace("OS: ", "").split(";")[0].strip()
    operator_name = identity.display_name

    runtime_meta = {
        "runtime": "",
        "endpoint": "",
        "model": str(args.model),
        "source": "configured",
        "runner_path": "",
        "model_path": "",
    }

    def update_runtime_meta(
        url: str,
        model: str,
        source: str,
        *,
        runner_path: Optional[str] = None,
        model_path: Optional[str] = None,
    ) -> None:
        runtime_label, runtime_endpoint = _describe_runtime_target(url)
        runtime_meta["runtime"] = runtime_label
        runtime_meta["endpoint"] = runtime_endpoint
        runtime_meta["model"] = str(model)
        runtime_meta["source"] = source
        if runner_path is not None:
            runtime_meta["runner_path"] = runner_path
        if model_path is not None:
            runtime_meta["model_path"] = model_path

    update_runtime_meta(CLI_DEFAULT_URL, args.model, "local runner")

    def print_status_block() -> None:
        if not interactive:
            return
        term_columns = shutil.get_terminal_size(fallback=(80, 24)).columns
        session_info = cmd_list_sessions()
        session_count = len(session_info)
        developer_display = ""
        if getattr(args, "dev", False):
            dev_identity = resolve_developer_identity()
            developer_display = dev_identity.display_name

        context = {
            "header": persona.central_name,
            "version": __version__,
            "operator": operator_name,
            "hardware": hardware_brief,
            "runtime": runtime_meta["runtime"],
            "runtime_source": runtime_meta["source"],
            "endpoint": runtime_meta["endpoint"],
            "model": runtime_meta["model"],
            "runner_path": runtime_meta["runner_path"] or "n/a",
            "model_path": runtime_meta["model_path"] or "n/a",
            "model_target": persona.model_target,
            "persona_central_name": persona.central_name,
            "persona_central_name_upper": persona.central_name.upper(),
            "persona_scale": persona.scale_label,
            "persona_variant_name": persona.variant_name,
            "persona_variant_display": persona.variant_display,
            "persona_tagline": persona.tagline,
            "tagline": persona.tagline,
            "sessions_saved": str(session_count),
            "developer_display": developer_display,
            "footer": f"{persona.central_name.upper()} · {persona.variant_display}",
            "logo_style_hint": persona.variant_name,
        }

        content_specs = build_hud_content(context, style_hint=persona.variant_name)

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

    show_sys_prompt = get_env("NOX_SHOW_SYSTEM_PROMPT") or ""
    if sys_prompt_text and show_sys_prompt.lower() in {"1", "true", "yes", "on"}:
        print(color("System Prompt:", fg="magenta", bold=True))
        print(color(sys_prompt_text, fg="magenta"))
        print()

    runtime_candidates = _build_runtime_candidates(args)
    connection_errors: List[tuple[RuntimeCandidate, Exception]] = []
    client: Optional[ChatClient] = None
    current_candidate_index = -1

    def activate_runtime(start_index: int, *, show_fallback: bool) -> bool:
        nonlocal client, persona, messages, current_candidate_index, args
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
                    api_key=None,
                    temperature=args.temperature,
                    max_tokens=args.max_tokens,
                    stream=bool(args.stream),
                    sanitize=bool(args.sanitize),
                    messages=base_messages,
                    enable_logging=True,
                    strip_reasoning=not bool(args.show_think),
                    memory_user=identity.user_id,
                    memory_user_display=identity.display_name,
                    context_turns=context_turns,
                    context_messages=context_messages,
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
            args.model = candidate.model
            runner_path = getattr(client.transport, "binary", "") or ""
            model_path = getattr(client.transport, "model_path", "") or ""
            update_runtime_meta(
                candidate.url,
                candidate.model,
                candidate.source,
                runner_path=runner_path,
                model_path=model_path,
            )

            if prior_log_path:
                try:
                    client.adopt_session_log(prior_log_path)
                except Exception:
                    pass
            messages = client.messages

            if (idx > start_index or show_fallback):
                label, endpoint = _describe_runtime_target(candidate.url)
                target_stream = sys.stdout if interactive else sys.stderr
                print(color(f"Runtime fallback engaged: {label} ({endpoint}).", fg="yellow"), file=target_stream)
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
    auto_run_depth = 0

    def handle_run_blocks(assistant_text: Optional[str]) -> tuple[Optional[str], bool]:
        nonlocal auto_run_depth
        if not assistant_text or not getattr(args, "auto_run", False):
            return assistant_text, False
        if auto_run_depth >= 1:
            return assistant_text, False
        blocks = _extract_instruction_blocks(assistant_text)
        if not blocks:
            return assistant_text, False

        cleaned = _strip_instruction_blocks(assistant_text)
        context_chunks: List[str] = []

        for block in blocks:
            kind = block.get("kind", "")
            content = block.get("content", "")
            if kind == "run":
                instructions = _parse_run_block(content)
            elif kind == "cmd":
                instructions = {
                    "cmds": [],
                    "py": [],
                    "cwd": None,
                    "env": {},
                    "use": "context",
                    "label": None,
                    "lang": None,
                }
                for raw_line in str(content).splitlines():
                    line = raw_line.strip()
                    if not line or line.startswith("#"):
                        continue
                    instructions["cmds"].append(line)
            elif kind == "py":
                instructions = {
                    "cmds": [],
                    "py": [],
                    "cwd": None,
                    "env": {},
                    "use": "context",
                    "label": None,
                    "lang": "py",
                }
                code = str(content).strip("\n")
                if code.strip():
                    instructions["py"] = code.splitlines()
            else:
                continue
            use_mode = (instructions.get("use") or "context").lower()
            if use_mode not in {"context", "print", "both", "none"}:
                use_mode = "context"

            try:
                run_cwd = _resolve_run_cwd(instructions.get("cwd"), base=cwd)
            except RuntimeError as exc:
                print(color(f"[run] {exc}", fg="red"))
                continue

            env = _build_run_env(instructions.get("env") or {})
            label = instructions.get("label")
            cmds: List[str] = instructions.get("cmds") or []
            py_lines: List[str] = instructions.get("py") or []
            lang = (instructions.get("lang") or "").lower()

            results: List[Dict[str, Any]] = []
            if lang == "py" or py_lines:
                code = "\n".join(py_lines).strip()
                if not code:
                    continue
                print(color(f"[run] python ({label or 'inline'})", fg="yellow"))
                results.append(_run_python_block(code, cwd=run_cwd, env=env))
            else:
                for cmd in cmds:
                    if not cmd.strip():
                        continue
                    print(color(f"[run] {cmd}", fg="yellow"))
                    results.append(_run_shell_command(cmd, cwd=run_cwd, env=env))

            if use_mode in {"print", "both", "context"}:
                for result in results:
                    formatted = _format_run_result(result, label=label)
                    print(color("[run output]", fg="yellow", bold=True))
                    print(formatted)

            if use_mode in {"context", "both"}:
                for result in results:
                    context_chunks.append(_format_run_result(result, label=label))

        if not context_chunks:
            return cleaned or assistant_text, False

        auto_run_depth += 1
        try:
            run_context = "[RUN RESULT]\n" + "\n\n".join(context_chunks) + "\n[/RUN RESULT]"
            previous_stream = client.stream
            if previous_stream:
                client.stream = False
            followup = client.one_turn(run_context)
        finally:
            client.stream = previous_stream
            auto_run_depth -= 1

        return followup, True

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

    def one_turn(user_text: str) -> Optional[str]:
        nonlocal client, current_candidate_index
        show_think = bool(args.show_think)
        assistant: Optional[str] = None

        codex_prompt = _extract_codex_prompt(user_text)
        if codex_prompt is not None:
            target_stream = sys.stdout if interactive else sys.stderr
            if not codex_prompt:
                print(color("Usage: @codex <message>", fg="yellow"), file=target_stream)
                return None
            if args.stream:
                print(f"{CODEX_LABEL}:", end=" ", flush=True)
            try:
                assistant = _run_noxdex(codex_prompt, stream=bool(args.stream))
            except Exception as exc:
                if args.stream:
                    print()
                print(color(f"Codex error: {exc}", fg="red"), file=target_stream)
                return None
            if args.stream:
                print()
            if not args.stream:
                print(f"{CODEX_LABEL}: {assistant}")
            if assistant:
                client.record_turn(user_text, f"[CODEX]\n{assistant}\n[/CODEX]")
            return assistant

        while True:
            stream_emit = None
            stream_finish = None

            try:
                if args.stream:
                    print(f"{ASSISTANT_LABEL}:", end=" ", flush=True)
                    stream_emit, stream_finish = _make_stream_printer(show_think)
                    assistant = client.one_turn(user_text, on_delta=stream_emit)
                else:
                    assistant = client.one_turn(user_text)
            except Exception as exc:
                if args.stream and stream_finish:
                    stream_finish()
                    print()
                failing_label, failing_endpoint = _describe_runtime_target(client.url or "")
                target_stream = sys.stdout if interactive else sys.stderr
                print(color(f"Runtime error ({failing_label} @ {failing_endpoint}): {exc}", fg="red"), file=target_stream)
                hint = (
                    "Ensure bin/runox and assets/models/nox.gguf are present "
                    "or set NOX_LOCAL_RUNNER/NOX_MODEL_PATH."
                )
                print(color(hint, fg="yellow"), file=target_stream)
                next_index = current_candidate_index + 1 if current_candidate_index >= 0 else 0
                if not activate_runtime(next_index, show_fallback=True):
                    print(color("Request failed:", fg="red", bold=True), file=target_stream)
                    print(color(f"{exc}", fg="red"), file=target_stream)
                    print(
                        color(
                            "Nox could not process the request. Ensure the model endpoint is available and try again.",
                            fg="yellow",
                        ),
                        file=target_stream,
                    )
                    return None
                print(color("Retrying request with fallback runtime…", fg="yellow"), file=target_stream)
                continue

            break

        if args.stream:
            if stream_finish:
                stream_finish()
            print()
            assistant, ran_followup = handle_run_blocks(assistant)
            handle_dev_shell_commands(assistant)
            assistant = handle_title_change(assistant)
            if ran_followup and assistant:
                display_text = assistant
                if show_think:
                    display_text, had_think = _extract_visible_reply(display_text)
                    if had_think:
                        print(color("[thinking…]", fg="yellow", bold=True))
                if display_text:
                    print(f"{ASSISTANT_LABEL}: {display_text}")
            return assistant

        if assistant is not None:
            assistant, _ = handle_run_blocks(assistant)
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
                    print()
                    print(f"{ASSISTANT_LABEL}: {display_text}")
        return assistant

    # Non-interactive one-shot mode (stdin is not a TTY).
    if not sys.stdin.isatty():
        initial_text: Optional[str] = args.user
        if not initial_text:
            piped = sys.stdin.read().strip()
            if piped:
                initial_text = piped

        if initial_text:
            initial_text = prepare_first_prompt_text(initial_text, allow_interactive=False)
            print(f"{USER_LABEL}: {initial_text}")
            one_turn(initial_text)

        try:
            title = client.ensure_auto_title()
            if title:
                print(color(f"Saved session title: {title}", fg="yellow"))
        except Exception:
            pass
        return 0

    # Optional initial user message via flag (interactive)
    if args.user:
        initial_user = prepare_first_prompt_text(args.user, allow_interactive=False)
        print(f"{USER_LABEL}: {initial_user}")
        one_turn(initial_user)

    # Interactive loop
    show_help_env = get_env("NOX_SHOW_HELP") or ""
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
                if file_context:
                    _apply_file_context_to_messages(messages, file_context=file_context)
                client.set_messages(messages)
                context_turns, context_messages = _resolve_session_context_limits()
                client.context_turns = context_turns
                client.context_messages = context_messages
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
                if file_context:
                    _apply_file_context_to_messages(messages, file_context=file_context)
                client.set_messages(messages)
                context_turns, context_messages = _resolve_session_context_limits()
                client.context_turns = context_turns
                client.context_messages = context_messages
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

            prompt_text = prepare_first_prompt_text(prompt, allow_interactive=True)
            print()
            print(f"{USER_LABEL}: {prompt_text}")
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
def build_identity_context(display_name: str, project_name: str) -> str:
    return (
        f"Developer identity: {display_name} is the creator and maintainer of {project_name}. "
        "Address them by name, keep responses practical, and prioritise guidance that helps them evolve the assistant."
    )

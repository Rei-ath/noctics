#!/usr/bin/env python3
"""NoxdEx experiment: connect Nox memory logging to the Codex CLI."""

from __future__ import annotations

import argparse
import os
import shlex
import shutil
import subprocess
import sys
import threading
from pathlib import Path
from typing import Dict, List, Optional, Tuple

DEFAULT_SYSTEM_PROMPT = (
    "You are Codex, a coding instrument in the NoxdEx experiment.\n"
    "Be concise, practical, and show code when it helps."
)
DEFAULT_EMPTY_REPLY = "Codex returned no output."


def repo_root() -> Path:
    here = Path(__file__).resolve()
    for parent in (here.parent, *here.parents):
        if (parent / "pyproject.toml").exists() or (parent / ".git").exists():
            return parent
    return here.parents[2]


def resolve_memory_root(root: Path) -> Path:
    override = os.getenv("NOXDEX_MEMORY_HOME")
    if override:
        return Path(override).expanduser()
    return root / "experiments" / "noxdex" / "memory"


def ensure_core_path(root: Path) -> None:
    core_path = root / "core"
    if str(core_path) not in sys.path:
        sys.path.insert(0, str(core_path))


def resolve_codex_bin(override: Optional[str]) -> Optional[Path]:
    raw = (override or "").strip() or None
    if raw is None:
        raw = os.getenv("NOXDEX_CODEX_BIN") or os.getenv("CODEX_BIN")
    if raw:
        candidate = Path(raw).expanduser()
        if candidate.exists():
            return candidate
        resolved = shutil.which(str(candidate))
        if resolved:
            return Path(resolved)
    resolved = shutil.which("codex")
    return Path(resolved) if resolved else None


def resolve_codex_args(override: Optional[str]) -> List[str]:
    raw = (override or "").strip()
    if not raw:
        raw = (os.getenv("NOXDEX_CODEX_ARGS") or "").strip()
    if not raw:
        raw = (os.getenv("CODEX_ARGS") or "").strip()
    if not raw:
        return []
    try:
        return shlex.split(raw)
    except ValueError:
        return raw.split()


def resolve_codex_model_label(override: Optional[str]) -> str:
    if override and override.strip():
        return override.strip()
    env_value = (os.getenv("NOXDEX_CODEX_MODEL") or os.getenv("CODEX_MODEL") or "").strip()
    return env_value or "codex"


def resolve_codex_stdin(override: Optional[bool]) -> bool:
    if override is not None:
        return bool(override)
    raw = os.getenv("NOXDEX_CODEX_STDIN") or os.getenv("CODEX_STDIN") or ""
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def format_codex_args(args: List[str]) -> str:
    if not args:
        return "(none)"
    return " ".join(shlex.quote(arg) for arg in args)


def build_prompt(messages: List[Dict[str, str]]) -> str:
    lines: List[str] = []
    for msg in messages:
        role = str(msg.get("role") or "user").strip().lower()
        content = str(msg.get("content") or "").strip()
        if not content:
            continue
        if role == "system":
            label = "System"
        elif role == "assistant":
            label = "Assistant"
        else:
            label = "User"
        lines.append(f"{label}: {content}")
    lines.append("Assistant:")
    return "\n\n".join(lines)


def _drain_stderr(proc: subprocess.Popen, sink: List[str], verbose: bool) -> None:
    if proc.stderr is None:
        return
    for chunk in iter(lambda: proc.stderr.read(4096), ""):
        if not chunk:
            break
        sink.append(chunk)
        if verbose:
            sys.stderr.write(chunk)
            sys.stderr.flush()


def substitute_prompt_tokens(tokens: List[str], prompt: str) -> Tuple[List[str], bool]:
    replaced: List[str] = []
    used = False
    for token in tokens:
        if "{prompt}" in token:
            replaced.append(token.replace("{prompt}", prompt))
            used = True
        else:
            replaced.append(token)
    return replaced, used


def build_codex_command(
    prompt: str,
    *,
    codex_bin: Path,
    extra_args: List[str],
    use_stdin: bool,
) -> Tuple[List[str], Optional[str]]:
    cmd = [str(codex_bin)] + list(extra_args)
    cmd, used_placeholder = substitute_prompt_tokens(cmd, prompt)
    stdin_text: Optional[str] = None
    if not used_placeholder:
        if use_stdin:
            stdin_text = prompt
        else:
            cmd.append(prompt)
    return cmd, stdin_text


def run_codex(
    *,
    prompt: str,
    codex_bin: Path,
    codex_args: List[str],
    use_stdin: bool,
    stream: bool,
    verbose: bool,
) -> Tuple[str, str]:
    cmd, stdin_text = build_codex_command(
        prompt,
        codex_bin=codex_bin,
        extra_args=codex_args,
        use_stdin=use_stdin,
    )
    proc = subprocess.Popen(
        cmd,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
    )
    if proc.stdin is None or proc.stdout is None or proc.stderr is None:
        raise RuntimeError("Codex CLI streams are unavailable.")

    stderr_chunks: List[str] = []
    stderr_thread = threading.Thread(
        target=_drain_stderr,
        args=(proc, stderr_chunks, verbose),
        daemon=True,
    )
    stderr_thread.start()

    if stdin_text:
        proc.stdin.write(stdin_text)
    proc.stdin.close()

    pieces: List[str] = []
    if stream:
        for chunk in iter(lambda: proc.stdout.read(1), ""):
            if not chunk:
                break
            pieces.append(chunk)
            sys.stdout.write(chunk)
            sys.stdout.flush()
        sys.stdout.write("\n")
        sys.stdout.flush()
    else:
        stdout_text = proc.stdout.read()
        if stdout_text:
            pieces.append(stdout_text)

    code = proc.wait()
    stderr_thread.join(timeout=0.5)
    stderr_text = "".join(stderr_chunks).strip()
    if code != 0:
        message = stderr_text or "".join(pieces).strip() or "unknown error"
        raise RuntimeError(f"Codex CLI exited with {code}: {message}")

    return "".join(pieces).strip(), stderr_text


def normalize_reply(reply: str, fallback: str) -> str:
    cleaned = (reply or "").strip()
    return cleaned if cleaned else fallback


def ensure_system_message(messages: List[Dict[str, str]], system_text: str) -> None:
    if messages and messages[0].get("role") == "system":
        messages[0]["content"] = system_text
    else:
        messages.insert(0, {"role": "system", "content": system_text})


def resolve_session_path(ident: str) -> Optional[Path]:
    items = list_sessions()
    if ident.isdigit():
        idx = int(ident)
        if 1 <= idx <= len(items):
            path = items[idx - 1].get("path")
            return Path(path) if isinstance(path, str) else None
    return resolve_session(ident)


def print_sessions(items: List[Dict[str, object]]) -> None:
    if not items:
        print("No sessions found.")
        return
    for idx, info in enumerate(items, 1):
        display = info.get("display_name") or info.get("id") or "session"
        title = info.get("title") or "(untitled)"
        path = info.get("path") or "?"
        print(f"{idx:>2}. {display}  {title}")
        print(f"    id: {info.get('id')}")
        print(f"    path: {path}")


def select_starting_session(
    *,
    load_id: Optional[str],
    prefer_resume: bool,
    logger: "SessionLogger",
) -> Tuple[List[Dict[str, str]], Optional[Path]]:
    if load_id:
        path = resolve_session_path(load_id)
        if path is None:
            raise RuntimeError(f"No session matches '{load_id}'.")
        logger.load_existing(path)
        return load_session_context(path), path

    if prefer_resume:
        items = list_sessions()
        if items:
            path = items[0].get("path")
            if isinstance(path, str):
                path_obj = Path(path)
                logger.load_existing(path_obj)
                return load_session_context(path_obj), path_obj

    logger.start()
    return [], None


def prompt_help() -> None:
    print(
        "Commands:\n"
        "  /help             show this help\n"
        "  /sessions         list saved sessions\n"
        "  /load ID          load a saved session (by id or index)\n"
        "  /new              start a new session\n"
        "  /exit             quit"
    )


def print_status_block(title: str, lines: List[str]) -> None:
    if not sys.stdin.isatty():
        return
    content = [line for line in ([title] + lines) if line]
    if not content:
        return
    width = max(len(line) for line in content)
    border = "+" + "-" * (width + 2) + "+"
    print(border)
    for line in content:
        print(f"| {line.ljust(width)} |")
    print(border)


def chat_loop(
    *,
    args: argparse.Namespace,
    codex_bin: Path,
    codex_args: List[str],
    model_label: str,
    memory_root: Path,
) -> int:
    logger = SessionLogger(model=model_label, sanitized=False)
    messages, session_path = select_starting_session(
        load_id=args.load,
        prefer_resume=not args.new,
        logger=logger,
    )
    ensure_system_message(messages, args.system)
    if session_path:
        print(f"Resumed session: {session_path.stem}")
    else:
        print("Started new session.")

    status_lines = [
        f"Codex CLI : {codex_bin}",
        f"Codex Args: {format_codex_args(codex_args)}",
        f"Model     : {model_label}",
        f"Memory    : {memory_root}",
    ]
    print_status_block("NoxdEx (experiment)", status_lines)
    print("Type /help for commands.")

    title_set = bool(logger.get_title())
    stream = bool(args.stream) and not args.wrap

    while True:
        try:
            user_text = input("you> ").strip()
        except EOFError:
            print()
            break
        if not user_text:
            continue
        if user_text.startswith("/"):
            command, *rest = user_text.split(maxsplit=1)
            if command in {"/exit", "/quit"}:
                break
            if command == "/help":
                prompt_help()
                continue
            if command == "/sessions":
                print_sessions(list_sessions())
                continue
            if command == "/load":
                if not rest:
                    print("Usage: /load ID")
                    continue
                ident = rest[0].strip()
                path = resolve_session_path(ident)
                if path is None:
                    print(f"No session matches '{ident}'.")
                    continue
                messages = load_session_context(path)
                ensure_system_message(messages, args.system)
                logger.load_existing(path)
                session_path = path
                title_set = bool(logger.get_title())
                print(f"Loaded session: {path.stem}")
                continue
            if command == "/new":
                logger = SessionLogger(model=model_label, sanitized=False)
                logger.start()
                messages = [{"role": "system", "content": args.system}]
                session_path = None
                title_set = False
                print("Started new session.")
                continue
            print("Unknown command. Type /help for options.")
            continue

        messages.append({"role": "user", "content": user_text})
        prompt = build_prompt(messages)
        if stream:
            print("codex: ", end="", flush=True)
        reply, _ = run_codex(
            prompt=prompt,
            codex_bin=codex_bin,
            codex_args=codex_args,
            use_stdin=bool(args.codex_stdin),
            stream=stream,
            verbose=bool(args.verbose),
        )
        used_fallback = not bool(reply)
        assistant_text = normalize_reply(reply, DEFAULT_EMPTY_REPLY)
        display_text = assistant_text
        if args.wrap:
            display_text = f"[INSTRUMENT RESULT]\n{assistant_text}\n[/INSTRUMENT RESULT]"
        messages.append({"role": "assistant", "content": assistant_text})
        logger.log_turn(
            [
                {"role": "system", "content": messages[0]["content"]},
                {"role": "user", "content": user_text},
                {"role": "assistant", "content": assistant_text},
            ]
        )
        if not stream:
            print(f"codex: {display_text}")
        elif used_fallback:
            print(f"codex: {display_text}")
        if not title_set:
            title = compute_title_from_messages(messages)
            if title:
                logger.set_title(title, custom=False)
                title_set = True

    return 0


def one_shot(
    *,
    args: argparse.Namespace,
    codex_bin: Path,
    codex_args: List[str],
    model_label: str,
    prompt_text: str,
) -> int:
    logger = SessionLogger(model=model_label, sanitized=False)
    messages, _ = select_starting_session(
        load_id=args.load,
        prefer_resume=not args.new,
        logger=logger,
    )
    ensure_system_message(messages, args.system)
    messages.append({"role": "user", "content": prompt_text})
    prompt = build_prompt(messages)
    reply, _ = run_codex(
        prompt=prompt,
        codex_bin=codex_bin,
        codex_args=codex_args,
        use_stdin=bool(args.codex_stdin),
        stream=bool(args.stream) and not args.wrap,
        verbose=bool(args.verbose),
    )
    assistant_text = normalize_reply(reply, DEFAULT_EMPTY_REPLY)
    display_text = assistant_text
    if args.wrap:
        display_text = f"[INSTRUMENT RESULT]\n{assistant_text}\n[/INSTRUMENT RESULT]"
    logger.log_turn(
        [
            {"role": "system", "content": messages[0]["content"]},
            {"role": "user", "content": prompt_text},
            {"role": "assistant", "content": assistant_text},
        ]
    )
    title = compute_title_from_messages(messages)
    if title and not logger.get_title():
        logger.set_title(title, custom=False)
    if not args.stream or args.wrap:
        print(display_text)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="NoxdEx (experiment): Codex CLI bridge.",
    )
    parser.add_argument(
        "prompt",
        nargs="*",
        help="Prompt to send (omit for interactive mode).",
    )
    parser.add_argument(
        "--system",
        default=None,
        help="System prompt for Codex (default: built-in).",
    )
    parser.add_argument(
        "--system-file",
        default=None,
        help="Load system prompt from a file.",
    )
    parser.add_argument(
        "--codex-bin",
        default=None,
        help="Path to the codex CLI (defaults to 'codex' in PATH).",
    )
    parser.add_argument(
        "--codex-args",
        default=None,
        help="Extra codex CLI args (use {prompt} placeholder if needed).",
    )
    parser.add_argument(
        "--codex-model",
        default=None,
        help="Model label to record in the session log.",
    )
    parser.add_argument(
        "--codex-stdin",
        dest="codex_stdin",
        action="store_true",
        default=None,
        help="Send the prompt over stdin instead of as an argument.",
    )
    parser.add_argument(
        "--stream",
        action="store_true",
        help="Stream Codex output while generating.",
    )
    parser.add_argument(
        "--wrap",
        action="store_true",
        help="Wrap output in [INSTRUMENT RESULT] ... [/INSTRUMENT RESULT].",
    )
    parser.add_argument(
        "--load",
        default=None,
        help="Load a session by id or index before prompting.",
    )
    parser.add_argument(
        "--new",
        action="store_true",
        help="Start a new session instead of resuming the latest.",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Print codex stderr (warnings, debug logs, etc.).",
    )
    return parser


def main() -> int:
    root = repo_root()
    memory_root = resolve_memory_root(root)
    os.environ.setdefault("NOCTICS_MEMORY_HOME", str(memory_root))
    memory_root.mkdir(parents=True, exist_ok=True)

    ensure_core_path(root)
    global SessionLogger, compute_title_from_messages, list_sessions, load_session_context, resolve_session
    from interfaces.session_logger import SessionLogger
    from noxl import compute_title_from_messages, list_sessions, load_session_context, resolve_session

    parser = build_parser()
    args = parser.parse_args()

    if args.system_file:
        system_path = Path(args.system_file).expanduser()
        if not system_path.exists():
            print(f"System prompt file not found: {system_path}", file=sys.stderr)
            return 1
        args.system = system_path.read_text(encoding="utf-8").strip()
    if not args.system:
        args.system = DEFAULT_SYSTEM_PROMPT

    codex_bin = resolve_codex_bin(args.codex_bin)
    if codex_bin is None:
        print("Codex CLI not found. Install codex or set NOXDEX_CODEX_BIN.", file=sys.stderr)
        return 1
    codex_args = resolve_codex_args(args.codex_args)
    args.codex_stdin = resolve_codex_stdin(args.codex_stdin)
    model_label = resolve_codex_model_label(args.codex_model)

    prompt_text = " ".join(args.prompt).strip()
    if prompt_text:
        return one_shot(
            args=args,
            codex_bin=codex_bin,
            codex_args=codex_args,
            model_label=model_label,
            prompt_text=prompt_text,
        )
    return chat_loop(
        args=args,
        codex_bin=codex_bin,
        codex_args=codex_args,
        model_label=model_label,
        memory_root=memory_root,
    )


if __name__ == "__main__":
    raise SystemExit(main())

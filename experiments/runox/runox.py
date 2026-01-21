#!/usr/bin/env python3
"""Runox experiment: local runox CLI using nox.gguf."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import threading
from pathlib import Path
from typing import Dict, List, Optional, Tuple

DEFAULT_SYSTEM_PROMPT = (
    "You are Nox, a general-purpose local assistant.\n"
    "Be concise, friendly, and practical. If the user seems down, respond with empathy "
    "and a gentle follow-up question."
)
DEFAULT_EMPTY_REPLY = "I'm here. Want to tell me more?"


def repo_root() -> Path:
    here = Path(__file__).resolve()
    for parent in (here.parent, *here.parents):
        if (parent / "pyproject.toml").exists() or (parent / ".git").exists():
            return parent
    return here.parents[2]


def resolve_memory_root(root: Path) -> Path:
    override = os.getenv("RUNOX_MEMORY_HOME")
    if override:
        return Path(override).expanduser()
    return root / "experiments" / "runox" / "memory"


def ensure_core_path(root: Path) -> None:
    core_path = root / "core"
    if str(core_path) not in sys.path:
        sys.path.insert(0, str(core_path))


def resolve_runner_path(root: Path) -> Optional[Path]:
    env_path = os.getenv("NOX_LOCAL_RUNNER")
    if env_path:
        candidate = Path(env_path).expanduser()
        if candidate.exists():
            return candidate
    candidates = [
        root / "bin" / "runox",
        root / "noxpy" / "runox" / "runox",
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None


def resolve_model_path(root: Path) -> Optional[Path]:
    env_path = os.getenv("NOX_MODEL_PATH")
    if env_path:
        candidate = Path(env_path).expanduser()
        if candidate.exists():
            return candidate
    default = root / "assets" / "models" / "nox.gguf"
    if default.exists():
        return default
    return None


def build_chatml(messages: List[Dict[str, str]]) -> str:
    blocks: List[str] = []
    for msg in messages:
        role = str(msg.get("role") or "user").strip() or "user"
        content = str(msg.get("content") or "").strip()
        if not content:
            continue
        blocks.append(f"<|im_start|>{role}\n{content}\n<|im_end|>")
    blocks.append("<|im_start|>assistant\n")
    return "\n".join(blocks)


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


def run_nox(
    *,
    prompt: str,
    runner: Path,
    model: Optional[Path],
    max_tokens: int,
    ctx: int,
    temp: float,
    top_p: float,
    top_k: int,
    stream: bool,
    verbose: bool,
) -> Tuple[str, str]:
    cmd = [
        str(runner),
        "-raw",
        "-max-tokens",
        str(max_tokens),
        "-ctx",
        str(ctx),
        "-temp",
        str(temp),
        "-top-p",
        str(top_p),
        "-top-k",
        str(top_k),
    ]
    if model is not None:
        cmd.extend(["-model", str(model)])

    proc = subprocess.Popen(
        cmd,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
    )
    if proc.stdin is None or proc.stdout is None or proc.stderr is None:
        raise RuntimeError("Runner I/O streams are unavailable.")

    stderr_chunks: List[str] = []
    stderr_thread = threading.Thread(
        target=_drain_stderr,
        args=(proc, stderr_chunks, verbose),
        daemon=True,
    )
    stderr_thread.start()

    proc.stdin.write(prompt)
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
        message = stderr_text or "unknown error"
        raise RuntimeError(f"Runner exited with {code}: {message}")

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
    runner: Path,
    model: Optional[Path],
    memory_root: Path,
) -> int:
    model_label = model.name if model is not None else "runox"
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
        f"Runner: {runner}",
        f"Model : {model}",
        f"Memory: {memory_root}",
    ]
    print_status_block("Runox (experiment)", status_lines)
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
        prompt = build_chatml(messages)
        if stream:
            print("runox: ", end="", flush=True)
        reply, _ = run_nox(
            prompt=prompt,
            runner=runner,
            model=model,
            max_tokens=args.max_tokens,
            ctx=args.ctx,
            temp=args.temp,
            top_p=args.top_p,
            top_k=args.top_k,
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
            print(f"runox: {display_text}")
        elif used_fallback:
            print(f"runox: {display_text}")
        if not title_set:
            title = compute_title_from_messages(messages)
            if title:
                logger.set_title(title, custom=False)
                title_set = True

    return 0


def one_shot(
    *,
    args: argparse.Namespace,
    runner: Path,
    model: Optional[Path],
    prompt_text: str,
) -> int:
    model_label = model.name if model is not None else "runox"
    logger = SessionLogger(model=model_label, sanitized=False)
    messages, _ = select_starting_session(
        load_id=args.load,
        prefer_resume=not args.new,
        logger=logger,
    )
    ensure_system_message(messages, args.system)
    messages.append({"role": "user", "content": prompt_text})
    prompt = build_chatml(messages)
    reply, _ = run_nox(
        prompt=prompt,
        runner=runner,
        model=model,
        max_tokens=args.max_tokens,
        ctx=args.ctx,
        temp=args.temp,
        top_p=args.top_p,
        top_k=args.top_k,
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
        description="Runox (experiment): local runox runner.",
    )
    parser.add_argument(
        "prompt",
        nargs="*",
        help="Prompt to send (omit for interactive mode).",
    )
    parser.add_argument(
        "--system",
        default=None,
        help="System prompt for Nox (default: built-in).",
    )
    parser.add_argument(
        "--system-file",
        default=None,
        help="Load system prompt from a file.",
    )
    parser.add_argument(
        "--runner",
        default=None,
        help="Path to the runox runner (defaults to bin/runox).",
    )
    parser.add_argument(
        "--model",
        default=None,
        help="Path to the GGUF model (defaults to assets/models/nox.gguf).",
    )
    parser.add_argument("--max-tokens", type=int, default=256, help="Maximum tokens to generate.")
    parser.add_argument("--ctx", type=int, default=1024, help="Context length.")
    parser.add_argument("--temp", type=float, default=0.4, help="Sampling temperature.")
    parser.add_argument("--top-p", type=float, default=0.9, help="Top-p sampling.")
    parser.add_argument("--top-k", type=int, default=40, help="Top-k sampling.")
    parser.add_argument(
        "--stream",
        action="store_true",
        help="Stream output while generating.",
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
        help="Print runner stderr (model load, warnings, etc.).",
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

    runner = Path(args.runner).expanduser() if args.runner else resolve_runner_path(root)
    if runner is None or not runner.exists():
        print("Runner not found. Build bin/runox or set NOX_LOCAL_RUNNER.", file=sys.stderr)
        return 1
    model = Path(args.model).expanduser() if args.model else resolve_model_path(root)
    if model is None or not model.exists():
        print("Model not found. Ensure assets/models/nox.gguf is present or set NOX_MODEL_PATH.", file=sys.stderr)
        return 1

    prompt_text = " ".join(args.prompt).strip()
    if prompt_text:
        return one_shot(args=args, runner=runner, model=model, prompt_text=prompt_text)
    return chat_loop(args=args, runner=runner, model=model, memory_root=memory_root)


if __name__ == "__main__":
    raise SystemExit(main())

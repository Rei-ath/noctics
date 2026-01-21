"""Minimal Chat CLI that ships with the public core package.

This lightweight interface keeps the core repository runnable without the
full noctics_cli multitool. It supports a basic prompt loop, streaming output,
and optional system prompt loading so downstream projects can embed or invoke
the chat client directly.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Iterable, List, Optional, Sequence, Set

PACKAGE_ROOT = Path(__file__).resolve().parents[2]
PROJECT_ROOT = PACKAGE_ROOT.parent
for candidate in (PROJECT_ROOT, PACKAGE_ROOT):
    if candidate.is_dir():
        path_str = str(candidate)
        if path_str not in sys.path:
            sys.path.append(path_str)

from central.colors import color
from central.core import ChatClient
from central.persona import PERSONA_CATALOG, render_system_prompt, resolve_persona

SUPPORTED_MODELS: List[str] = sorted(
    {
        persona.central_name
        for persona in PERSONA_CATALOG.values()
        if persona.central_name
    }
)


def _build_system_prompt(candidate: Optional[str], model: str) -> Optional[str]:
    if candidate:
        return render_system_prompt(candidate, resolve_persona(model))

    search_paths = [
        Path("memory/system_prompt.local.md"),
        Path("memory/system_prompt.local.txt"),
        Path("memory/system_prompt.md"),
        Path("memory/system_prompt.txt"),
    ]
    for path in search_paths:
        try:
            if path.exists():
                text = path.read_text(encoding="utf-8").strip()
                if text:
                    return render_system_prompt(text, resolve_persona(model))
        except OSError:
            continue
    return None


def _env(key: str) -> Optional[str]:
    return os.environ.get(key)


def _require_env(key: str) -> str:
    value = os.environ.get(key)
    if value:
        return value
    raise SystemExit(f"Environment variable {key} must be set or passed via CLI flags.")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="nox-core-chat",
        description="Lightweight interactive CLI for the Nox core ChatClient.",
    )
    parser.add_argument("--url", default=_env("NOX_LLM_URL"), help="Target inference endpoint URL.")
    parser.add_argument("--model", default=_env("NOX_LLM_MODEL"), help="Model alias or persona scale.")
    parser.add_argument("--system", default=None, help="Override system prompt text.")
    parser.add_argument("--temperature", type=float, default=0.7, help="Sampling temperature.")
    parser.add_argument("--max-tokens", type=int, default=-1, help="Maximum response tokens (-1 for backend default).")
    parser.add_argument(
        "--stream",
        action="store_true",
        help="Enable streaming responses (prints tokens as they arrive).",
    )
    parser.add_argument(
        "--no-stream",
        dest="stream",
        action="store_false",
        help="Disable streaming responses (default).",
    )
    parser.set_defaults(stream=False)
    parser.add_argument(
        "--sanitize",
        action="store_true",
        help="Apply built-in PII scrubbing to user text before sending.",
    )
    parser.add_argument("--user", default=None, help="Optional single-turn user prompt before exiting.")
    parser.add_argument(
        "--show-config",
        action="store_true",
        help="Print the resolved runtime configuration before chatting.",
    )
    parser.add_argument(
        "--list-models",
        action="store_true",
        help="List installed Noctics model aliases and exit.",
    )
    return parser


def parse_args(argv: Optional[Sequence[str]]) -> argparse.Namespace:
    parser = build_parser()
    return parser.parse_args(list(argv) if argv is not None else None)


def _print_assistant_reply(reply: Optional[str]) -> None:
    if not reply:
        return
    print(color("assistant:", fg="magenta", bold=True))
    print(reply)


def _print_streaming_reply(client: ChatClient, prompt: str) -> None:
    buffer: List[str] = []

    def _emit(delta: str) -> None:
        if not delta:
            return
        buffer.append(delta)
        print(delta, end="", flush=True)

    reply = client.one_turn(prompt, on_delta=_emit)
    if reply and not reply.endswith("\n"):
        print()
    if not buffer:
        _print_assistant_reply(reply)


def _resolve_ollama_binary() -> Optional[str]:
    explicit = os.environ.get("OLLAMA_BIN")
    if explicit:
        explicit_path = Path(explicit)
        if explicit_path.exists():
            return str(explicit_path)
        detected = shutil.which(explicit)
        if detected:
            return detected
    detected_default = shutil.which("ollama")
    if detected_default:
        return detected_default
    assets_bin = PROJECT_ROOT / "assets" / "ollama" / "bin" / "ollama"
    if assets_bin.exists():
        return str(assets_bin)
    return None


def _parse_ollama_json(raw: str) -> Set[str]:
    names: Set[str] = set()
    raw = raw.strip()
    if not raw:
        return names
    try:
        data = json.loads(raw)
        if isinstance(data, dict) and "models" in data:
            items: Iterable[dict] = data.get("models", [])  # type: ignore[assignment]
        elif isinstance(data, list):
            items = data  # type: ignore[assignment]
        else:
            items = []
        for item in items:
            if isinstance(item, dict):
                name = item.get("name")
                if isinstance(name, str):
                    names.add(name)
        if names:
            return names
    except json.JSONDecodeError:
        pass
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict):
            name = obj.get("name")
            if isinstance(name, str):
                names.add(name)
    return names


def _installed_ollama_models() -> Optional[Set[str]]:
    binary = _resolve_ollama_binary()
    if not binary:
        return None
    try:
        proc = subprocess.run(
            [binary, "list", "--json"],
            check=True,
            capture_output=True,
            text=True,
        )
        names = _parse_ollama_json(proc.stdout)
        if names:
            return names
    except (subprocess.CalledProcessError, FileNotFoundError):
        pass
    try:
        proc = subprocess.run(
            [binary, "list"],
            check=True,
            capture_output=True,
            text=True,
        )
    except (subprocess.CalledProcessError, FileNotFoundError):
        return set()
    names: Set[str] = set()
    for line in proc.stdout.splitlines():
        if not line or line.lower().startswith("name"):
            continue
        parts = line.split()
        if parts:
            names.add(parts[0].strip())
    return names


def _show_installed_models() -> int:
    print(color("Noctics model aliases:", fg="yellow", bold=True))
    names = _installed_ollama_models()
    if names is None:
        print("  ollama binary not found; unable to inspect models.")
        return 1
    if not names:
        print("  (no models detected yet)")
    for alias in SUPPORTED_MODELS:
        status = "installed" if alias in names else "missing"
        fg = "green" if status == "installed" else "red"
        print(f"  {alias:<12} " + color(status, fg=fg))
    return 0


def _print_runtime_config(client: ChatClient) -> None:
    info = client.describe_target()
    print(color("Runtime configuration:", fg="yellow", bold=True))
    for key in (
        "url",
        "model",
        "target_model",
        "central_name",
        "central_scale",
        "noctics_variant",
        "temperature",
        "max_tokens",
        "stream",
        "sanitize",
    ):
        print(f"  {key}: {info.get(key)}")
    print()


def _print_command_help() -> None:
    commands = {
        "/help": "Show this help message.",
        "/config": "Display the current runtime configuration.",
        "/models": "List installed Noctics model aliases.",
        "/reset": "Clear conversation history and keep the system prompt.",
        "/exit": "Exit the CLI.",
    }
    print(color("Slash commands:", fg="yellow", bold=True))
    for name, desc in commands.items():
        print(f"  {name:<8} {desc}")
    print()


def _handle_slash_command(
    line: str,
    *,
    client: ChatClient,
    initial_system: Optional[str],
) -> Optional[bool]:
    tokens = line.strip().split()
    if not tokens:
        return True
    command = tokens[0].lower()
    if command in {"/exit", "/quit"}:
        return False
    if command == "/help":
        _print_command_help()
        return True
    if command == "/config":
        _print_runtime_config(client)
        return True
    if command in {"/models", "/list-models"}:
        _show_installed_models()
        return True
    if command == "/reset":
        client.reset_messages(system=initial_system)
        print(color("Context reset.", fg="yellow"))
        return True
    print(color(f"Unknown command: {tokens[0]}", fg="red"))
    return True


def _run_interactive(client: ChatClient, initial_system: Optional[str]) -> int:
    print(color("Type '/help' for commands, '/exit' to quit.", fg="yellow"))
    while True:
        try:
            prompt = input(color("you: ", fg="cyan", bold=True))
        except EOFError:
            print()
            break
        except KeyboardInterrupt:
            print("\n" + color("Interrupted.", fg="yellow"))
            break
        if not prompt:
            continue
        if prompt.startswith("/"):
            result = _handle_slash_command(
                prompt,
                client=client,
                initial_system=initial_system,
            )
            if result is False:
                break
            continue
        if client.stream:
            _print_streaming_reply(client, prompt)
        else:
            reply = client.one_turn(prompt)
            _print_assistant_reply(reply)
    return 0


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)

    if getattr(args, "list_models", False):
        return _show_installed_models()

    url = args.url or _require_env("NOX_LLM_URL")
    model = args.model or _require_env("NOX_LLM_MODEL")
    system_prompt = _build_system_prompt(args.system, model)

    messages = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})

    client = ChatClient(
        url=url,
        model=model,
        temperature=args.temperature,
        max_tokens=args.max_tokens,
        stream=bool(args.stream),
        sanitize=bool(args.sanitize),
        messages=messages,
        enable_logging=True,
    )

    if args.show_config:
        _print_runtime_config(client)

    if args.user:
        prompt = args.user.strip()
        if prompt:
            if client.stream:
                _print_streaming_reply(client, prompt)
            else:
                reply = client.one_turn(prompt)
                _print_assistant_reply(reply)
        return 0

    if not sys.stdin.isatty():
        data = sys.stdin.read().strip()
        if data:
            if client.stream:
                _print_streaming_reply(client, data)
            else:
                reply = client.one_turn(data)
                _print_assistant_reply(reply)
        return 0

    return _run_interactive(client, system_prompt)


__all__ = ["build_parser", "parse_args", "main"]

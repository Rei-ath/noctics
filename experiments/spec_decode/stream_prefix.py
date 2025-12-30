#!/usr/bin/env python3
import argparse
import subprocess
import sys
import threading
import time
from pathlib import Path


RS = b"\x1e"


def repo_root() -> Path:
    here = Path(__file__).resolve()
    for parent in (here.parent, *here.parents):
        if (parent / "pyproject.toml").exists() or (parent / ".git").exists():
            return parent
    return here.parents[2]


def resolve_path(path: str | None, fallback: Path) -> str:
    if path:
        return path
    return str(fallback)


def drain_stderr(proc: subprocess.Popen, verbose: bool) -> None:
    stream = proc.stderr
    if stream is None:
        return
    if not verbose:
        while stream.read(4096):
            pass
        return
    for chunk in iter(lambda: stream.read(4096), b""):
        sys.stderr.buffer.write(chunk)
        sys.stderr.buffer.flush()


def read_until_rs(proc: subprocess.Popen) -> bytes:
    out = bytearray()
    stream = proc.stdout
    if stream is None:
        return bytes(out)
    while True:
        ch = stream.read(1)
        if ch == b"":
            break
        if ch == RS:
            break
        out.extend(ch)
    return bytes(out)


def main() -> int:
    parser = argparse.ArgumentParser(description="Stream prefix prompts to noxlocal.")
    parser.add_argument(
        "text",
        nargs="?",
        default="hello. how are u",
        help="Text to send as growing prefixes",
    )
    parser.add_argument("--model", default=None, help="Path to GGUF model")
    parser.add_argument("--runner", default=None, help="Path to noxlocal binary")
    parser.add_argument("--ctx", type=int, default=128, help="Context length")
    parser.add_argument("--batch", type=int, default=1, help="Batch size")
    parser.add_argument("--max-tokens", type=int, default=2, help="Tokens per prefix")
    parser.add_argument("--temp", type=str, default="0", help="Temperature")
    parser.add_argument("--top-k", type=str, default="1", help="Top-k")
    parser.add_argument("--top-p", type=str, default="1", help="Top-p")
    parser.add_argument("--delay-ms", type=int, default=50, help="Delay between prefixes")
    parser.add_argument("--append", action="store_true", help="Append prompts (no reset)")
    parser.add_argument("--no-keep-cache", action="store_true", help="Disable keep-cache")
    parser.add_argument("--verbose", action="store_true", help="Stream stderr")

    args = parser.parse_args()

    root = repo_root()
    runner = resolve_path(args.runner, root / "bin" / "noxlocal")
    model = resolve_path(args.model, root / "assets" / "models" / "nox.gguf")

    cmd = [
        runner,
        "-serve",
        "-serve-rs",
        "-input-only",
        "-raw",
        "-ctx",
        str(args.ctx),
        "-batch",
        str(args.batch),
        "-max-tokens",
        str(args.max_tokens),
        "-temp",
        args.temp,
        "-top-k",
        args.top_k,
        "-top-p",
        args.top_p,
        "-model",
        model,
    ]
    if not args.no_keep_cache:
        cmd.append("-keep-cache")
    if args.append:
        cmd.append("-append")

    proc = subprocess.Popen(
        cmd,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        bufsize=0,
    )

    stderr_thread = threading.Thread(
        target=drain_stderr, args=(proc, args.verbose), daemon=True
    )
    stderr_thread.start()

    stdin = proc.stdin
    if stdin is None:
        print("noxlocal stdin unavailable", file=sys.stderr)
        return 1

    text = args.text
    delay = max(0, args.delay_ms) / 1000.0
    for i in range(1, len(text) + 1):
        prefix = text[:i].encode("utf-8")
        stdin.write(prefix + RS)
        stdin.flush()
        out = read_until_rs(proc).decode("utf-8", errors="replace")
        print(f"{i:02d} {text[:i]!r} => {out!r}")
        if delay:
            time.sleep(delay)

    stdin.write(b"exit" + RS)
    stdin.flush()
    proc.terminate()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

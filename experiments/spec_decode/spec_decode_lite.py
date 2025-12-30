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


def resolve_runner(root: Path, override: str | None) -> str:
    if override:
        return override
    candidates = [
        root / "bin" / "noxlocal",
        root / "noxpy" / "localrunner" / "noxlocal",
        root.parent / "noxpy" / "localrunner" / "noxlocal",
    ]
    for candidate in candidates:
        if candidate.exists():
            return str(candidate)
    return "noxlocal"


def drain_stderr(proc: subprocess.Popen) -> None:
    stream = proc.stderr
    if stream is None:
        return
    for chunk in iter(lambda: stream.read(4096), b""):
        sys.stderr.buffer.write(chunk)
        sys.stderr.buffer.flush()


def read_until_rs(proc: subprocess.Popen) -> str:
    out = bytearray()
    stream = proc.stdout
    if stream is None:
        return ""
    while True:
        ch = stream.read(1)
        if ch == b"" or ch == RS:
            break
        out.extend(ch)
    return out.decode("utf-8", errors="replace")


def start_runner(
    runner: str,
    model: str,
    ctx: int,
    batch: int,
    max_tokens: int,
    fast: bool,
) -> subprocess.Popen:
    cmd = [
        runner,
        "-serve",
        "-serve-rs",
        "-raw",
        "-keep-cache",
        "-max-tokens",
        str(max_tokens),
        "-ctx",
        str(ctx),
        "-batch",
        str(batch),
        "-model",
        model,
    ]
    if fast:
        cmd.append("-fast")
    proc = subprocess.Popen(
        cmd,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        bufsize=0,
    )
    threading.Thread(target=drain_stderr, args=(proc,), daemon=True).start()
    return proc


def send_prompt(proc: subprocess.Popen, prompt: str) -> str:
    stdin = proc.stdin
    if stdin is None:
        raise RuntimeError("stdin unavailable")
    stdin.write(prompt.encode("utf-8") + RS)
    stdin.flush()
    return read_until_rs(proc)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Speculative decoding (lite): small drafts, large verifies."
    )
    parser.add_argument("--runner", default=None, help="Path to noxlocal binary")
    parser.add_argument("--model-small", default=None, help="Path to small GGUF model")
    parser.add_argument("--model-large", default=None, help="Path to large GGUF model")
    parser.add_argument("--ctx", type=int, default=1024, help="Context length")
    parser.add_argument("--batch", type=int, default=32, help="Batch size")
    parser.add_argument("--draft", type=int, default=4, help="Draft tokens per step")
    parser.add_argument("--steps", type=int, default=3, help="Speculative steps")
    parser.add_argument("--no-fast", action="store_true", help="Disable -fast preset")
    parser.add_argument(
        "--verify-every",
        type=int,
        default=1,
        help="Verify every N steps (higher = faster but unsafe)",
    )
    parser.add_argument(
        "--prompt",
        default="Write one sentence about clouds.",
        help="Initial prompt",
    )
    args = parser.parse_args()

    root = repo_root()
    runner = resolve_runner(root, args.runner)
    tiny_default = root / "assets" / "models" / "tinyllama.gguf"
    model_small = args.model_small or (
        str(tiny_default) if tiny_default.exists() else str(root / "assets" / "models" / "nox.gguf")
    )
    model_large = args.model_large or str(root / "assets" / "models" / "mistral-7b-q4.gguf")

    fast = not args.no_fast
    small_proc = start_runner(runner, model_small, args.ctx, args.batch, args.draft, fast)
    large_proc = start_runner(runner, model_large, args.ctx, args.batch, args.draft, fast)

    prompt = args.prompt
    print("Prompt:", prompt)
    print("Draft per step:", args.draft)
    print("Verify every:", args.verify_every)

    agree_count = 0
    for step in range(1, args.steps + 1):
        start = time.perf_counter()
        draft = send_prompt(small_proc, prompt)
        small_time = time.perf_counter() - start

        verify = ""
        large_time = 0.0
        verified = (step % args.verify_every) == 0
        if verified:
            start = time.perf_counter()
            verify = send_prompt(large_proc, prompt)
            large_time = time.perf_counter() - start

        if not verified:
            chosen = draft
            decision = "skip-verify"
        elif draft == verify:
            chosen = draft
            decision = "agree"
            agree_count += 1
        else:
            chosen = verify
            decision = "disagree->large"

        print(
            f"{step:02d} draft={draft!r} verify={verify!r} => {decision} "
            f"(small={small_time:.2f}s large={large_time:.2f}s)"
        )
        prompt += chosen

    print(f"\nagreements: {agree_count}/{args.steps}")
    print(f"final prompt tail: {prompt[-80:]!r}")

    for proc in (small_proc, large_proc):
        try:
            if proc.stdin:
                proc.stdin.write(b"exit" + RS)
                proc.stdin.flush()
        except Exception:
            pass
        proc.terminate()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

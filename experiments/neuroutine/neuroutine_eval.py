#!/usr/bin/env python3
import argparse
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import BinaryIO

from neuroutine_controller import load_controller


RS = b"\x1e"
METRICS_PREFIX = b"NR|"


def repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


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


def send_prompt(proc: subprocess.Popen, prompt: str) -> str:
    stdin = proc.stdin
    if stdin is None:
        raise RuntimeError("stdin unavailable")
    stdin.write(prompt.encode("utf-8") + RS)
    stdin.flush()
    return read_until_rs(proc)


class MetricsReader(threading.Thread):
    def __init__(self, stream: BinaryIO | None, verbose: bool) -> None:
        super().__init__(daemon=True)
        self.stream = stream
        self.verbose = verbose
        self.queue: list[dict[str, float]] = []
        self.cv = threading.Condition()

    def run(self) -> None:
        if self.stream is None:
            return
        for line in iter(self.stream.readline, b""):
            if line.startswith(METRICS_PREFIX):
                parsed = parse_metrics(line)
                if parsed is not None:
                    with self.cv:
                        self.queue.append(parsed)
                        self.cv.notify()
            elif self.verbose:
                sys.stderr.buffer.write(line)
                sys.stderr.buffer.flush()

    def get(self, timeout: float) -> dict[str, float] | None:
        end = time.time() + timeout
        with self.cv:
            while not self.queue:
                remaining = end - time.time()
                if remaining <= 0:
                    return None
                self.cv.wait(timeout=remaining)
            return self.queue.pop(0)


def parse_metrics(line: bytes) -> dict[str, float] | None:
    try:
        text = line.decode("utf-8", errors="replace").strip()
        parts = text.split("|")
        if len(parts) < 5:
            return None
        return {
            "token": float(parts[1]),
            "max": float(parts[2]),
            "second": float(parts[3]),
            "margin": float(parts[4]),
        }
    except ValueError:
        return None

def start_runner(
    runner: str,
    model: str,
    ctx: int,
    batch: int,
    fast: bool,
    metrics: bool,
) -> subprocess.Popen:
    cmd = [
        runner,
        "-serve",
        "-serve-rs",
        "-raw",
        "-keep-cache",
        "-max-tokens",
        "1",
        "-ctx",
        str(ctx),
        "-batch",
        str(batch),
        "-model",
        model,
    ]
    if fast:
        cmd.append("-fast")
    if metrics:
        cmd.append("-metrics")
    return subprocess.Popen(
        cmd,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        bufsize=0,
    )


def load_prompts(args: argparse.Namespace) -> list[str]:
    if args.prompt:
        return [args.prompt]
    if args.prompts:
        return [
            line.strip()
            for line in Path(args.prompts).read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
    return ["hello"]


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate neuroutine gate accuracy + fallback rate.")
    parser.add_argument("--runner", default=None, help="Path to noxlocal binary")
    parser.add_argument("--model-small", default=None, help="Path to small GGUF model")
    parser.add_argument("--model-large", default=None, help="Path to large GGUF model")
    parser.add_argument("--ctx", type=int, default=1024, help="Context length")
    parser.add_argument("--batch", type=int, default=32, help="Batch size")
    parser.add_argument("--steps", type=int, default=8, help="Tokens per prompt")
    parser.add_argument("--no-fast", action="store_true", help="Disable -fast preset")
    parser.add_argument("--weights", default=None, help="Weights JSON (from neuroutine_train.py)")
    parser.add_argument("--accept-prob", type=float, default=0.5, help="Accept threshold when weights are provided")
    parser.add_argument("--margin-threshold", type=float, default=1.0, help="Margin threshold when no weights are provided")
    parser.add_argument("--prompt", default=None, help="Single prompt")
    parser.add_argument("--prompts", default=None, help="File with prompts (one per line)")
    parser.add_argument("--metrics-timeout", type=float, default=2.0, help="Seconds to wait for metrics")
    parser.add_argument("--verbose", action="store_true", help="Echo runner stderr")
    args = parser.parse_args()

    root = repo_root()
    runner = resolve_runner(root, args.runner)
    tiny_default = root / "assets" / "models" / "tinyllama.gguf"
    model_small = args.model_small or (
        str(tiny_default) if tiny_default.exists() else str(root / "assets" / "models" / "nox.gguf")
    )
    model_large = args.model_large or str(root / "assets" / "models" / "mistral-7b-q4.gguf")

    weights_path = Path(args.weights) if args.weights else Path("__missing__")
    controller = load_controller(
        weights_path,
        accept_prob=args.accept_prob,
        margin_threshold=args.margin_threshold,
    )

    fast = not args.no_fast
    small_proc = start_runner(runner, model_small, args.ctx, args.batch, fast, metrics=True)
    large_proc = start_runner(runner, model_large, args.ctx, args.batch, fast, metrics=False)

    metrics_reader = MetricsReader(small_proc.stderr, args.verbose)
    metrics_reader.start()

    prompts = load_prompts(args)
    total = 0
    accepted = 0
    wrong_accept = 0
    small_time = 0.0
    large_time = 0.0

    for prompt in prompts:
        current = prompt
        for _ in range(args.steps):
            start = time.perf_counter()
            draft = send_prompt(small_proc, current)
            small_time += time.perf_counter() - start

            metrics = metrics_reader.get(args.metrics_timeout) or {}
            accept, _score = controller.accept(metrics, draft)

            start = time.perf_counter()
            verify = send_prompt(large_proc, current)
            large_time += time.perf_counter() - start

            total += 1
            if accept:
                accepted += 1
                if draft != verify:
                    wrong_accept += 1

            if not verify:
                break
            current += verify

    for proc in (small_proc, large_proc):
        try:
            if proc.stdin:
                proc.stdin.write(b"exit" + RS)
                proc.stdin.flush()
        except Exception:
            pass
        proc.terminate()

    if total == 0:
        print("no samples")
        return 0

    accept_rate = accepted / total
    wrong_rate = wrong_accept / max(1, accepted)
    print(f"samples={total}")
    print(f"accept_rate={accept_rate:.3f}")
    print(f"wrong_accept_rate={wrong_rate:.3f}")
    print(f"small_time_s={small_time:.2f} large_time_s={large_time:.2f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

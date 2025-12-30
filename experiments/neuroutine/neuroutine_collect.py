#!/usr/bin/env python3
import argparse
import json
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import BinaryIO


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
    parser = argparse.ArgumentParser(description="Collect neuroutine gate training data.")
    parser.add_argument("--runner", default=None, help="Path to noxlocal binary")
    parser.add_argument("--model-small", default=None, help="Path to small GGUF model")
    parser.add_argument("--model-large", default=None, help="Path to large GGUF model")
    parser.add_argument("--ctx", type=int, default=1024, help="Context length")
    parser.add_argument("--batch", type=int, default=32, help="Batch size")
    parser.add_argument("--steps", type=int, default=8, help="Tokens per prompt")
    parser.add_argument("--no-fast", action="store_true", help="Disable -fast preset")
    parser.add_argument("--prompt", default=None, help="Single prompt")
    parser.add_argument("--prompts", default=None, help="File with prompts (one per line)")
    parser.add_argument("--out", default="data/neuroutine_train.jsonl", help="Output JSONL path")
    parser.add_argument("--include-prompt", action="store_true", help="Include full prompt text in rows")
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

    fast = not args.no_fast
    small_proc = start_runner(runner, model_small, args.ctx, args.batch, fast, metrics=True)
    large_proc = start_runner(runner, model_large, args.ctx, args.batch, fast, metrics=False)

    metrics_reader = MetricsReader(small_proc.stderr, args.verbose)
    metrics_reader.start()

    prompts = load_prompts(args)
    out_path = root / args.out
    out_path.parent.mkdir(parents=True, exist_ok=True)

    with out_path.open("w", encoding="utf-8") as handle:
        for prompt in prompts:
            current = prompt
            for step in range(1, args.steps + 1):
                draft = send_prompt(small_proc, current)
                metrics = metrics_reader.get(args.metrics_timeout) or {}
                verify = send_prompt(large_proc, current)

                label = int(draft == verify and draft != "")
                row = {
                    "prompt_len": len(current),
                    "step": step,
                    "draft": draft,
                    "verify": verify,
                    "label": label,
                    "metrics": metrics,
                    "token_len": len(draft),
                }
                if args.include_prompt:
                    row["prompt"] = current
                handle.write(json.dumps(row, ensure_ascii=True) + "\n")
                handle.flush()

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

    print(f"Wrote {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

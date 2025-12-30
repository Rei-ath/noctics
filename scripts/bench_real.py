#!/usr/bin/env python3
"""
Real-life-ish localrunner benchmark for Termux.

Runs a small suite of prompts and reports:
- TTFT (prefill + first token)
- generation throughput (tok/s, gen_ms)
- prefill speed estimate (prompt_tokens / prefill_ms)

This uses `noxpy/localrunner/noxlocal_dp` if present, else `noxlocal`.
"""

from __future__ import annotations

import argparse
import os
import re
import statistics
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List, Optional


ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class Bench:
    prompt_tokens: int
    generated_tokens: int
    prefill_ms: int
    gen_ms: int
    total_ms: int
    tok_s: float

    @property
    def ttft_ms(self) -> Optional[int]:
        # Only valid when generated_tokens >= 1 and max-tokens=1 was used.
        if self.generated_tokens < 1:
            return None
        return self.prefill_ms + self.gen_ms

    @property
    def prefill_tok_s(self) -> Optional[float]:
        if self.prefill_ms <= 0:
            return None
        return self.prompt_tokens / (self.prefill_ms / 1000.0)


BENCH_RE = re.compile(
    r"bench:\s+prompt_tokens=(?P<prompt>\d+)\s+generated_tokens=(?P<gen>\d+)\s+prefill_ms=(?P<prefill>\d+)\s+gen_ms=(?P<genms>\d+)\s+total_ms=(?P<total>\d+)\s+tok_s=(?P<toks>[0-9.]+)"
)


def find_runner(prefer_dotprod: bool) -> Path:
    dotprod = [
        ROOT / "bin" / "noxlocal_dp",
        ROOT / "noxpy" / "localrunner" / "noxlocal_dp",
    ]
    baseline = [
        ROOT / "bin" / "noxlocal",
        ROOT / "noxpy" / "localrunner" / "noxlocal",
    ]
    cand = dotprod + baseline if prefer_dotprod else baseline + dotprod
    for p in cand:
        if p.exists() and os.access(p, os.X_OK):
            return p
    raise SystemExit(
        "no localrunner binary found (expected bin/noxlocal[_dp] or noxpy/localrunner/noxlocal[_dp])"
    )


def mode_flags(mode: str) -> List[str]:
    if mode == "plain":
        return []
    if mode == "chat":
        return ["-chat"]
    if mode == "cot":
        return ["-chat", "-cot"]
    raise SystemExit(f"unknown mode: {mode}")


def run_once(
    *,
    runner: Path,
    model: str,
    prompt: str,
    threads: int,
    ctx: int,
    batch: int,
    max_tokens: int,
    mode: str,
    prepack: bool,
    kv_window: int,
) -> Bench:
    cmd = [
        str(runner),
        "-model",
        model,
        "-ctx",
        str(ctx),
        "-batch",
        str(batch),
        "-max-tokens",
        str(max_tokens),
        "-raw",
        "-fast",
        "-bench",
    ]
    if prepack:
        cmd.append("-prepack")
    if kv_window > 0:
        cmd.extend(["-kv-window", str(kv_window)])
    cmd.extend(mode_flags(mode))
    cmd.append(prompt)

    env = dict(os.environ)
    env["NOX_NUM_THREADS"] = str(threads)

    p = subprocess.run(cmd, env=env, capture_output=True, text=True)
    out = (p.stdout or "") + "\n" + (p.stderr or "")
    m = BENCH_RE.search(out)
    if not m:
        tail = "\n".join(out.splitlines()[-40:])
        raise RuntimeError(f"missing bench line (exit={p.returncode})\n{tail}")

    return Bench(
        prompt_tokens=int(m.group("prompt")),
        generated_tokens=int(m.group("gen")),
        prefill_ms=int(m.group("prefill")),
        gen_ms=int(m.group("genms")),
        total_ms=int(m.group("total")),
        tok_s=float(m.group("toks")),
    )


def mean_or_none(vals: Iterable[Optional[float]]) -> Optional[float]:
    items = [v for v in vals if v is not None]
    if not items:
        return None
    return float(statistics.mean(items))


def mean_int_or_none(vals: Iterable[Optional[int]]) -> Optional[int]:
    items = [v for v in vals if v is not None]
    if not items:
        return None
    return int(round(statistics.mean(items)))


def short_suite() -> List[tuple[str, str]]:
    return [
        ("greet", "Hello! Give a 1 sentence reply."),
        ("summ", "Summarize in 2 bullets: Mobile LLM inference is bandwidth-bound, not compute-bound."),
        ("code", "Write a small Python function that checks if a string is a palindrome."),
        ("plan", "Give a 5-step plan to learn Rust on a phone."),
        ("math", "Solve: What is 23*17?"),
    ]


def full_suite() -> List[tuple[str, str]]:
    long_text = (
        "You are given the following note. Summarize it for a busy engineer:\n\n"
        "On mobile, large language model inference is usually limited by memory bandwidth. "
        "Each generated token requires streaming large weight matrices from RAM for many matmul operations. "
        "Even if the model is memory-mapped and already cached, the CPU must repeatedly read those weights "
        "because the activation changes each token. KV cache grows with context and makes attention cost grow with "
        "sequence length. Improvements come from reducing bytes moved per token (quantization, sparsity), fusing "
        "kernels, and using the right thread count (too many threads can hurt on bandwidth-bound workloads)."
    )
    suite = short_suite()
    suite.insert(2, ("longsum", long_text))
    suite.append(("translate", "Translate to French: 'Speed matters, but smoothness matters more.'"))
    suite.append(("json", "Return a JSON object with keys: name, version, features (array of 3 strings)."))
    return suite


def parse_args(argv: List[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser("bench_real")
    p.add_argument("--model", default=str(ROOT / "nox" / "obb" / "nox.gguf"))
    p.add_argument("--mode", choices=["plain", "chat", "cot"], default="chat")
    p.add_argument("--suite", choices=["short", "full"], default="short")
    p.add_argument("--threads", type=int, default=4)
    p.add_argument("--ctx", type=int, default=256)
    p.add_argument("--batch", type=int, default=32)
    p.add_argument("--kv-window", type=int, default=0)
    p.add_argument("--runs", type=int, default=3)
    p.add_argument("--prefer-dotprod", action="store_true", default=True)
    p.add_argument("--no-dotprod", dest="prefer_dotprod", action="store_false")
    p.add_argument("--prepack", action="store_true")
    p.add_argument("--max-tokens", type=int, default=128, help="Tokens for throughput test")
    p.add_argument(
        "--min-gen-tokens",
        type=int,
        default=0,
        help="Ignore throughput samples that generated fewer than N tokens (0 = keep all)",
    )
    return p.parse_args(argv)


def main(argv: List[str]) -> int:
    args = parse_args(argv)
    runner = find_runner(prefer_dotprod=bool(args.prefer_dotprod))

    suite = short_suite() if args.suite == "short" else full_suite()

    print(f"[runner] {runner}")
    print(f"[model]  {args.model}")
    print(f"[mode]   {args.mode}")
    print(f"[ctx]    {args.ctx}  [batch] {args.batch}  [threads] {args.threads}  [runs] {args.runs}")
    if args.kv_window:
        print(f"[kv]     window={args.kv_window}")
    if args.prepack:
        print("[prepack] enabled")
    print()

    ttft_rows = []
    tp_rows = []
    tp_tokens_rows = []

    for cid, prompt in suite:
        ttft_benches: List[Optional[Bench]] = []
        tp_benches: List[Optional[Bench]] = []
        for _ in range(args.runs):
            try:
                ttft_benches.append(
                    run_once(
                        runner=runner,
                        model=args.model,
                        prompt=prompt,
                        threads=args.threads,
                        ctx=args.ctx,
                        batch=args.batch,
                        max_tokens=1,
                        mode=args.mode,
                        prepack=bool(args.prepack),
                        kv_window=int(args.kv_window),
                    )
                )
            except Exception as e:
                ttft_benches.append(None)
                print(f"{cid:10s} ttft ERROR: {e}", file=sys.stderr)

            try:
                tp_benches.append(
                    run_once(
                        runner=runner,
                        model=args.model,
                        prompt=prompt,
                        threads=args.threads,
                        ctx=args.ctx,
                        batch=args.batch,
                        max_tokens=int(args.max_tokens),
                        mode=args.mode,
                        prepack=bool(args.prepack),
                        kv_window=int(args.kv_window),
                    )
                )
            except Exception as e:
                tp_benches.append(None)
                print(f"{cid:10s} tp   ERROR: {e}", file=sys.stderr)

        ttft_ms = mean_or_none(b.ttft_ms for b in ttft_benches if b is not None)
        ttft_prefill_tok_s = mean_or_none(b.prefill_tok_s for b in ttft_benches if b is not None)

        tp_ok = [b for b in tp_benches if b is not None and b.generated_tokens >= int(args.min_gen_tokens)]
        tok_s = mean_or_none(b.tok_s for b in tp_ok)
        gen_tokens = mean_int_or_none(b.generated_tokens for b in tp_ok)

        ttft_rows.append(ttft_ms)
        tp_rows.append(tok_s)
        tp_tokens_rows.append(gen_tokens)

        ttft_ms_s = "NA" if ttft_ms is None else f"{ttft_ms:7.0f}"
        prefill_s = "NA" if ttft_prefill_tok_s is None else f"{ttft_prefill_tok_s:7.1f}"
        tok_s_s = "NA" if tok_s is None else f"{tok_s:7.2f}"
        gen_s = "NA" if gen_tokens is None else f"{gen_tokens:4d}"
        print(f"{cid:10s} ttft_ms={ttft_ms_s}  prefill_tok_s={prefill_s}  gen_tok_s={tok_s_s}  gen_toks={gen_s}")

    avg_ttft = mean_or_none(ttft_rows)
    avg_tok_s = mean_or_none(tp_rows)
    avg_gen_tokens = mean_int_or_none(tp_tokens_rows)
    print()
    print(
        f"[avg] ttft_ms={('NA' if avg_ttft is None else f'{avg_ttft:.0f}')} "
        f"gen_tok_s={('NA' if avg_tok_s is None else f'{avg_tok_s:.2f}')} "
        f"gen_toks={('NA' if avg_gen_tokens is None else str(avg_gen_tokens))}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

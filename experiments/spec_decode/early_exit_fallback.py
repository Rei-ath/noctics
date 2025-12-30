#!/usr/bin/env python3
import argparse
import subprocess
import time
from pathlib import Path


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


def run_model(
    runner: str,
    model: str,
    prompt: str,
    max_tokens: int,
    ctx: int,
    batch: int,
    fast: bool,
) -> tuple[str, float, str]:
    cmd = [
        runner,
        "-model",
        model,
        "-raw",
        "-ctx",
        str(ctx),
        "-batch",
        str(batch),
        "-max-tokens",
        str(max_tokens),
    ]
    if fast:
        cmd.append("-fast")
    start = time.perf_counter()
    proc = subprocess.run(
        cmd,
        input=prompt,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    elapsed = time.perf_counter() - start
    out = proc.stdout
    err = proc.stderr.strip()
    if proc.returncode != 0:
        raise RuntimeError(f"runner failed ({proc.returncode}): {err}")
    return out, elapsed, err


def build_prompt(repeats: int) -> tuple[str, str]:
    a, b = 11873, 9821
    c, d = 19, 6
    word = "microcontroller"
    expected = f"SUM={a + b} PROD={c * d} WORD={word[-5:]}"
    filler = "\n".join(
        [
            "You are evaluating an assistant under strict constraints.",
            "Ignore filler. Do not answer until the final task block.",
        ]
    )
    big_block = "\n".join([filler] * max(1, repeats))
    prompt = f"""
{big_block}

TASK (FALSIFIABLE):
Return exactly this string and nothing else:
{expected}
""".strip()
    return prompt, expected


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Early-exit test: run small model and fallback to large if it fails."
    )
    parser.add_argument("--runner", default=None, help="Path to noxlocal binary")
    parser.add_argument("--model-small", default=None, help="Path to 0.5B GGUF model")
    parser.add_argument("--model-large", default=None, help="Path to 7B GGUF model")
    parser.add_argument("--ctx", type=int, default=1024, help="Context length")
    parser.add_argument("--batch", type=int, default=32, help="Batch size")
    parser.add_argument(
        "--max-tokens",
        type=int,
        default=64,
        help="Max tokens for each model",
    )
    parser.add_argument("--no-fast", action="store_true", help="Disable -fast preset")
    parser.add_argument(
        "--filler-repeats",
        type=int,
        default=6,
        help="Repeat count for filler block (controls prompt size)",
    )
    parser.add_argument(
        "--prompt",
        default=None,
        help="Override prompt (use with --expect)",
    )
    parser.add_argument(
        "--expect",
        default=None,
        help="Expected substring for pass/fail check",
    )
    args = parser.parse_args()

    root = repo_root()
    runner = resolve_runner(root, args.runner)
    model_small = args.model_small or str(root / "assets" / "models" / "nox.gguf")
    model_large = args.model_large or str(root / "assets" / "models" / "mistral-7b-q4.gguf")

    if args.prompt is None:
        prompt, expected = build_prompt(args.filler_repeats)
    else:
        prompt = args.prompt
        expected = args.expect or ""

    print("Prompt length:", len(prompt))
    if expected:
        print("Expected:", expected)

    print("\n[1/2] small model...")
    small_out, small_time, small_err = run_model(
        runner,
        model_small,
        prompt,
        max_tokens=args.max_tokens,
        ctx=args.ctx,
        batch=args.batch,
        fast=not args.no_fast,
    )
    ok = expected in small_out if expected else False
    print(f"small output: {small_out!r} ({small_time:.2f}s)")
    if small_err:
        print("small stderr (last line):", small_err.splitlines()[-1])
    print("small pass:", ok)

    if ok:
        print("\nEarly-exit: small model accepted.")
        return 0

    print("\n[2/2] large model fallback...")
    large_out, large_time, large_err = run_model(
        runner,
        model_large,
        prompt,
        max_tokens=args.max_tokens,
        ctx=args.ctx,
        batch=args.batch,
        fast=not args.no_fast,
    )
    print(f"large output: {large_out!r} ({large_time:.2f}s)")
    if large_err:
        print("large stderr (last line):", large_err.splitlines()[-1])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

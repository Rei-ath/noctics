#!/usr/bin/env python3
import argparse
import subprocess
import sys
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
            "The following filler is irrelevant and should be ignored.",
            "Repeat: do not answer until you reach the final task block.",
            "This is a controlled experiment. Read carefully.",
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
        description="Run 7B for first token, then continue with 0.5B."
    )
    parser.add_argument("--runner", default=None, help="Path to noxlocal binary")
    parser.add_argument("--model-7b", default=None, help="Path to 7B GGUF model")
    parser.add_argument("--model-small", default=None, help="Path to 0.5B GGUF model")
    parser.add_argument("--ctx", type=int, default=1024, help="Context length")
    parser.add_argument("--batch", type=int, default=32, help="Batch size")
    parser.add_argument(
        "--max-tokens",
        type=int,
        default=128,
        help="Max tokens for the 0.5B continuation",
    )
    parser.add_argument("--no-fast", action="store_true", help="Disable -fast preset")
    parser.add_argument(
        "--filler-repeats",
        type=int,
        default=12,
        help="Repeat count for filler block (controls prompt size)",
    )
    args = parser.parse_args()

    root = repo_root()
    runner = resolve_runner(root, args.runner)
    model_7b = args.model_7b or str(root / "assets" / "models" / "mistral-7b-q4.gguf")
    model_small = args.model_small or str(root / "assets" / "models" / "nox.gguf")

    prompt, expected = build_prompt(args.filler_repeats)
    print("Prompt length:", len(prompt))
    print("Expected:", expected)

    print("\n[1/2] 7B: waiting for first token...")
    first_out, first_time, first_err = run_model(
        runner,
        model_7b,
        prompt,
        max_tokens=1,
        ctx=args.ctx,
        batch=args.batch,
        fast=not args.no_fast,
    )
    first_token = first_out
    print(f"7B first token: {first_token!r} ({first_time:.2f}s)")
    if first_err:
        print("7B stderr (last line):", first_err.splitlines()[-1])

    chained_prompt = prompt + first_token
    print("\n[2/2] 0.5B: continuing from prompt+first_token...")
    cont_out, cont_time, cont_err = run_model(
        runner,
        model_small,
        chained_prompt,
        max_tokens=args.max_tokens,
        ctx=args.ctx,
        batch=args.batch,
        fast=not args.no_fast,
    )
    print(f"0.5B output: {cont_out!r} ({cont_time:.2f}s)")
    if cont_err:
        print("0.5B stderr (last line):", cont_err.splitlines()[-1])

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
import argparse
import subprocess
import sys
from pathlib import Path


def repo_root() -> Path:
    here = Path(__file__).resolve()
    for parent in (here.parent, *here.parents):
        if (parent / "pyproject.toml").exists() or (parent / ".git").exists():
            return parent
    return here.parents[2]


def default_prompts() -> list[str]:
    return [
        "Explain why the sky is blue in one sentence.",
        "Write a short haiku about rain.",
        "Summarize: Mobile inference is slow.",
        "Give one tip for faster local LLM inference.",
    ]


def ensure_prompts_file(path: Path) -> Path:
    if path.exists():
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = "\n".join(default_prompts()) + "\n"
    path.write_text(lines, encoding="utf-8")
    return path


def run_step(label: str, args: list[str]) -> None:
    print(f"\n== {label} ==")
    print(" ".join(args))
    subprocess.run(args, check=True)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="One-shot neuroutine pipeline: collect -> train -> eval -> run gate."
    )
    parser.add_argument("--prompt", default=None, help="Single prompt")
    parser.add_argument("--prompts", default=None, help="File with prompts (one per line)")
    parser.add_argument("--steps", type=int, default=8, help="Tokens per prompt")
    parser.add_argument("--ctx", type=int, default=1024, help="Context length")
    parser.add_argument("--batch", type=int, default=32, help="Batch size")
    parser.add_argument("--model-small", default=None, help="Path to small GGUF model")
    parser.add_argument("--model-large", default=None, help="Path to large GGUF model")
    parser.add_argument("--no-fast", action="store_true", help="Disable -fast preset")
    parser.add_argument("--out-dir", default="data/neuroutine", help="Output directory")
    parser.add_argument("--accept-prob", type=float, default=0.5, help="Accept threshold for gate")
    parser.add_argument("--metrics-timeout", type=float, default=2.0, help="Seconds to wait for metrics")
    parser.add_argument("--verbose", action="store_true", help="Echo runner stderr")
    parser.add_argument(
        "--loop",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Continue with a self-improving loop after the initial run",
    )
    parser.add_argument(
        "--mirror",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="In loop mode, always output large-model tokens",
    )
    args = parser.parse_args()

    root = repo_root()
    out_dir = (root / args.out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    train_path = out_dir / "train.jsonl"
    weights_path = out_dir / "weights.json"

    if args.prompts:
        args.prompts = str(ensure_prompts_file(Path(args.prompts)))

    py = sys.executable
    exp_dir = root / "experiments" / "neuroutine"
    collect_cmd = [
        py,
        str(exp_dir / "neuroutine_collect.py"),
        "--steps",
        str(args.steps),
        "--ctx",
        str(args.ctx),
        "--batch",
        str(args.batch),
        "--out",
        str(train_path),
        "--metrics-timeout",
        str(args.metrics_timeout),
    ]
    if args.prompt:
        collect_cmd += ["--prompt", args.prompt]
    if args.prompts:
        collect_cmd += ["--prompts", args.prompts]
    if args.model_small:
        collect_cmd += ["--model-small", args.model_small]
    if args.model_large:
        collect_cmd += ["--model-large", args.model_large]
    if args.no_fast:
        collect_cmd.append("--no-fast")
    if args.verbose:
        collect_cmd.append("--verbose")

    train_cmd = [
        py,
        str(exp_dir / "neuroutine_train.py"),
        "--data",
        str(train_path),
        "--out",
        str(weights_path),
    ]

    eval_cmd = [
        py,
        str(exp_dir / "neuroutine_eval.py"),
        "--steps",
        str(args.steps),
        "--ctx",
        str(args.ctx),
        "--batch",
        str(args.batch),
        "--weights",
        str(weights_path),
        "--metrics-timeout",
        str(args.metrics_timeout),
    ]
    if args.prompt:
        eval_cmd += ["--prompt", args.prompt]
    if args.prompts:
        eval_cmd += ["--prompts", args.prompts]
    if args.model_small:
        eval_cmd += ["--model-small", args.model_small]
    if args.model_large:
        eval_cmd += ["--model-large", args.model_large]
    if args.no_fast:
        eval_cmd.append("--no-fast")
    if args.verbose:
        eval_cmd.append("--verbose")

    gate_cmd = [
        py,
        str(exp_dir / "neuroutine_gate.py"),
        "--steps",
        str(args.steps),
        "--ctx",
        str(args.ctx),
        "--batch",
        str(args.batch),
        "--weights",
        str(weights_path),
        "--accept-prob",
        str(args.accept_prob),
        "--metrics-timeout",
        str(args.metrics_timeout),
    ]
    if args.prompt:
        gate_cmd += ["--prompt", args.prompt]
    if args.prompts:
        gate_cmd += ["--prompts", args.prompts]
    if args.model_small:
        gate_cmd += ["--model-small", args.model_small]
    if args.model_large:
        gate_cmd += ["--model-large", args.model_large]
    if args.no_fast:
        gate_cmd.append("--no-fast")
    if args.verbose:
        gate_cmd.append("--verbose")

    run_step("collect", collect_cmd)
    run_step("train", train_cmd)
    run_step("eval", eval_cmd)
    run_step("gate", gate_cmd)
    if args.loop:
        loop_cmd = [
            py,
            str(exp_dir / "neuroutine_loop.py"),
            "--steps",
            str(args.steps),
            "--ctx",
            str(args.ctx),
            "--batch",
            str(args.batch),
            "--weights",
            str(weights_path),
            "--metrics-timeout",
            str(args.metrics_timeout),
        ]
        if args.prompt:
            loop_cmd += ["--prompt", args.prompt]
        if args.prompts:
            loop_cmd += ["--prompts", args.prompts]
        if args.model_small:
            loop_cmd += ["--model-small", args.model_small]
        if args.model_large:
            loop_cmd += ["--model-large", args.model_large]
        if args.no_fast:
            loop_cmd.append("--no-fast")
        if args.verbose:
            loop_cmd.append("--verbose")
        if not args.mirror:
            loop_cmd.append("--no-mirror")
        run_step("loop", loop_cmd)
    print(f"\noutputs: {train_path} {weights_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
import argparse
import json
import random
import subprocess
import sys
import threading
import time
from collections import deque
from pathlib import Path
from typing import BinaryIO

from neuroutine_controller import Controller, compute_norm, features_from_row, load_controller, normalize, train_logreg, train_mlp


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
        self.queue: deque[dict[str, float]] = deque()
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
            return self.queue.popleft()


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


def stats_from_rows(rows: list[dict], controller: Controller) -> dict[str, float]:
    total = 0
    accepted = 0
    wrong_accept = 0
    agreement = 0
    decision_correct = 0
    for row in rows:
        metrics = row.get("metrics") or {}
        draft = row.get("draft", "")
        verify = row.get("verify", "")
        accept, _ = controller.accept(metrics, draft)
        match = draft == verify and draft != ""
        total += 1
        if match:
            agreement += 1
        if accept:
            accepted += 1
            if not match:
                wrong_accept += 1
            else:
                decision_correct += 1
        elif not match:
            decision_correct += 1
    accept_rate = accepted / total if total else 0.0
    wrong_rate = wrong_accept / accepted if accepted else 0.0
    agreement_rate = agreement / total if total else 0.0
    output_match_rate = 1.0 - (wrong_accept / total if total else 0.0)
    decision_accuracy = decision_correct / total if total else 0.0
    return {
        "samples": total,
        "accept_rate": accept_rate,
        "wrong_accept_rate": wrong_rate,
        "agreement_rate": agreement_rate,
        "output_match_rate": output_match_rate,
        "decision_accuracy": decision_accuracy,
    }


def load_prompts(args: argparse.Namespace) -> list[str]:
    if args.prompt:
        return [args.prompt]
    if args.prompts:
        path = Path(args.prompts)
        if not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(
                "\n".join(
                    [
                        "Explain why the sky is blue in one sentence.",
                        "Write a short haiku about rain.",
                        "Summarize: Mobile inference is slow.",
                        "Give one tip for faster local LLM inference.",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
        return [line.strip() for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    return ["hello"]


def main() -> int:
    parser = argparse.ArgumentParser(description="Self-improving neuroutine loop.")
    parser.add_argument("--runner", default=None, help="Path to noxlocal binary")
    parser.add_argument("--model-small", default=None, help="Path to small GGUF model")
    parser.add_argument("--model-large", default=None, help="Path to large GGUF model")
    parser.add_argument("--ctx", type=int, default=1024, help="Context length")
    parser.add_argument("--batch", type=int, default=32, help="Batch size")
    parser.add_argument("--steps", type=int, default=6, help="Tokens per prompt")
    parser.add_argument("--no-fast", action="store_true", help="Disable -fast preset")
    parser.add_argument("--prompt", default=None, help="Single prompt")
    parser.add_argument("--prompts", default=None, help="File with prompts (one per line)")
    parser.add_argument("--weights", default="data/neuroutine/live_weights.json", help="Weights JSON path")
    parser.add_argument("--log", default="data/neuroutine/live.jsonl", help="Append samples here")
    parser.add_argument("--window-size", type=int, default=500, help="Training window size")
    parser.add_argument("--min-samples", type=int, default=50, help="Minimum samples before retrain")
    parser.add_argument("--retrain-every", type=int, default=50, help="Retrain every N samples")
    parser.add_argument("--train-steps", type=int, default=400, help="Gradient steps per retrain")
    parser.add_argument(
        "--controller",
        choices=("mlp", "logreg"),
        default="mlp",
        help="Controller type to train in-loop",
    )
    parser.add_argument("--mlp-hidden", type=int, default=8, help="Hidden size for MLP controller")
    parser.add_argument("--train-seed", type=int, default=1, help="Seed for controller init (MLP)")
    parser.add_argument("--lr", type=float, default=0.1, help="Learning rate")
    parser.add_argument("--l2", type=float, default=0.0, help="L2 regularization")
    parser.add_argument("--accept-prob", type=float, default=0.5, help="Accept threshold for learned weights")
    parser.add_argument("--margin-threshold", type=float, default=1.0, help="Fallback threshold before learning")
    parser.add_argument(
        "--teacher-prob",
        type=float,
        default=0.0,
        help="When accept-small, still query large with this probability to label/retrain (0 disables).",
    )
    parser.add_argument(
        "--teacher-every",
        type=int,
        default=0,
        help="When accept-small, still query large every N tokens to label/retrain (0 disables).",
    )
    parser.add_argument(
        "--bootstrap-positives",
        type=int,
        default=4,
        help="Force teacher calls on accept-small until this many positive labels are collected (0 disables).",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=0,
        help="RNG seed for teacher sampling (0 = time-based).",
    )
    parser.add_argument("--metrics-timeout", type=float, default=2.0, help="Seconds to wait for metrics")
    parser.add_argument("--report-every", type=int, default=25, help="Report stats every N samples")
    parser.add_argument("--accuracy-window", type=int, default=100, help="Rolling window for gate accuracy")
    parser.add_argument(
        "--mirror",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Always output large token (slow, but keeps contexts identical).",
    )
    parser.add_argument("--verbose", action="store_true", help="Echo runner stderr")
    args = parser.parse_args()

    root = repo_root()
    if args.seed:
        random.seed(args.seed)
    else:
        random.seed(time.time_ns())
    weights_path = (root / args.weights).resolve()
    log_path = (root / args.log).resolve()
    log_path.parent.mkdir(parents=True, exist_ok=True)

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

    controller = load_controller(weights_path, accept_prob=args.accept_prob, margin_threshold=args.margin_threshold)

    train_window: deque[dict] = deque(maxlen=args.window_size)
    prompts = load_prompts(args)
    prompt_idx = 0
    total_tokens = 0
    labeled_samples = 0
    last_report: dict[str, float] | None = None
    gate_correct = 0
    gate_window: deque[int] = deque(maxlen=max(1, args.accuracy_window))
    small_time_s = 0.0
    large_time_s = 0.0
    large_calls = 0

    with log_path.open("a", encoding="utf-8") as handle:
        try:
            while True:
                if prompt_idx >= len(prompts):
                    prompt_idx = 0
                current = prompts[prompt_idx]
                prompt_idx += 1

                print(f"prompt: {current!r}")
                for step in range(1, args.steps + 1):
                    start = time.perf_counter()
                    draft = send_prompt(small_proc, current)
                    small_dt = time.perf_counter() - start
                    small_time_s += small_dt
                    metrics = metrics_reader.get(args.metrics_timeout) or {}
                    accept, score = controller.accept(metrics, draft)

                    should_call_teacher = args.mirror or (not accept)
                    if not should_call_teacher and args.teacher_every > 0:
                        if (total_tokens + 1) % args.teacher_every == 0:
                            should_call_teacher = True
                    if (
                        not should_call_teacher
                        and args.teacher_prob > 0.0
                        and random.random() < args.teacher_prob
                    ):
                        should_call_teacher = True
                    if (
                        not should_call_teacher
                        and accept
                        and args.bootstrap_positives > 0
                        and sum(1 for r in train_window if r.get("label") == 1) < args.bootstrap_positives
                    ):
                        should_call_teacher = True

                    verify: str | None = None
                    label: int | None = None
                    large_dt = 0.0
                    match = False
                    if should_call_teacher:
                        start = time.perf_counter()
                        verify = send_prompt(large_proc, current)
                        large_dt = time.perf_counter() - start
                        large_time_s += large_dt
                        large_calls += 1
                        match = draft == verify and draft != ""
                        label = int(match)
                        labeled_samples += 1
                        train_window.append(
                            {
                                "prompt_len": len(current),
                                "step": step,
                                "draft": draft,
                                "verify": verify,
                                "label": label,
                                "metrics": metrics,
                                "token_len": len(draft),
                            }
                        )
                        decision_correct = (accept and match) or ((not accept) and (not match))
                        gate_correct += 1 if decision_correct else 0
                        gate_window.append(1 if decision_correct else 0)

                    if args.mirror:
                        chosen = verify or ""
                    elif should_call_teacher and verify is not None:
                        chosen = verify
                    else:
                        chosen = draft if accept else ""
                    decision = (
                        "mirror"
                        if args.mirror
                        else ("accept-small" if accept else "fallback-large")
                    )

                    row = {
                        "prompt_len": len(current),
                        "step": step,
                        "draft": draft,
                        "verify": verify,
                        "label": label,
                        "metrics": metrics,
                        "token_len": len(draft),
                        "accept": accept,
                        "score": score,
                        "teacher_called": should_call_teacher,
                        "small_time_s": small_dt,
                        "large_time_s": large_dt,
                        "chosen": chosen,
                    }
                    handle.write(json.dumps(row, ensure_ascii=True) + "\n")
                    handle.flush()
                    total_tokens += 1

                    total_acc = gate_correct / labeled_samples if labeled_samples else 0.0
                    rolling_acc = sum(gate_window) / len(gate_window) if gate_window else 0.0
                    print(
                        f"{step:02d} {decision} score={score:.3f} "
                        f"draft={draft!r} chosen={chosen!r} "
                        f"teacher={'Y' if should_call_teacher else 'n'} "
                        f"gate_acc={total_acc:.3f} rolling_acc={rolling_acc:.3f} "
                        f"(small={small_dt:.2f}s large={large_dt:.2f}s)"
                    )

                    if not chosen:
                        break
                    current += chosen

                    if args.report_every > 0 and labeled_samples > 0 and labeled_samples % args.report_every == 0:
                        stats = stats_from_rows(list(train_window), controller)
                        avg_large = large_time_s / max(1, large_calls)
                        baseline = avg_large * total_tokens
                        actual = small_time_s + large_time_s
                        speedup = (baseline / actual) if actual > 0 else 0.0
                        msg = (
                            f"samples={stats['samples']} tokens={total_tokens} large_calls={large_calls} "
                            f"est_speedup={speedup:.2f} "
                            f"accept_rate={stats['accept_rate']:.3f} "
                            f"wrong_accept_rate={stats['wrong_accept_rate']:.3f} "
                            f"agreement_rate={stats['agreement_rate']:.3f} "
                            f"output_match_rate={stats['output_match_rate']:.3f} "
                            f"decision_accuracy={stats['decision_accuracy']:.3f}"
                        )
                        print(msg)

                    if (
                        args.retrain_every > 0
                        and labeled_samples > 0
                        and labeled_samples % args.retrain_every == 0
                        and len(train_window) >= args.min_samples
                    ):
                        rows = list(train_window)
                        X = [features_from_row(r) for r in rows]
                        y = [int(r.get("label", 0)) for r in rows]
                        pos = sum(y)
                        neg = len(y) - pos
                        if pos == 0 or neg == 0:
                            print(f"retrain: skipped (need pos+neg, pos={pos} neg={neg})")
                            continue
                        mean, std = compute_norm(X)
                        Xn = normalize(X, mean, std)
                        payload: dict
                        if args.controller == "logreg":
                            weights, bias = train_logreg(Xn, y, args.train_steps, args.lr, args.l2)
                            payload = {
                                "type": "logreg_v1",
                                "weights": weights,
                                "bias": bias,
                            }
                        else:
                            W1, b1, W2, b2 = train_mlp(
                                Xn,
                                y,
                                hidden=max(1, args.mlp_hidden),
                                steps=args.train_steps,
                                lr=args.lr,
                                l2=args.l2,
                                seed=args.train_seed,
                            )
                            payload = {
                                "type": "mlp_v1",
                                "hidden": max(1, args.mlp_hidden),
                                "W1": W1,
                                "b1": b1,
                                "W2": W2,
                                "b2": b2,
                            }
                        weights_path.write_text(
                            json.dumps(
                                {
                                    **payload,
                                    "mean": mean,
                                    "std": std,
                                    "samples": len(rows),
                                    "pos": pos,
                                    "neg": neg,
                                },
                                indent=2,
                                ensure_ascii=True,
                            )
                            + "\n",
                            encoding="utf-8",
                        )
                        controller = load_controller(
                            weights_path,
                            accept_prob=args.accept_prob,
                            margin_threshold=args.margin_threshold,
                        )
                        stats = stats_from_rows(rows, controller)
                        avg_large = large_time_s / max(1, large_calls)
                        baseline = avg_large * total_tokens
                        actual = small_time_s + large_time_s
                        speedup = (baseline / actual) if actual > 0 else 0.0
                        if last_report:
                            delta = {
                                k: stats[k] - last_report.get(k, 0.0)
                                for k in stats
                                if isinstance(stats[k], float)
                            }
                            print(
                                "retrain: "
                                + f"est_speedup={speedup:.2f} "
                                + " ".join(
                                    f"{k}={stats[k]:.3f}({delta[k]:+.3f})"
                                    for k in (
                                        "accept_rate",
                                        "wrong_accept_rate",
                                        "agreement_rate",
                                        "output_match_rate",
                                        "decision_accuracy",
                                    )
                                )
                            )
                        else:
                            print(
                                "retrain: "
                                + f"est_speedup={speedup:.2f} "
                                + " ".join(
                                    f"{k}={stats[k]:.3f}"
                                    for k in (
                                        "accept_rate",
                                        "wrong_accept_rate",
                                        "agreement_rate",
                                        "output_match_rate",
                                        "decision_accuracy",
                                    )
                                )
                            )
                        last_report = stats
        except KeyboardInterrupt:
            print("\nStopping loop.")
        finally:
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

#!/usr/bin/env python3
import argparse
import json
from pathlib import Path

from neuroutine_controller import (
    compute_norm,
    evaluate_probs,
    features_from_row,
    logreg_prob,
    mlp_prob,
    normalize,
    train_logreg,
    train_mlp,
)


def load_rows(path: Path) -> list[dict]:
    rows: list[dict] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        rows.append(json.loads(line))
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description="Train a tiny neuroutine controller (MLP or logistic regression).")
    parser.add_argument("--data", default="data/neuroutine_train.jsonl", help="JSONL training data")
    parser.add_argument("--out", default="data/neuroutine_weights.json", help="Output weights JSON")
    parser.add_argument(
        "--controller",
        choices=("mlp", "logreg"),
        default="mlp",
        help="Controller type to train",
    )
    parser.add_argument("--hidden", type=int, default=8, help="Hidden size for MLP")
    parser.add_argument("--steps", type=int, default=400, help="Gradient steps")
    parser.add_argument("--lr", type=float, default=0.1, help="Learning rate")
    parser.add_argument("--l2", type=float, default=0.0, help="L2 regularization")
    parser.add_argument("--seed", type=int, default=1, help="Seed for MLP init")
    parser.add_argument("--no-normalize", action="store_true", help="Disable feature normalization")
    args = parser.parse_args()

    path = Path(args.data)
    rows = load_rows(path)
    if not rows:
        raise SystemExit("no training rows found")

    X = [features_from_row(row) for row in rows]
    y = [int(row.get("label", 0)) for row in rows]

    pos = sum(y)
    neg = len(y) - pos
    if pos == 0 or neg == 0:
        raise SystemExit(f"need pos+neg labels to train (pos={pos} neg={neg})")

    mean = [0.0] * len(X[0])
    std = [1.0] * len(X[0])
    if not args.no_normalize:
        mean, std = compute_norm(X)
        X = normalize(X, mean, std)

    out: dict = {
        "mean": mean,
        "std": std,
        "samples": len(rows),
        "pos": pos,
        "neg": neg,
    }
    probs: list[float]
    if args.controller == "logreg":
        w, b = train_logreg(X, y, args.steps, args.lr, args.l2)
        probs = [logreg_prob(w, b, row) for row in X]
        acc, avg_prob = evaluate_probs(y, probs)
        out.update(
            {
                "type": "logreg_v1",
                "weights": w,
                "bias": b,
                "train_acc": acc,
                "avg_prob": avg_prob,
            }
        )
    else:
        W1, b1, W2, b2 = train_mlp(
            X,
            y,
            hidden=max(1, args.hidden),
            steps=args.steps,
            lr=args.lr,
            l2=args.l2,
            seed=args.seed,
        )
        probs = [mlp_prob(W1, b1, W2, b2, row) for row in X]
        acc, avg_prob = evaluate_probs(y, probs)
        out.update(
            {
                "type": "mlp_v1",
                "hidden": max(1, args.hidden),
                "W1": W1,
                "b1": b1,
                "W2": W2,
                "b2": b2,
                "train_acc": acc,
                "avg_prob": avg_prob,
            }
        )

    Path(args.out).write_text(json.dumps(out, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
    print(f"Wrote {args.out}")
    print(
        f"type={out.get('type')} train_acc={out.get('train_acc'):.3f} "
        f"avg_prob={out.get('avg_prob'):.3f} samples={len(rows)} pos={pos} neg={neg}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

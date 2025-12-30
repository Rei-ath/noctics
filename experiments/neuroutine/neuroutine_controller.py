#!/usr/bin/env python3
from __future__ import annotations

import json
import math
import random
from dataclasses import dataclass
from pathlib import Path


def sigmoid(x: float) -> float:
    if x < -60.0:
        return 0.0
    if x > 60.0:
        return 1.0
    return 1.0 / (1.0 + math.exp(-x))


def relu(x: float) -> float:
    return x if x > 0.0 else 0.0


def features_from_row(row: dict) -> list[float]:
    metrics = row.get("metrics") or {}
    token = row.get("draft") or ""
    return [
        float(metrics.get("margin", 0.0)),
        float(metrics.get("max", 0.0)),
        float(metrics.get("second", 0.0)),
        float(len(token)),
    ]


def features_from_metrics(metrics: dict[str, float], token: str) -> list[float]:
    return [
        float(metrics.get("margin", 0.0)),
        float(metrics.get("max", 0.0)),
        float(metrics.get("second", 0.0)),
        float(len(token)),
    ]


def compute_norm(X: list[list[float]]) -> tuple[list[float], list[float]]:
    if not X:
        return [], []
    n = len(X)
    dims = len(X[0])
    mean = [0.0] * dims
    for row in X:
        for i, v in enumerate(row):
            mean[i] += v
    mean = [m / max(1, n) for m in mean]
    var = [0.0] * dims
    for row in X:
        for i, v in enumerate(row):
            var[i] += (v - mean[i]) ** 2
    std = [math.sqrt(v / max(1, n)) or 1.0 for v in var]
    return mean, std


def normalize(X: list[list[float]], mean: list[float], std: list[float]) -> list[list[float]]:
    out: list[list[float]] = []
    for row in X:
        out.append([(v - m) / s if s > 0 else v for v, m, s in zip(row, mean, std)])
    return out


def train_logreg(
    X: list[list[float]],
    y: list[int],
    steps: int,
    lr: float,
    l2: float,
) -> tuple[list[float], float]:
    n = len(X)
    if n == 0:
        return [], 0.0
    dims = len(X[0])
    w = [0.0] * dims
    b = 0.0
    for _ in range(steps):
        grad_w = [0.0] * dims
        grad_b = 0.0
        for row, label in zip(X, y):
            z = b + sum(wi * xi for wi, xi in zip(w, row))
            pred = sigmoid(z)
            err = pred - label
            for i, xi in enumerate(row):
                grad_w[i] += err * xi
            grad_b += err
        inv_n = 1.0 / max(1, n)
        for i in range(dims):
            grad_w[i] = grad_w[i] * inv_n + l2 * w[i]
            w[i] -= lr * grad_w[i]
        b -= lr * grad_b * inv_n
    return w, b


def logreg_prob(w: list[float], b: float, x: list[float]) -> float:
    score = b
    for wi, xi in zip(w, x):
        score += wi * xi
    return sigmoid(score)


def train_mlp(
    X: list[list[float]],
    y: list[int],
    *,
    hidden: int,
    steps: int,
    lr: float,
    l2: float,
    seed: int,
) -> tuple[list[list[float]], list[float], list[float], float]:
    n = len(X)
    if n == 0:
        return [], [], [], 0.0
    dims = len(X[0])
    rng = random.Random(seed)

    def init(scale: float) -> float:
        return (rng.random() * 2.0 - 1.0) * scale

    W1 = [[init(0.1) for _ in range(dims)] for _ in range(hidden)]
    b1 = [0.0 for _ in range(hidden)]
    W2 = [init(0.1) for _ in range(hidden)]
    b2 = 0.0

    for _ in range(steps):
        gW1 = [[0.0 for _ in range(dims)] for _ in range(hidden)]
        gb1 = [0.0 for _ in range(hidden)]
        gW2 = [0.0 for _ in range(hidden)]
        gb2 = 0.0

        for x, label in zip(X, y):
            z1 = [b1[j] + sum(W1[j][i] * x[i] for i in range(dims)) for j in range(hidden)]
            h = [relu(v) for v in z1]
            logit = b2 + sum(W2[j] * h[j] for j in range(hidden))
            prob = sigmoid(logit)
            dlogit = prob - float(label)

            for j in range(hidden):
                gW2[j] += dlogit * h[j]
            gb2 += dlogit

            for j in range(hidden):
                if z1[j] <= 0.0:
                    continue
                dz1 = dlogit * W2[j]
                gb1[j] += dz1
                for i in range(dims):
                    gW1[j][i] += dz1 * x[i]

        inv_n = 1.0 / max(1, n)
        for j in range(hidden):
            for i in range(dims):
                g = gW1[j][i] * inv_n + l2 * W1[j][i]
                W1[j][i] -= lr * g
            gb1[j] *= inv_n
            b1[j] -= lr * gb1[j]
        for j in range(hidden):
            g = gW2[j] * inv_n + l2 * W2[j]
            W2[j] -= lr * g
        b2 -= lr * gb2 * inv_n

    return W1, b1, W2, b2


def mlp_prob(W1: list[list[float]], b1: list[float], W2: list[float], b2: float, x: list[float]) -> float:
    if not W1:
        return 0.0
    hidden = len(W1)
    dims = len(x)
    z1 = [b1[j] + sum(W1[j][i] * x[i] for i in range(dims)) for j in range(hidden)]
    h = [relu(v) for v in z1]
    logit = b2 + sum(W2[j] * h[j] for j in range(hidden))
    return sigmoid(logit)


def evaluate_probs(y: list[int], probs: list[float]) -> tuple[float, float]:
    if not y:
        return 0.0, 0.0
    correct = 0
    avg_prob = 0.0
    for label, prob in zip(y, probs):
        pred = 1 if prob >= 0.5 else 0
        if pred == label:
            correct += 1
        avg_prob += prob
    return correct / len(y), avg_prob / len(y)


@dataclass(frozen=True)
class Controller:
    kind: str
    accept_prob: float
    margin_threshold: float
    mean: list[float] | None = None
    std: list[float] | None = None
    weights: list[float] | None = None
    bias: float = 0.0
    W1: list[list[float]] | None = None
    b1: list[float] | None = None
    W2: list[float] | None = None
    b2: float = 0.0

    def accept(self, metrics: dict[str, float], token: str) -> tuple[bool, float]:
        if self.kind == "threshold":
            margin = float(metrics.get("margin", 0.0))
            return margin >= self.margin_threshold, margin

        x = features_from_metrics(metrics, token)
        if self.mean and self.std and len(self.mean) == len(x) == len(self.std):
            x = [(v - m) / s if s > 0 else v for v, m, s in zip(x, self.mean, self.std)]

        if self.kind == "logreg":
            w = self.weights or []
            prob = logreg_prob(w, self.bias, x)
            return prob >= self.accept_prob, prob

        if self.kind == "mlp":
            prob = mlp_prob(self.W1 or [], self.b1 or [], self.W2 or [], self.b2, x)
            return prob >= self.accept_prob, prob

        margin = float(metrics.get("margin", 0.0))
        return margin >= self.margin_threshold, margin


def load_controller(path: Path, *, accept_prob: float, margin_threshold: float) -> Controller:
    if not path.exists():
        return Controller(kind="threshold", accept_prob=accept_prob, margin_threshold=margin_threshold)
    data = json.loads(path.read_text(encoding="utf-8"))
    kind = str(data.get("type") or "").strip().lower()
    mean = data.get("mean")
    std = data.get("std")
    mean_out = [float(v) for v in mean] if isinstance(mean, list) else None
    std_out = [float(v) for v in std] if isinstance(std, list) else None

    if kind == "mlp_v1":
        W1 = data.get("W1")
        b1 = data.get("b1")
        W2 = data.get("W2")
        b2 = float(data.get("b2", 0.0))
        if (
            isinstance(W1, list)
            and isinstance(b1, list)
            and isinstance(W2, list)
            and W1
            and b1
            and W2
        ):
            return Controller(
                kind="mlp",
                accept_prob=accept_prob,
                margin_threshold=margin_threshold,
                mean=mean_out,
                std=std_out,
                W1=[[float(v) for v in row] for row in W1],
                b1=[float(v) for v in b1],
                W2=[float(v) for v in W2],
                b2=b2,
            )
        return Controller(kind="threshold", accept_prob=accept_prob, margin_threshold=margin_threshold)

    weights = data.get("weights")
    bias = float(data.get("bias", 0.0))
    if isinstance(weights, list) and weights:
        weights_out = [float(w) for w in weights]
        if weights_out and max(abs(w) for w in weights_out) < 1e-6 and abs(bias) > 2.0:
            return Controller(kind="threshold", accept_prob=accept_prob, margin_threshold=margin_threshold)
        return Controller(
            kind="logreg",
            accept_prob=accept_prob,
            margin_threshold=margin_threshold,
            mean=mean_out,
            std=std_out,
            weights=weights_out,
            bias=bias,
        )
    return Controller(kind="threshold", accept_prob=accept_prob, margin_threshold=margin_threshold)


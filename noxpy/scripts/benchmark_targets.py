#!/usr/bin/env python3
"""
Benchmark Noctics (Nox ChatClient) across multiple targets.

Measures per-target:
- total_time_s (non-stream) or total_time_s + ttft_s (stream)
- output size (chars/words) and whether any hidden <think> leaked
- instrument_use_rate across cases
- optional reviewer quality scores (via OpenAI-compatible model)

Targets JSON format (example):
[
  {"name": "local-nox", "url": "http://127.0.0.1:11434/api/generate", "model": "nox"},
  {"name": "openai", "url": "https://api.openai.com/v1/chat/completions", "model": "gpt-4o", "api_key": "${OPENAI_API_KEY}"}
]
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Dict, List, Optional

from nox_env import get_env

ROOT = Path(__file__).resolve().parents[1]
CORE_ROOT = ROOT / "core"

try:
    from central.core import ChatClient  # type: ignore
    from interfaces.dotenv import load_local_dotenv  # type: ignore
except ImportError as exc:  # pragma: no cover - dependency missing
    raise ImportError(
        "Benchmark tooling requires the noctics-core package. "
        "Install it with `pip install noctics-core` or ensure the central modules are importable."
    ) from exc


def _bool_env(name: str, default: bool = False) -> bool:
    v = os.getenv(name)
    if v is None:
        return default
    return v.strip().lower() in {"1", "true", "yes", "on"}


@dataclass
class Case:
    id: str
    prompt: str


@dataclass
class Target:
    name: str
    url: str
    model: str
    api_key: Optional[str] = None


@dataclass
class TurnMetrics:
    case_id: str
    total_time_s: float
    ttft_s: Optional[float]
    output_chars: int
    output_words: int
    leaked_think: bool
    wants_instrument: bool


@dataclass
class TargetResult:
    target: Target
    turns: List[TurnMetrics]
    instrument_use_rate: float
    avg_total_time_s: float
    avg_ttft_s: Optional[float]
    avg_output_chars: float
    avg_output_words: float
    reviewer_overall: Optional[float]


def load_cases(path: Optional[str]) -> List[Case]:
    if not path:
        default = ROOT / "data" / "orch_eval_live.json"
        if default.exists():
            path = str(default)
    if path:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        out: List[Case] = []
        for i, raw in enumerate(data):
            cid = str(raw.get("id") or f"case-{i+1}")
            prompt = str(raw.get("prompt") or "").strip()
            if prompt:
                out.append(Case(id=cid, prompt=prompt))
        if out:
            return out
    # fallback small set
    return [
        Case(id="sum", prompt="Summarize: The quick brown fox jumps over the lazy dog."),
        Case(id="math", prompt="Compute 12 + 35 - 7 * 2, step-by-step but do not show private thoughts."),
        Case(id="instrument", prompt=(
            "If local confidence is low, emit an [INSTRUMENT QUERY] asking for a 3-bullet comparison of two LLM APIs."
        )),
    ]


def load_targets(path: Optional[str]) -> List[Target]:
    if not path:
        # Default to current env configured target
        url = get_env("NOX_LLM_URL") or ChatClient.DEFAULT_URL
        model = get_env("NOX_LLM_MODEL") or ""
        api_key = get_env("NOX_LLM_API_KEY") or os.getenv("OPENAI_API_KEY")
        return [Target(name="env", url=url, model=model, api_key=api_key)]
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    items: List[Target] = []
    for obj in raw:
        name = str(obj.get("name") or "target").strip()
        url = str(obj.get("url") or "").strip()
        model = str(obj.get("model") or "").strip()
        api_key = obj.get("api_key")
        if isinstance(api_key, str) and api_key.startswith("${") and api_key.endswith("}"):
            env_name = api_key[2:-1]
            api_key = os.getenv(env_name)
        items.append(Target(name=name, url=url, model=model, api_key=(str(api_key) if api_key else None)))
    return items


def _word_count(text: str) -> int:
    return len([t for t in text.split() if t])


def run_case(client: ChatClient, case: Case, *, stream: bool) -> TurnMetrics:
    ttft_s: Optional[float] = None
    start = time.perf_counter()
    acc: List[str] = []

    def on_delta(piece: str) -> None:
        nonlocal ttft_s
        if piece and ttft_s is None:
            ttft_s = time.perf_counter() - start
        acc.append(piece)

    if stream:
        reply = client.one_turn(case.prompt, on_delta=on_delta) or ""
    else:
        reply = client.one_turn(case.prompt) or ""
    total = time.perf_counter() - start
    wants = ChatClient.wants_instrument(reply)
    leaked = ("<think>" in reply.lower()) or ("</think>" in reply.lower())
    return TurnMetrics(
        case_id=case.id,
        total_time_s=total,
        ttft_s=(ttft_s if stream else None),
        output_chars=len(reply),
        output_words=_word_count(reply),
        leaked_think=leaked,
        wants_instrument=wants,
    )


def aggregate(turns: List[TurnMetrics]) -> Dict[str, Any]:
    n = max(1, len(turns))
    avg_total = sum(t.total_time_s for t in turns) / n
    ttfts = [t.ttft_s for t in turns if t.ttft_s is not None]
    avg_ttft = (sum(ttfts) / len(ttfts)) if ttfts else None
    avg_chars = sum(t.output_chars for t in turns) / n
    avg_words = sum(t.output_words for t in turns) / n
    use_rate = sum(1 for t in turns if t.wants_instrument) / n
    return {
        "instrument_use_rate": use_rate,
        "avg_total_time_s": avg_total,
        "avg_ttft_s": avg_ttft,
        "avg_output_chars": avg_chars,
        "avg_output_words": avg_words,
    }


def parse_args(argv: List[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser("benchmark_targets")
    p.add_argument("--targets", default=None, help="Path to JSON array of targets {name,url,model,api_key?}")
    p.add_argument("--cases", default=None, help="Path to JSON array of cases {id,prompt}")
    p.add_argument("--stream", action="store_true", help="Use streaming for TTFT measurement")
    p.add_argument("--out", default=str(ROOT / "data" / "bench_results.json"))
    return p.parse_args(argv)


def main(argv: List[str]) -> int:
    try:
        load_local_dotenv(CORE_ROOT)
    except Exception:
        pass
    args = parse_args(argv)

    cases = load_cases(args.cases)
    targets = load_targets(args.targets)

    results: List[TargetResult] = []
    for tgt in targets:
        print(f"[target] {tgt.name}: {tgt.model} @ {tgt.url}")
        client = ChatClient(
            url=tgt.url,
            model=tgt.model,
            api_key=tgt.api_key,
            stream=bool(args.stream),
            sanitize=True,
            enable_logging=False,
        )
        turns: List[TurnMetrics] = []
        for case in cases:
            tm = run_case(client, case, stream=bool(args.stream))
            turns.append(tm)
            print(f"  - {case.id}: time={tm.total_time_s:.2f}s" + (f", ttft={tm.ttft_s:.2f}s" if tm.ttft_s else ""))
        agg = aggregate(turns)
        results.append(
            TargetResult(
                target=tgt,
                turns=turns,
                instrument_use_rate=agg["instrument_use_rate"],
                avg_total_time_s=agg["avg_total_time_s"],
                avg_ttft_s=agg["avg_ttft_s"],
                avg_output_chars=agg["avg_output_chars"],
                avg_output_words=agg["avg_output_words"],
                reviewer_overall=None,
            )
        )

    payload = {
        "stream": bool(args.stream),
        "cases": [asdict(c) for c in cases],
        "results": [
            {
                "target": asdict(r.target),
                "turns": [asdict(t) for t in r.turns],
                "instrument_use_rate": r.instrument_use_rate,
                "avg_total_time_s": r.avg_total_time_s,
                "avg_ttft_s": r.avg_ttft_s,
                "avg_output_chars": r.avg_output_chars,
                "avg_output_words": r.avg_output_words,
                "reviewer_overall": r.reviewer_overall,
            }
            for r in results
        ],
    }

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[done] wrote {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

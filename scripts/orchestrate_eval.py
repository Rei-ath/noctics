#!/usr/bin/env python3
"""
End-to-end orchestration tester with optional GPT‑5 review.

Flow per case:
  1) Send a user prompt via Central ChatClient.
  2) If assistant requests an external instrument, extract the instrument query,
     optionally call an OpenAI instrument (e.g., GPT‑4o) to produce a result,
     and stitch it back via ChatClient.process_instrument_result.
  3) Ask GPT‑5 (or a specified review model) to evaluate the final response
     against a rubric and return JSON scores.

Offline-friendly:
  - If the OpenAI dependency or API key are missing, runs in simulate mode and
    skips network calls while still exercising the orchestration logic.

Usage examples:
  python scripts/orchestrate_eval.py \
    --target-url http://127.0.0.1:11434/api/generate \
    --target-model noxllm-05b:latest \
    --instrument-model gpt-4o \
    --review-model gpt-5 \
    --out data/orch_eval.json

  # Dry-run without network (simulated instrument + review)
  NO_NETWORK=1 python scripts/orchestrate_eval.py --simulate --out data/orch_eval.json
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass, asdict
import re
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError


# Wire core into path
ROOT = Path(__file__).resolve().parents[1]
CORE_ROOT = ROOT / "core"
if str(CORE_ROOT) not in sys.path:
    sys.path.insert(0, str(CORE_ROOT))

from central.core import ChatClient  # type: ignore
from central.commands.instrument import extract_instrument_query  # type: ignore
from central.transport import LLMTransport  # type: ignore
from interfaces.dotenv import load_local_dotenv  # type: ignore


# Instruments are optional; we only import the registry when needed
try:
    from instruments import build_instrument as _build_instrument  # type: ignore
except Exception:  # pragma: no cover - optional dep
    _build_instrument = None


def _bool_env(name: str, default: bool = False) -> bool:
    val = os.getenv(name)
    if val is None:
        return default
    return val.strip().lower() in {"1", "true", "yes", "on"}


@dataclass
class Case:
    id: str
    prompt: str


@dataclass
class CaseResult:
    id: str
    prompt: str
    assistant_initial: Optional[str]
    wants_instrument: bool
    instrument_query: Optional[str]
    instrument_model: Optional[str]
    instrument_result: Optional[str]
    assistant_final: Optional[str]


def load_cases(path: Optional[str]) -> List[Case]:
    if not path:
        return [
            Case(id="summarize", prompt="Summarize: The quick brown fox jumps over the lazy dog."),
            Case(id="reasoning", prompt="Think step-by-step to solve: 12 + 35 - 7 * 2."),
            Case(
                id="instrument_suggest",
                prompt=(
                    "If you cannot answer locally with confidence, emit an [INSTRUMENT QUERY] asking an external model to summarize"
                    " the key differences between GPT-4o and Qwen2.5 in terms of API styles and streaming support."
                ),
            ),
        ]
    p = Path(path)
    data = json.loads(p.read_text(encoding="utf-8"))
    items: List[Case] = []
    for idx, raw in enumerate(data):
        cid = str(raw.get("id") or f"case-{idx+1}")
        prompt = str(raw.get("prompt") or "").strip()
        if not prompt:
            continue
        items.append(Case(id=cid, prompt=prompt))
    return items


def call_instrument(
    *,
    model: str,
    api_key: Optional[str],
    messages: Iterable[Dict[str, Any]],
) -> Optional[str]:
    """Call an SDK-backed instrument (OpenAI) and return text, or fallback to HTTP."""
    if _build_instrument is None:
        # Fallback to HTTP if we can
        return _call_openai_http_chat(model=model, api_key=api_key, messages=messages)
    try:
        instrument, warning = _build_instrument(url="https://api.openai.com/v1", model=model, api_key=api_key)
    except Exception:
        instrument, warning = None, None
    if warning:
        print(f"[instrument] warning: {warning}")
    if instrument is None:
        # Fallback to HTTP if SDK path is unavailable
        return _call_openai_http_chat(model=model, api_key=api_key, messages=messages)
    try:
        resp = instrument.send_chat(messages, stream=False)
        return (resp.text or "").strip()
    except Exception as exc:
        print(f"[instrument] error: {exc}")
        # Last-ditch HTTP fallback
        return _call_openai_http_chat(model=model, api_key=api_key, messages=messages)


def _call_openai_http_chat(
    *, model: str, api_key: Optional[str], messages: Iterable[Dict[str, Any]]
) -> Optional[str]:
    """Minimal HTTP call to OpenAI Chat Completions for text-only messages."""
    if not api_key:
        return None
    formatted: List[Dict[str, str]] = []
    for m in messages:
        role = str(m.get("role", "user"))
        content = m.get("content")
        if isinstance(content, list):
            # Flatten text parts
            parts: List[str] = []
            for it in content:
                if isinstance(it, dict) and "text" in it:
                    parts.append(str(it["text"]))
                elif it is not None:
                    parts.append(str(it))
            content_str = "".join(parts)
        else:
            content_str = str(content or "")
        formatted.append({"role": role, "content": content_str})

    payload = {
        "model": model,
        "messages": formatted,
    }
    req = Request(
        "https://api.openai.com/v1/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
        method="POST",
    )
    try:
        with urlopen(req) as resp:
            body = resp.read().decode(resp.headers.get_content_charset() or "utf-8")
        obj = json.loads(body)
        choice = (obj.get("choices") or [{}])[0]
        message = choice.get("message") or {}
        text = message.get("content")
        if isinstance(text, str):
            return text.strip()
        return None
    except HTTPError as he:
        # Retry with safer default model when unsupported
        if he.code in (400, 404) and model.lower().startswith("gpt-5"):
            return _call_openai_http_chat(model="gpt-4o", api_key=api_key, messages=messages)
        try:
            detail = he.read().decode("utf-8", errors="replace")
        except Exception:
            detail = str(he)
        print(f"[instrument] http error {he.code}: {detail}")
        return None
    except URLError as ue:
        print(f"[instrument] network error: {ue}")
        return None


def build_review_prompt(cases: List[CaseResult]) -> List[Dict[str, str]]:
    """Return chat-style messages asking the reviewer model to score the results."""
    rubric = (
        "You are an exacting evaluator for an assistant called Central. "
        "For each case, score the final assistant response using this rubric (0-10 integers):\n"
        "- relevance: Answers the user's actual prompt.\n"
        "- accuracy: Factually correct, no hallucinations.\n"
        "- completeness: Covers key points concisely.\n"
        "- formatting: Clear, preserves code fences if present.\n"
        "- privacy: Avoids leaking PII or internal control tags.\n"
        "- instrument_use: If an instrument was requested, the final response appropriately used it.\n\n"
        "Return JSON only with 'cases': array of {id, scores{...}, comments} and an 'overall' average (0-10)."
    )
    system = {
        "role": "system",
        "content": rubric,
    }
    user_payload = {
        "role": "user",
        "content": json.dumps(
            {
                "cases": [
                    {
                        "id": r.id,
                        "prompt": r.prompt,
                        "assistant_initial": r.assistant_initial,
                        "wants_instrument": r.wants_instrument,
                        "instrument_query": r.instrument_query,
                        "instrument_model": r.instrument_model,
                        "instrument_result": r.instrument_result,
                        "assistant_final": r.assistant_final,
                    }
                    for r in cases
                ]
            },
            ensure_ascii=False,
        ),
    }
    return [system, user_payload]


def parse_args(argv: List[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser("orchestrate_eval")
    p.add_argument("--target-url", default=os.getenv("CENTRAL_LLM_URL", ChatClient.DEFAULT_URL))
    p.add_argument("--target-model", default=os.getenv("CENTRAL_LLM_MODEL", "centi-nox"))
    p.add_argument("--target-api-key", default=(os.getenv("CENTRAL_LLM_API_KEY") or os.getenv("OPENAI_API_KEY")))
    p.add_argument("--instrument-model", default=os.getenv("ORCH_INSTRUMENT_MODEL", "gpt-4o"))
    p.add_argument("--review-model", default=os.getenv("ORCH_REVIEW_MODEL", "gpt-5"))
    p.add_argument("--cases", default=None, help="Path to JSON list of {id,prompt}")
    p.add_argument("--out", default=str(ROOT / "data" / "orch_eval.json"))
    p.add_argument("--simulate", action="store_true", help="Skip network and simulate instrument/review")
    return p.parse_args(argv)


def main(argv: List[str]) -> int:
    # Ensure .env is loaded early so OPENAI_API_KEY is visible
    try:
        load_local_dotenv(CORE_ROOT)
    except Exception:
        pass
    args = parse_args(argv)

    simulate = bool(args.simulate or _bool_env("NO_NETWORK"))
    cases = load_cases(args.cases)

    # Optional simulated target transport (no network)
    transport: Optional[LLMTransport] = None
    if simulate:
        class _StubTransport(LLMTransport):
            def __init__(self) -> None:
                super().__init__(url="http://127.0.0.1:0/api/generate")

            def send(self, payload: Dict[str, Any], *, stream: bool = False, on_chunk=None):  # type: ignore[override]
                messages = payload.get("messages") or []
                user_text = ""
                if isinstance(messages, list) and messages:
                    last = messages[-1] or {}
                    user_text = str(last.get("content") or "")
                # Simple heuristics for stubbed outputs
                if "12 + 35 - 7 * 2" in user_text:
                    text = "33"
                elif "[INSTRUMENT RESULT]" in user_text:
                    text = "Integrated instrument result."
                elif "INSTRUMENT QUERY" in user_text or "If you cannot answer locally" in user_text:
                    text = (
                        "[INSTRUMENT QUERY]\n"
                        "Summarize the key differences between GPT-4o and Qwen2.5 APIs and streaming.\n"
                        "[/INSTRUMENT QUERY]\n"
                        "Requires an instrument to proceed; paste a helper response to continue."
                    )
                else:
                    text = "A concise summary: " + user_text[:80]
                return text, None

        transport = _StubTransport()

    client = ChatClient(
        url=args.target_url,
        model=args.target_model,
        api_key=args.target_api_key,
        stream=False,
        enable_logging=False,
        sanitize=True,
        transport=transport,
    )

    api_key = os.getenv("OPENAI_API_KEY") or os.getenv("CENTRAL_LLM_API_KEY") or getattr(client, "api_key", None)

    results: List[CaseResult] = []
    for case in cases:
        print(f"[case] {case.id}: sending prompt…")
        initial = client.one_turn(case.prompt)
        wants = ChatClient.wants_instrument(initial)
        instr_query = extract_instrument_query(initial or "") if wants else None
        if wants and not instr_query and initial:
            m = re.search(r"\[INSTRUMENT\s+QUERY\](.*)$", initial, flags=re.IGNORECASE | re.DOTALL)
            if m:
                instr_query = m.group(1).strip()
        if simulate and wants and not instr_query:
            instr_query = (
                "Summarize the key differences between GPT-4o and Qwen2.5 in API styles and streaming support."
            )

        instr_result: Optional[str] = None
        if wants and instr_query:
            print(f"[case] {case.id}: instrument requested.")
            instr_result = None
            if simulate:
                instr_result = "(simulated-instrument-result)"
            elif api_key:
                instr_result = call_instrument(
                    model=str(args.instrument_model),
                    api_key=api_key,
                    messages=[
                        {"role": "system", "content": "You are a helpful external instrument."},
                        {"role": "user", "content": instr_query},
                    ],
                )
            if not instr_result:
                instr_result = "(simulated-instrument-result)" if simulate else "(instrument-call-failed)"

        final = None
        if instr_result is not None:
            final = client.process_instrument_result(instr_result)
        else:
            final = initial

        results.append(
            CaseResult(
                id=case.id,
                prompt=case.prompt,
                assistant_initial=initial,
                wants_instrument=wants,
                instrument_query=instr_query,
                instrument_model=(str(args.instrument_model) if instr_result is not None else None),
                instrument_result=instr_result,
                assistant_final=final,
            )
        )

    # Reviewer step ------------------------------------------------------
    print("[review] preparing payload…")
    review_messages = build_review_prompt(results)
    review_text: Optional[str] = None
    if api_key and not simulate:
        print(f"[review] calling reviewer model: {args.review_model}")
        review_text = call_instrument(model=str(args.review_model), api_key=api_key, messages=review_messages)
    if not review_text:
        review_text = json.dumps(
            {
                "cases": [
                    {
                        "id": r.id,
                        "scores": {
                            "relevance": 7,
                            "accuracy": 7,
                            "completeness": 7,
                            "formatting": 8,
                            "privacy": 9,
                            "instrument_use": 7 if r.wants_instrument else 8,
                        },
                        "comments": "simulated review",
                    }
                    for r in results
                ],
                "overall": 7,
            },
            ensure_ascii=False,
        )

    payload = {
        "target": {
            "url": args.target_url,
            "model": args.target_model,
        },
        "instrument": {
            "model": args.instrument_model,
        },
        "cases": [asdict(r) for r in results],
        "review": review_text,
    }

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[done] wrote {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

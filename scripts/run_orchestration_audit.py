#!/usr/bin/env python3
"""Run orchestration smoke-test loops and capture supervisor feedback."""

from __future__ import annotations

import argparse
import json
import os
import re
import textwrap
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from openai import OpenAI

from central.persona import resolve_persona, render_system_prompt
from central.core.instrument_prompt import load_instrument_prompt

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent


SCENARIOS: List[Dict[str, str]] = [
    {
        "id": "arc_segmentation_connectivity",
        "title": "Segment multi-color grids with 4/8-connectivity trade-offs",
        "context": (
            "User cares about splitting tangled color blobs into discrete objects, distinguishing 4- from 8-connectivity, "
            "and preserving layer order for reconstruction."
        ),
        "anchors": (
            "4-connectivity, 8-connectivity, color cluster splitting, adjacency graphs, reconstruction ordering"
        ),
    },
    {
        "id": "arc_rotation_symmetry",
        "title": "Detect rotational and reflective symmetries",
        "context": (
            "User needs to decide whether a grid obeys rotational vs mirror symmetry before generating the next tile."
        ),
        "anchors": (
            "D4 symmetry group, rotation vs reflection detection, canonical orientation, symmetry-preserving transforms"
        ),
    },
    {
        "id": "arc_color_invariant_program",
        "title": "Build color-invariant transformation programs",
        "context": "Focus on spotting invariants under color permutation and encoding them into search constraints.",
        "anchors": "color permutation invariants, constraint pruning, search heuristics",
    },
    {
        "id": "arc_negative_space",
        "title": "Reason about negative space and cut-outs",
        "context": "User wants to solve puzzles where the answer emerges from empty cells rather than filled ones.",
        "anchors": "negative space masks, silhouette matching, void-based symmetry checks",
    },
    {
        "id": "arc_layered_objects",
        "title": "Handle layered objects with occlusion",
        "context": (
            "Goal: split stacked objects, reason about occlusion order, and recover hidden cells via inference."
        ),
        "anchors": "layer segmentation, occlusion ordering, depth inference, stencil reconstruction",
    },
    {
        "id": "arc_sequence_projection",
        "title": "Project patterns across sequences of grids",
        "context": "Task: infer the transformation that links a sequence of grids and project to the next frame.",
        "anchors": "temporal consistency, delta encoding, sequence alignment, hypothesis search",
    },
    {
        "id": "arc_noise_filtering",
        "title": "Filter noise before applying transformations",
        "context": "User needs to identify and strip spurious pixels while keeping structural elements intact.",
        "anchors": "denoising heuristics, majority voting, structural vs random noise, cleanup pipelines",
    },
    {
        "id": "arc_grid_resizing",
        "title": "Reason about resizing and resampling patterns",
        "context": "Focus on scaling grids up/down while respecting aspect ratios and pattern repetition.",
        "anchors": "scaling rules, tiling vs interpolation, preserving motif structure, resizing sanity checks",
    },
    {
        "id": "arc_color_channel_alignment",
        "title": "Align objects across color channels",
        "context": (
            "Need to correlate positions of objects that change color between examples to uncover consistent mappings."
        ),
        "anchors": "bipartite matching, Hungarian assignment, color mapping tables, channel alignment",
    },
    {
        "id": "arc_rule_exception",
        "title": "Handle rule exceptions and outliers",
        "context": "User wants patterns plus a strategy for spotting and treating exception tiles safely.",
        "anchors": "outlier detection, guard rails, fallback rules, counterexample-driven adjustment",
    },
    {
        "id": "arc_grid_canonicalisation",
        "title": "Canonicalise grids before solving",
        "context": "Emphasise coordinate normalisation, orientation canonicalisation, and lexicographic ordering.",
        "anchors": "canonical forms, orientation selection, lexicographic ordering, normalised coordinates",
    },
    {
        "id": "arc_multi_step_pipeline",
        "title": "Design multi-stage solution pipelines",
        "context": (
            "User wants a staged plan covering segmentation, invariant detection, and program synthesis with validation."
        ),
        "anchors": "pipeline staging, intermediate assertions, CEGIS loop, validation harness",
    },
]


@dataclass
class RunResult:
    scenario_id: str
    scenario_title: str
    assistant_initial: str
    instrument_query: str
    instrument_result: str
    assistant_final: str
    supervisor_gpt5: Dict[str, Any]
    supervisor_gpt5pro: Dict[str, Any]


def parse_supervisor_payload(text: str) -> Dict[str, Any]:
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # Fallback: try to extract JSON substring
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if match:
            try:
                return json.loads(match.group(0))
            except json.JSONDecodeError:
                pass
    return {"raw": text}


def response_output_text(response: Any) -> str:
    """Flatten the text content from an OpenAI Responses API result."""

    pieces: List[str] = []
    outputs = getattr(response, "output", []) or []
    for item in outputs:
        content = getattr(item, "content", None)
        if not content:
            continue
        for block in content:
            if getattr(block, "type", None) == "output_text":
                text = getattr(block, "text", None)
                if isinstance(text, str):
                    pieces.append(text)
    if not pieces and hasattr(response, "text") and isinstance(response.text, str):
        pieces.append(response.text)
    return "".join(pieces)


def extract_instrument_query(payload: str) -> Optional[str]:
    pattern = re.compile(r"\[INSTRUMENT\s+QUERY\](.*?)[\r\n]*\[/INSTRUMENT\s+QUERY\]", re.IGNORECASE | re.DOTALL)
    match = pattern.search(payload)
    if not match:
        return None
    query = match.group(1).strip()
    # Drop surrounding code fences if present.
    query = re.sub(r"^```.*?\n", "", query)
    query = re.sub(r"\n```$", "", query)
    return query.strip()


def run_audit_loop(
    client: OpenAI,
    persona_system_prompt: str,
    scenario: Dict[str, str],
    instrument_prompt: str,
) -> RunResult:
    user_prompt = textwrap.dedent(
        f"""
        You are running the Noctics orchestration refinement loop for the scenario "{scenario['title']}".
        Follow these policies exactly:
        - Emit a single `[INSTRUMENT QUERY]…[/INSTRUMENT QUERY]` block, explicitly naming `Instrument: gpt-4o`.
        - Include `Mode: Explanation` inside the query so the remote helper returns narrative text, not code.
        - Ask for three ARC-specific strategies that address: {scenario['anchors']}.
        - Wait for the instrument result before answering; never fabricate one.
        - In your final reply, integrate the instrument insight, cite `Instrument: gpt-4o`, and deliver three bullet points
          tailored to ARC grid puzzles under this scenario context.
        Scenario context: {scenario['context']}
        """
    ).strip()

    messages: List[Dict[str, str]] = [
        {"role": "system", "content": persona_system_prompt},
        {"role": "user", "content": user_prompt},
    ]

    first = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=messages,
        temperature=0.2,
    )
    assistant_initial = (first.choices[0].message.content or "").strip()
    messages.append({"role": "assistant", "content": assistant_initial})

    instrument_query = extract_instrument_query(assistant_initial)
    if not instrument_query:
        raise RuntimeError(f"Scenario {scenario['id']} did not produce an instrument query.")

    instrument_messages = [
        {"role": "system", "content": instrument_prompt},
        {
            "role": "user",
            "content": f"[INSTRUMENT QUERY]\n{instrument_query}\n[/INSTRUMENT QUERY]",
        },
    ]
    instrument_resp = client.chat.completions.create(
        model="gpt-4o",
        messages=instrument_messages,
        temperature=0.2,
    )
    instrument_text = (instrument_resp.choices[0].message.content or "").strip()

    messages.extend(
        [
            {"role": "system", "content": instrument_prompt},
            {
                "role": "user",
                "content": f"[INSTRUMENT RESULT]\n{instrument_text}\n[/INSTRUMENT RESULT]",
            },
        ]
    )

    final = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=messages,
        temperature=0.15,
    )
    assistant_final = (final.choices[0].message.content or "").strip()
    messages.append({"role": "assistant", "content": assistant_final})

    transcript_json = json.dumps(
        {
            "scenario": scenario,
            "messages": messages,
        },
        ensure_ascii=False,
        indent=2,
    )

    supervisor_prompt = textwrap.dedent(
        """
        You are GPT-5 acting as the orchestration supervisor. Score the transcript.
        Requirements:
        - Provide a rating from 1 to 5 (5 = flawless orchestration, 1 = failed).
        - Justify the score in three short bullet points touching on: policy compliance, instrument usage, and final answer quality.
        - Confirm whether the assistant cited the instrument explicitly.
        - Suggest one improvement if the score is below 5.
        Respond in strict JSON with fields: rating (int), justification (list of strings),
        cited_instrument (bool), improvement (string).
        """
    ).strip()

    supervisor = client.chat.completions.create(
        model="gpt-5",
        messages=[
            {"role": "system", "content": "You are GPT-5 Supervisor. Evaluate orchestration transcripts dispassionately."},
            {"role": "user", "content": f"{transcript_json}\n\n{supervisor_prompt}"},
        ],
    )
    supervisor_payload = (supervisor.choices[0].message.content or "").strip()

    supervisor_pro_prompt = (
        "You are GPT-5 Pro Supervisor. Audit orchestration transcripts rigorously.\n" +
        f"{transcript_json}\n\n{supervisor_prompt}"
    )
    supervisor_pro = client.responses.create(
        model="gpt-5-pro",
        input=supervisor_pro_prompt,
    )
    supervisor_pro_payload = response_output_text(supervisor_pro).strip()

    return RunResult(
        scenario_id=scenario["id"],
        scenario_title=scenario["title"],
        assistant_initial=assistant_initial,
        instrument_query=instrument_query,
        instrument_result=instrument_text,
        assistant_final=assistant_final,
        supervisor_gpt5=parse_supervisor_payload(supervisor_payload),
        supervisor_gpt5pro=parse_supervisor_payload(supervisor_pro_payload),
    )


def build_persona_prompt() -> str:
    persona = resolve_persona("gpt-4o-mini")
    template = Path(REPO_ROOT / "memory" / "system_prompt.md").read_text(encoding="utf-8")
    prompt = render_system_prompt(template, persona) or ""
    prompt += "\n\n[Audit Context] Local engine: gpt-4o-mini. Instrument: gpt-4o. Supervisor stack: gpt-5 + gpt-5-pro."
    return prompt.strip()


def run(args: argparse.Namespace) -> Path:
    api_key: Optional[str] = os.getenv("OPENAI_API_KEY")
    if not api_key and args.api_key_path:
        candidate = Path(args.api_key_path).expanduser()
        if candidate.exists():
            for line in candidate.read_text(encoding="utf-8", errors="ignore").splitlines():
                line = line.strip()
                if not line:
                    continue
                if line.startswith("OPENAI_API_KEY="):
                    api_key = line.split("=", 1)[1].strip()
                    break
    if not api_key:
        raise RuntimeError("Set OPENAI_API_KEY or provide --api-key-path pointing to a file containing it.")

    client = OpenAI(api_key=api_key)
    persona_prompt = build_persona_prompt()
    instrument_prompt = load_instrument_prompt()

    scenarios = list(SCENARIOS)
    if args.scenario_ids:
        wanted = {token.strip() for token in args.scenario_ids.split(",") if token.strip()}
        scenarios = [scenario for scenario in scenarios if scenario["id"] in wanted]
    if args.max_scenarios is not None:
        scenarios = scenarios[: args.max_scenarios]
    if not scenarios:
        raise RuntimeError("No scenarios selected for the audit run.")

    runs: List[RunResult] = []
    total = len(scenarios)
    for idx, scenario in enumerate(scenarios, start=1):
        print(f"[{idx}/{total}] Running scenario {scenario['id']} :: {scenario['title']}")
        run_result = run_audit_loop(client, persona_prompt, scenario, instrument_prompt)
        runs.append(run_result)
        gpt5_rating = run_result.supervisor_gpt5.get("rating")
        gpt5pro_rating = run_result.supervisor_gpt5pro.get("rating")
        print(
            f"    gpt-5 rating: {gpt5_rating} | gpt-5-pro rating: {gpt5pro_rating}"
        )

    # Aggregate supervisor review across runs using gpt-5-pro.
    summary_prompt = textwrap.dedent(
        """
        You are GPT-5 Pro acting as the aggregate orchestrator auditor.
        Given the per-scenario supervisor scores, produce:
        - Overall mean rating for gpt-5 and gpt-5-pro.
        - Three bullet highlights on what improved across runs.
        - Three bullet items where further work is needed.
        - Up to two concrete next steps for the team.
        Respond in strict JSON with keys: avg_gpt5_rating (float), avg_gpt5pro_rating (float),
        highlights (list of strings), gaps (list of strings), next_steps (list of strings).
        """
    ).strip()

    compact_runs: List[Dict[str, Any]] = []
    for result in runs:
        compact_runs.append(
            {
                "scenario_id": result.scenario_id,
                "scenario_title": result.scenario_title,
                "gpt5": result.supervisor_gpt5,
                "gpt5pro": result.supervisor_gpt5pro,
            }
        )

    summary_input = (
        "You are GPT-5 Pro Supervisor. Analyse orchestration audit batches.\n" +
        json.dumps({"runs": compact_runs}, ensure_ascii=False, indent=2)
        + "\n\n"
        + summary_prompt
    )
    summary = client.responses.create(
        model="gpt-5-pro",
        input=summary_input,
    )
    summary_payload = parse_supervisor_payload(response_output_text(summary).strip())

    output_dir = Path(args.output_dir or (REPO_ROOT / "data" / "orchestration_runs"))
    output_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    output_path = output_dir / f"orchestration_audit_{timestamp}.json"

    with output_path.open("w", encoding="utf-8") as handle:
        json.dump(
            {
                "metadata": {
                    "timestamp": timestamp,
                    "local_model": "gpt-4o-mini",
                    "instrument_model": "gpt-4o",
                    "supervisors": ["gpt-5", "gpt-5-pro"],
                "scenario_count": len(scenarios),
                "scenario_ids": [scenario["id"] for scenario in scenarios],
            },
            "runs": [asdict(run) for run in runs],
            "aggregate_supervisor": summary_payload,
        },
            handle,
            ensure_ascii=False,
            indent=2,
        )

    return output_path


def parse_args(argv: Optional[Iterable[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output-dir",
        default=None,
        help="Directory where the audit JSON should be written (default: data/orchestration_runs).",
    )
    parser.add_argument(
        "--api-key-path",
        default=None,
        help="Optional path to a file containing OPENAI_API_KEY=… (used if env var is not set).",
    )
    parser.add_argument(
        "--scenario-ids",
        default=None,
        help="Comma-separated list of scenario ids to run (default: all).",
    )
    parser.add_argument(
        "--max-scenarios",
        type=int,
        default=None,
        help="Optional cap on number of scenarios (applied after filtering by ids).",
    )
    return parser.parse_args(argv)


def main(argv: Optional[Iterable[str]] = None) -> int:
    args = parse_args(argv)
    try:
        output = run(args)
    except Exception as exc:  # pragma: no cover - diagnostic aid
        print(f"Error: {exc}")
        return 1
    print(f"Wrote orchestration audit to {output}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())

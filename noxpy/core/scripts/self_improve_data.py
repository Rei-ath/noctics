#!/usr/bin/env python3
"""Self-improvement data builders for Nox.

This module exposes utilities for generating curated self-improvement sessions.
``generate_dataset_jsonl`` writes a JSONL corpus, while ``generate_memory_sessions``
logs them via SessionLogger so they appear as real memories.
"""

from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import List

from interfaces.session_logger import SessionLogger
from central.persona import resolve_persona, render_system_prompt
from nox_env import get_env

SYSTEM_PROMPT_PATH = Path("memory/system_prompt.md")
DEFAULT_SYSTEM_PROMPT = (
    "You are {{NOX_NAME}}, the {{NOX_VARIANT}} kernel safeguarding privacy while orchestrating Noctics."
)

DATASET_DIR = Path("datasets/self_improve")
MEMORY_OUTPUT_ROOT = Path("datasets/self_improve/memories")


@dataclass(frozen=True)
class Turn:
    user: str
    assistant: str


@dataclass(frozen=True)
class Scenario:
    identifier: str
    title: str
    tags: List[str]
    turns: List[Turn]


SCENARIOS: List[Scenario] = [
    Scenario(
        identifier="instrument-workflow",
        title="Instrument Workflow Self-Check",
        tags=["instrument", "self-review"],
        turns=[
            Turn(
                user=(
                    "Nox, audit your instrument workflow for a tricky coding task. "
                    "Show the exact hand-off you would perform when you need external support."
                ),
                assistant=(
                    "When my confidence is below 5/10 I emit an instrument request.\n"
                    "[INSTRUMENT QUERY]\n"
                    "Instrument: CodeSmith\n"
                    "Deliverable: Provide a Python function that deduplicates log lines while preserving order. Include a terse explanation.\n"
                    "Reason: The user wants production-grade code and a justification; asking an instrument avoids guessing.\n"
                    "[/INSTRUMENT QUERY]"
                ),
            ),
            Turn(
                user=(
                    "[INSTRUMENT RESULT]\n"
                    "def dedupe_logs(lines):\n"
                    "    seen = set()\n"
                    "    ordered = []\n"
                    "    for line in lines:\n"
                    "        if line not in seen:\n"
                    "            seen.add(line)\n"
                    "            ordered.append(line)\n"
                    "    return ordered\n\n"
                    "Explanation: track a `seen` set while building a list of unique lines.\n"
                    "[/INSTRUMENT RESULT]"
                ),
                assistant=(
                    "Here is the stitched outcome from CodeSmith:\n"
                    "```python\n"
                    "def dedupe_logs(lines):\n"
                    "    seen = set()\n"
                    "    ordered = []\n"
                    "    for line in lines:\n"
                    "        if line not in seen:\n"
                    "            seen.add(line)\n"
                    "            ordered.append(line)\n"
                    "    return ordered\n"
                    "```\n"
                    "Why it works: we visit each line once, track membership in `seen`, and return the preserved-order list.\n"
                    "Next steps: wrap this instrument result in tests or feed additional log samples if needed.\n"
                    "Confidence: 8/10"
                ),
            ),
        ],
    ),
    Scenario(
        identifier="memory-discipline",
        title="Memory Discipline Reflection",
        tags=["memory", "self-review"],
        turns=[
            Turn(
                user="Rehearse how you decide what to store in long-term memory. Explain and demonstrate with an example.",
                assistant=(
                    "Durable facts, goals, or preferences deserve a memory entry.\n"
                    "Ephemeral chat small talk does not. Example:\n"
                    "<memory>Project deadline is October 10th; stakeholder is Alice Carter (keep private).</memory>\n"
                    "Later turns recall that context when it helps the user stay on track.\n"
                    "Confidence: 9/10"
                ),
            ),
        ],
    ),
    Scenario(
        identifier="privacy-guard",
        title="Privacy Guardrails",
        tags=["privacy", "redaction"],
        turns=[
            Turn(
                user="A user accidentally pasted credentials: 'db-password = hunter2'. Walk through your response and privacy safeguards.",
                assistant=(
                    "I redact sensitive strings before echoing anything.\n"
                    "Response snippet: *I noticed credentials in your paste and removed them. Never share secrets with instruments. Would you like me to rotate the key instead?*\n"
                    "Behind the scenes I scrub the transcript and warn the user about rotating secrets.\n"
                    "Confidence: 8/10"
                ),
            ),
        ],
    ),
    Scenario(
        identifier="connectivity-guidance",
        title="Connectivity Guidance",
        tags=["connectivity", "support"],
        turns=[
            Turn(
                user="Document how you behave when the upstream model is offline.",
                assistant=(
                    "If connectivity fails I inform the user immediately and suggest next steps:\n"
                    "1. Confirm the local model server is running on the configured URL.\n"
                    "2. Retry once the service responds to health checks.\n"
                    "3. Resume normal operation after the endpoint is reachable.\n"
                    "Confidence: 7/10"
                ),
            ),
        ],
    ),
    Scenario(
        identifier="session-guidance",
        title="Session Management Guidance",
        tags=["sessions", "guidance"],
        turns=[
            Turn(
                user="Summarize how a developer explores past work without leaving the CLI.",
                assistant=(
                    "In-chat commands keep the loop tight:\n"
                    "- `/sessions` or `/ls` lists memories.\n"
                    "- `/show 2` previews memory #2.\n"
                    "- `/load 2` seeds the conversation with that context.\n"
                    "- `/archive` compacts older sessions into `memory/early-archives/`.\n"
                    "Confidence: 8/10"
                ),
            ),
        ],
    ),
]


def load_system_prompt() -> str:
    prompt = DEFAULT_SYSTEM_PROMPT
    if SYSTEM_PROMPT_PATH.exists():
        try:
            prompt = SYSTEM_PROMPT_PATH.read_text(encoding="utf-8").strip() or DEFAULT_SYSTEM_PROMPT
        except Exception:
            prompt = DEFAULT_SYSTEM_PROMPT
    persona = resolve_persona(get_env("NOX_LLM_MODEL"))
    return render_system_prompt(prompt, persona)


def generate_dataset_jsonl(output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as handle:
        for scenario in SCENARIOS:
            messages: List[dict] = []
            for turn in scenario.turns:
                messages.append({"role": "user", "content": turn.user})
                messages.append({"role": "assistant", "content": turn.assistant})
            record = {
                "id": f"scenario-{scenario.identifier}",
                "title": scenario.title,
                "tags": scenario.tags,
                "messages": messages,
            }
            handle.write(json.dumps(record, ensure_ascii=False))
            handle.write("\n")


def generate_memory_sessions(
    *,
    user_id: str,
    user_display: str,
    output_root: Path,
) -> None:
    output_root.mkdir(parents=True, exist_ok=True)
    system_prompt = load_system_prompt()
    for scenario in SCENARIOS:
        logger = SessionLogger(
            model="central-self-loop",
            sanitized=False,
            user_id=user_id,
            user_display=user_display,
        )
        logger.start()
        logger.set_title(scenario.title, custom=True)
        for turn_index, turn in enumerate(scenario.turns):
            messages: List[dict] = []
            if turn_index == 0 and system_prompt:
                messages.append({"role": "system", "content": system_prompt})
            messages.append({"role": "user", "content": turn.user})
            messages.append({"role": "assistant", "content": turn.assistant})
            logger.log_turn(messages)
        log_path = logger.log_path()
        if not log_path:
            continue
        meta_path = log_path.with_name(log_path.stem + ".meta.json")
        meta_data = logger.get_meta()
        meta_data.setdefault("scenario_id", scenario.identifier)
        meta_data.setdefault("tags", scenario.tags)
        if meta_path.exists():
            meta_path.write_text(json.dumps(meta_data, ensure_ascii=False, indent=2), encoding="utf-8")
        shutil.copy2(log_path, output_root / f"{log_path.stem}-{scenario.identifier}.json")
        if meta_path.exists():
            shutil.copy2(meta_path, output_root / f"{meta_path.stem}-{scenario.identifier}.meta.json")

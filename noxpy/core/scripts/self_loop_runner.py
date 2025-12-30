#!/usr/bin/env python3
"""Run self-improvement simulations using the real ChatClient."""

from __future__ import annotations

import json
import shutil
from datetime import datetime
from pathlib import Path
from typing import Sequence

import sys
from urllib.error import URLError

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from central.core import ChatClient  # noqa: E402
from central.colors import color  # noqa: E402

DATASET_DIR = Path("datasets/self_loop")
DATASET_JSONL = DATASET_DIR / "self_loop.jsonl"
MEMORY_COPY_DIR = DATASET_DIR / "memories"
DEFAULT_USER_ID = "self-loop"
DEFAULT_USER_DISPLAY = "Self Loop"
TURNS_PER_SESSION = 10
SESSIONS_PER_RUN = 1

TOPICS: Sequence[str] = (
    "instrument workflow & confidence thresholds",
    "privacy and redaction safeguards",
    "memory capture / recall discipline",
    "connectivity guidance and service recovery",
    "session browsing and developer UX",
    "tone, clarity, and actionable guidance",
    "evaluating dataset quality and coverage",
    "self-audit: misfires and blind spots",
    "strategies for iterative improvement",
    "closing summary and next experiment",
)


def _build_user_prompt(session_index: int, turn_index: int, previous_summary: str | None) -> tuple[str, str]:
    topic = TOPICS[turn_index % len(TOPICS)]
    header = (
        f"Self-improvement simulation (session {session_index + 1}, turn {turn_index + 1}/"
        f"{TURNS_PER_SESSION})."
    )
    awareness = (
        "You are fully aware this is an internal loop where Nox plays user, instrument, "
        "and assistant roles to generate training data."
    )
    focus = (
        f"Focus topic: {topic}. Provide candid reflection, highlight concrete behaviours, "
        "and propose actionable next steps."
    )
    improv = (
        "Improvise without calling external instruments; if you discuss instruments, narrate the "
        "workflow hypothetically."
    )
    continuity = (
        f"Build on the previous insight: {previous_summary}" if previous_summary else "Start by orienting the reflection."
    )
    style = (
        "Write in the usual production tone (concise, GPT-4o-like) using 2-4 short paragraphs "
        "or bullet lists. End with a `Confidence: X/10` line."
    )
    prompt = " ".join([header, awareness, focus, improv, continuity, style])
    return prompt, topic


def _summarize(text: str, limit: int = 160) -> str:
    compact = " ".join(text.strip().split())
    return compact[:limit] + ("…" if len(compact) > limit else "")


def _copy_session(log_path: Path, tag: str) -> None:
    if not log_path.exists():
        return
    MEMORY_COPY_DIR.mkdir(parents=True, exist_ok=True)
    target = MEMORY_COPY_DIR / f"{log_path.stem}-{tag}.json"
    shutil.copy2(log_path, target)
    meta_path = log_path.with_name(log_path.stem + ".meta.json")
    if meta_path.exists():
        shutil.copy2(meta_path, MEMORY_COPY_DIR / f"{meta_path.stem}-{tag}.meta.json")


def _offline_response(topic: str, previous_summary: str | None, turn_index: int) -> str:
    intro = (
        f"Connectivity to the model endpoint is unavailable while reflecting on {topic}."
        " I notify the user, recommend restarting or verifying the local server, and wait for a successful retry."
    )
    guidance = "Action: ensure the configured URL is reachable, then rerun the request."
    confidence = "Confidence: 6/10"
    if previous_summary:
        return "\n".join([intro, f"Previous insight: {previous_summary}", guidance, confidence])
    return "\n".join([intro, guidance, confidence])


def run_self_loop(
    *,
    sessions: int = SESSIONS_PER_RUN,
    turns: int = TURNS_PER_SESSION,
    memory_user: str = DEFAULT_USER_ID,
    memory_display: str = DEFAULT_USER_DISPLAY,
    verbose: bool = True,
) -> None:
    DATASET_DIR.mkdir(parents=True, exist_ok=True)
    previous_summary: str | None = None

    with DATASET_JSONL.open("a", encoding="utf-8") as dataset_file:
        for session_index in range(sessions):
            client = ChatClient(
                stream=False,
                sanitize=False,
                enable_logging=True,
                memory_user=memory_user,
                memory_user_display=memory_display,
            )

            client.set_session_title(f"Self Loop {session_index + 1}", custom=True)
            session_id = datetime.now().strftime("%Y%m%d-%H%M%S")

            offline_notice_emitted = False

            for turn_index in range(turns):
                prompt, topic = _build_user_prompt(session_index, turn_index, previous_summary)
                if verbose:
                    print(color(f"\n[Session {session_index + 1}] USER", fg="cyan", bold=True))
                    print(color(prompt, fg="cyan"))
                try:
                    assistant = client.one_turn(prompt)
                    if assistant is None:
                        assistant = "(No response captured.)"
                except URLError:
                    assistant = _offline_response(topic, previous_summary, turn_index)
                    client.record_turn(prompt, assistant)
                    if verbose and not offline_notice_emitted:
                        print(color("Connectivity unavailable – switching to offline synthesis.", fg="yellow", bold=True))
                        offline_notice_emitted = True
                if verbose:
                    print(color(f"[Session {session_index + 1}] ASSISTANT", fg="magenta", bold=True))
                    print(color(assistant, fg="magenta"))
                previous_summary = _summarize(assistant)

            meta = client.logger.get_meta() if client.logger else {}
            log_path = client.logger.log_path() if client.logger else None

            record = {
                "id": f"self-loop-{session_id}-{session_index}",
                "title": meta.get("title") or f"Self Loop {session_index + 1}",
                "tags": ["self-loop"],
                "user_id": memory_user,
                "user_display": memory_display,
                "messages": client.messages,
            }
            dataset_file.write(json.dumps(record, ensure_ascii=False))
            dataset_file.write("\n")

            if log_path:
                _copy_session(log_path, f"self-loop-{session_index}")

    summary = (
        f"Generated {sessions} self-loop session(s) with {turns} turns each. "
        f"Dataset appended to {DATASET_JSONL} and copies stored under {MEMORY_COPY_DIR}."
    )
    print(color(summary, fg="green", bold=True))


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Run self-loop simulations.")
    parser.add_argument("--sessions", type=int, default=SESSIONS_PER_RUN)
    parser.add_argument("--turns", type=int, default=TURNS_PER_SESSION)
    parser.add_argument("--user", default=DEFAULT_USER_ID)
    parser.add_argument("--display", default=DEFAULT_USER_DISPLAY)
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args()

    run_self_loop(
        sessions=args.sessions,
        turns=args.turns,
        memory_user=args.user,
        memory_display=args.display,
        verbose=not args.quiet,
    )

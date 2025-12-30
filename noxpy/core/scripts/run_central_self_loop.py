#!/usr/bin/env python3
"""Run the predefined self-improvement scenarios and store the memories."""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path
from typing import Iterable

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from interfaces.session_logger import SessionLogger  # noqa: E402
from scripts.self_improve_data import SCENARIOS, Scenario, load_system_prompt  # noqa: E402


def log_scenario(
    scenario: Scenario,
    *,
    logger: SessionLogger,
    system_prompt: str,
) -> Path:
    """Log the scenario via the provided logger and return the session path."""

    logger.start()
    logger.set_title(scenario.title, custom=True)

    for turn_index, turn in enumerate(scenario.turns):
        messages = []
        if turn_index == 0 and system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": turn.user})
        messages.append({"role": "assistant", "content": turn.assistant})
        logger.log_turn(messages)

    log_path = logger.log_path()
    meta_path = logger.meta_path()
    if meta_path and meta_path.exists():
        meta_data = logger.get_meta()
        meta_data.setdefault("scenario_id", scenario.identifier)
        meta_data.setdefault("tags", scenario.tags)
        meta_path.write_text(json.dumps(meta_data, ensure_ascii=False, indent=2), encoding="utf-8")
    return log_path if log_path else Path()


def copy_session_files(log_path: Path, output_root: Path, scenario_id: str) -> None:
    if not log_path or not log_path.exists():
        return
    meta_path = log_path.with_name(log_path.stem + ".meta.json")
    output_root.mkdir(parents=True, exist_ok=True)
    shutil.copy2(log_path, output_root / f"{log_path.stem}-{scenario_id}.json")
    if meta_path.exists():
        shutil.copy2(meta_path, output_root / f"{meta_path.stem}-{scenario_id}.meta.json")


def run_scenarios(
    scenarios: Iterable[Scenario],
    *,
    user_id: str,
    user_display: str,
    output_root: Path,
) -> None:
    system_prompt = load_system_prompt()
    for scenario in scenarios:
        logger = SessionLogger(
            model="central-self-loop",
            sanitized=False,
            user_id=user_id,
            user_display=user_display,
        )
        log_path = log_scenario(scenario, logger=logger, system_prompt=system_prompt)
        copy_session_files(log_path, output_root, scenario.identifier)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run Nox self-improvement scenarios.")
    parser.add_argument(
        "--output-root",
        type=Path,
        default=Path("datasets/self_improve/memories"),
        help="Directory where generated sessions are copied (default: datasets/self_improve/memories)",
    )
    parser.add_argument(
        "--user",
        default="central-self",
        help="Memory user identifier (slug). Default: central-self",
    )
    parser.add_argument(
        "--display",
        default="Nox Self",
        help="Memory user display name. Default: Nox Self",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    run_scenarios(
        SCENARIOS,
        user_id=args.user,
        user_display=args.display,
        output_root=args.output_root,
    )
    print(f"Logged {len(SCENARIOS)} scenarios as user '{args.user}' and copied to {args.output_root}")


if __name__ == "__main__":
    main()

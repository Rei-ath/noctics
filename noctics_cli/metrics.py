"""Local adoption metrics utilities for the Noctics CLI."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict


def _load_metrics(metrics_path: Path) -> Dict[str, Any]:
    if not metrics_path.exists():
        return {}
    try:
        raw = metrics_path.read_text(encoding="utf-8")
    except OSError:
        return {}
    if not raw.strip():
        return {}
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    if isinstance(data, dict):
        return data
    return {}


def record_cli_run(memory_root: Path, version: str, *, now: datetime | None = None) -> None:
    """Persist lightweight adoption metrics for local analysis.

    Metrics are stored under ``<memory_root>/telemetry/metrics.json`` so they
    travel with other on-disk state but never leave the user's machine.
    """

    metrics_dir = memory_root / "telemetry"
    metrics_dir.mkdir(parents=True, exist_ok=True)
    metrics_path = metrics_dir / "metrics.json"

    data = _load_metrics(metrics_path)
    total_runs = int(data.get("total_runs") or 0) + 1
    per_version = data.get("per_version") or {}
    if not isinstance(per_version, dict):
        per_version = {}
    per_version[str(version)] = int(per_version.get(str(version)) or 0) + 1

    now = now or datetime.now(timezone.utc)
    timestamps = data.get("run_history") or []
    if isinstance(timestamps, list):
        timestamps.append(now.isoformat())
        # Keep the most recent 200 entries to cap file size.
        timestamps = timestamps[-200:]
    else:
        timestamps = [now.isoformat()]

    data.update(
        {
            "total_runs": total_runs,
            "last_run": now.isoformat(),
            "per_version": per_version,
            "run_history": timestamps,
        }
    )

    tmp_path = metrics_path.with_suffix(".tmp")
    try:
        tmp_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        tmp_path.replace(metrics_path)
    except OSError:
        # Best-effort only; ignore persistence issues.
        tmp_path.unlink(missing_ok=True)

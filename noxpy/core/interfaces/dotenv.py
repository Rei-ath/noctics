"""
Tiny .env loader with no external dependencies.

Loads key=value pairs from one or more .env files without overwriting
existing environment variables. Intended for local/dev usage.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Iterable


def load_dotenv_files(paths: Iterable[Path]) -> None:
    for p in paths:
        try:
            if not p.exists():
                continue
            for line in p.read_text(encoding="utf-8").splitlines():
                s = line.strip()
                if not s or s.startswith("#") or "=" not in s:
                    continue
                k, v = s.split("=", 1)
                k = k.strip()
                v = v.strip().strip('"').strip("'")
                if k and k not in os.environ:
                    os.environ[k] = v
        except Exception:
            # Best-effort: ignore malformed lines/files
            continue


def load_local_dotenv(here: Path | None = None) -> None:
    """Load .env from the package folder and nearby working directories.

    Does not overwrite existing environment variables.
    """
    if os.getenv("NOCTICS_SKIP_DOTENV") == "1":
        return
    if here is None:
        here = Path(__file__).resolve().parent
    candidates: list[Path] = [here / ".env", Path.cwd() / ".env"]

    # Also check a few ancestor directories (e.g., repo root when running from core/).
    for parent in list(here.parents)[:3]:
        candidates.append(parent / ".env")

    unique_candidates: list[Path] = []
    seen: set[str] = set()
    for path in candidates:
        try:
            resolved = path.resolve()
        except Exception:
            resolved = path
        key = str(resolved)
        if key in seen:
            continue
        seen.add(key)
        unique_candidates.append(path)

    load_dotenv_files(unique_candidates)

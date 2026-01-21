"""Runtime configuration loader for Nox."""

from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

__all__ = [
    "NoxConfig",
    "InstrumentConfig",
    "DeveloperConfig",
    "get_runtime_config",
    "reload_config",
]

_CONFIG_ENV = "NOX_CONFIG"
def _global_config_roots() -> List[Path]:
    roots: List[Path] = []
    env_root = os.getenv("NOCTICS_CONFIG_HOME")
    if env_root:
        roots.append(Path(env_root).expanduser())
    home = Path.home()
    if sys.platform == "win32":
        base = Path(os.getenv("APPDATA", home / "AppData" / "Roaming"))
        roots.extend([base / "Noctics", base / "noctics"])
    elif sys.platform == "darwin":
        base = home / "Library/Application Support"
        roots.extend([base / "Noctics", base / "noctics"])
    else:
        xdg = Path(os.getenv("XDG_CONFIG_HOME", home / ".config"))
        roots.extend([xdg / "noctics", home / ".config/noctics"])
    deduped: List[Path] = []
    for root in roots:
        expanded = root.expanduser()
        if expanded not in deduped:
            deduped.append(expanded)
    return deduped


def _default_config_locations() -> List[Path]:
    base_locations = [
        Path("config/central.local.json"),
        Path("config/central.json"),
        Path("central.local.json"),
        Path("central.json"),
    ]
    global_locations: List[Path] = []
    for root in _global_config_roots():
        global_locations.extend(
            [
                root / "central.local.json",
                root / "central.json",
            ]
        )
    seen: List[Path] = []
    for candidate in base_locations + global_locations:
        if candidate not in seen:
            seen.append(candidate)
    return seen


_DEFAULT_CONFIG_LOCATIONS: tuple[Path, ...] = tuple(_default_config_locations())


@dataclass(slots=True)
class InstrumentConfig:
    automation: bool = False
    roster: List[str] = field(default_factory=list)


@dataclass(slots=True)
class DeveloperConfig:
    passphrase: Optional[str] = None


@dataclass(slots=True)
class NoxConfig:
    instrument: InstrumentConfig = field(default_factory=InstrumentConfig)
    developer: DeveloperConfig = field(default_factory=DeveloperConfig)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "NoxConfig":
        if isinstance(data, dict):
            instrument_data = data.get("instrument")
            if not isinstance(instrument_data, dict):
                instrument_data = {}
        else:
            instrument_data = {}

        automation = (
            bool(instrument_data.get("automation", False)) if isinstance(instrument_data, dict) else False
        )
        roster_raw = (
            instrument_data.get("roster", []) if isinstance(instrument_data, dict) else []
        )
        roster = [str(item).strip() for item in roster_raw if str(item).strip()]
        instrument = InstrumentConfig(automation=automation, roster=roster)
        developer_data = data.get("developer", {}) if isinstance(data, dict) else {}
        passphrase_raw = developer_data.get("passphrase") if isinstance(developer_data, dict) else None
        passphrase = str(passphrase_raw).strip() if passphrase_raw is not None else None
        developer = DeveloperConfig(passphrase=passphrase or None)
        return cls(instrument=instrument, developer=developer)


def _candidate_paths(explicit: Optional[Path]) -> Iterable[Path]:
    if explicit is not None:
        yield explicit
    env_path = os.getenv(_CONFIG_ENV)
    if env_path:
        yield Path(env_path)
    yield from _DEFAULT_CONFIG_LOCATIONS


def _load_config(path: Optional[Path] = None) -> NoxConfig:
    for candidate in _candidate_paths(path):
        try:
            if candidate.exists():
                data = json.loads(candidate.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    return NoxConfig.from_dict(data)
        except Exception:
            continue
    return NoxConfig()


@lru_cache(maxsize=1)
def get_runtime_config() -> NoxConfig:
    """Return the cached runtime configuration."""

    return _load_config(None)


def reload_config(path: Optional[Path] = None) -> NoxConfig:
    """Reload configuration from disk, bypassing the cache."""

    get_runtime_config.cache_clear()  # type: ignore[attr-defined]
    return get_runtime_config() if path is None else _load_config(path)

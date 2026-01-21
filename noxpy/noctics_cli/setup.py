"""First-launch setup utilities for Noctics."""

from __future__ import annotations

import getpass
import json
import os
import sys
from pathlib import Path
from typing import Dict, Optional

from central.config import get_runtime_config, reload_config
from central.colors import color

import nox_env
from noctics_cli.paths import config_home

PROVIDERS: Dict[str, Dict[str, str]] = {
    "openai": {
        "label": "OpenAI (GPT-4o)",
        "env": "OPENAI_API_KEY",
        "url": "https://platform.openai.com/api-keys",
        "roster": "openai",
    },
    "anthropic": {
        "label": "Anthropic (Claude)",
        "env": "ANTHROPIC_API_KEY",
        "url": "https://console.anthropic.com/keys",
        "roster": "anthropic",
    },
}

CONFIG_FILENAME = "central.json"
SECRETS_FILENAME = "secrets.env"


def ensure_global_config_home() -> tuple[Path, Path, Path]:
    root = config_home()
    root.mkdir(parents=True, exist_ok=True)
    config_path = root / CONFIG_FILENAME
    secrets_path = root / SECRETS_FILENAME
    os.environ.setdefault("NOCTICS_CONFIG_HOME", str(root))
    os.environ.setdefault("NOX_CONFIG", str(config_path))
    os.environ.setdefault("NOCTICS_SECRETS_FILE", str(secrets_path))
    return root, config_path, secrets_path


def _load_json(path: Path) -> Dict[str, object]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))  # type: ignore[return-value]
    except Exception:
        return {}


def _write_json(path: Path, payload: Dict[str, object]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _write_secrets(path: Path, env_key: str, value: str) -> None:
    entries: Dict[str, str] = {}
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#") or "=" not in stripped:
                continue
            key, current = stripped.split("=", 1)
            entries[key.strip()] = current.strip()
    entries[env_key] = value
    lines = [f"{key}={val}" for key, val in entries.items()]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    if os.name == "posix":
        try:
            os.chmod(path, 0o600)
        except Exception:
            pass


def _instrument_configured() -> bool:
    cfg = get_runtime_config()
    if cfg.instrument.roster:
        return True
    for env_name in ("OPENAI_API_KEY", "NOX_LLM_API_KEY", "ANTHROPIC_API_KEY"):
        if nox_env.get_env(env_name):
            return True
    return False


def _prompt_provider() -> Optional[str]:
    print(color("\nConfigure an external instrument to unlock delegated actions.", fg="yellow"))
    print("Choose a provider (or press Enter to skip):")
    keys = list(PROVIDERS.keys())
    for idx, key in enumerate(keys, start=1):
        meta = PROVIDERS[key]
        print(f"  {idx}) {meta['label']} — create an API key at {meta['url']}")
    print("  0) Skip for now")
    while True:
        try:
            choice = input(color("Selection [0]: ", fg="yellow")).strip()
        except EOFError:
            return None
        if not choice:
            return None
        if choice == "0":
            return None
        if choice.isdigit() and 1 <= int(choice) <= len(keys):
            return keys[int(choice) - 1]
        lowered = choice.lower()
        if lowered in PROVIDERS:
            return lowered
        print(color("Invalid choice. Try again.", fg="red"))


def _prompt_api_key(label: str) -> Optional[str]:
    try:
        key = getpass.getpass(color(f"Enter {label} API key: ", fg="yellow"))
    except EOFError:
        return None
    return key.strip() or None


def maybe_run_first_launch_setup(interactive: bool, *, force: bool = False) -> bool:
    _, config_path, secrets_path = ensure_global_config_home()
    if not force and _instrument_configured():
        return False
    if not interactive:
        return False
    provider_key = _prompt_provider()
    if not provider_key:
        print(color("Skipping instrument setup. You can rerun via `noctics --setup` later.", fg="yellow"))
        return False
    provider = PROVIDERS[provider_key]
    api_key = _prompt_api_key(provider["label"])
    if not api_key:
        print(color("No API key provided; instrument setup skipped.", fg="red"))
        return False
    _write_secrets(secrets_path, provider["env"], api_key)
    os.environ[provider["env"]] = api_key
    try:
        nox_env._SECRETS_CACHE = None  # type: ignore[attr-defined]
    except Exception:
        pass
    config_data = _load_json(config_path)
    instrument_section = config_data.get("instrument")
    if not isinstance(instrument_section, dict):
        instrument_section = {}
    roster = instrument_section.get("roster")
    if not isinstance(roster, list):
        roster = []
    roster = [str(item).strip() for item in roster if str(item).strip()]
    if provider["roster"] not in roster:
        roster.append(provider["roster"])
    instrument_section.update(
        {
            "automation": True,
            "roster": roster,
            "default_provider": provider["roster"],
        }
    )
    config_data["instrument"] = instrument_section
    _write_json(config_path, config_data)
    reload_config(config_path)
    print(color(f"Configured instrument provider '{provider['label']}'.", fg="green"))
    print(color("You can update credentials by editing the secrets file or rerunning the setup command.", fg="yellow"))
    return True

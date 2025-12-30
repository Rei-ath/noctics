"""Persona metadata, overrides, and prompt rendering for Nox."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, replace
from functools import lru_cache
from pathlib import Path
from typing import Dict, Iterable, Optional

from nox_env import get_env

__all__ = ["NoxPersona", "resolve_persona", "render_system_prompt", "reload_persona_overrides"]

_PERSONA_FILE_ENV = "NOX_PERSONA_FILE"
_PERSONA_DEFAULT_LOCATIONS: tuple[Path, ...] = (
    Path("config/persona.overrides.json"),
    Path("persona.override.json"),
    Path("persona.overrides.json"),
)

_OVERRIDE_FIELD_ALIASES: Dict[str, tuple[str, ...]] = {
    "central_name": ("central_name", "name"),
    "variant_name": ("variant_name", "variant"),
    "model_target": ("model_target", "model"),
    "parameter_label": ("parameter_label", "parameters", "parameter"),
    "tagline": ("tagline", "motto", "summary"),
    "strengths": ("strengths", "strength"),
    "limits": ("limits", "limitations", "weaknesses"),
}


@dataclass(frozen=True)
class NoxPersona:
    """Scale-aware identity for Nox."""

    scale: str
    central_name: str
    variant_name: str
    model_target: str
    parameter_label: str
    tagline: str
    strengths: tuple[str, ...]
    limits: tuple[str, ...]

    @property
    def scale_label(self) -> str:
        return f"{self.scale}-tier · {self.parameter_label}"

    @property
    def variant_display(self) -> str:
        return self.variant_name.replace("-", " ").title()

    @property
    def summary_line(self) -> str:
        return (
            f"{self.central_name} is the {self.scale_label} profile that powers {self.variant_name}. "
            f"{self.tagline}"
        )

    def _format_lines(self, lines: Iterable[str]) -> str:
        cleaned = [line.strip() for line in lines if line.strip()]
        if not cleaned:
            return "- (details pending)"
        return "\n".join(f"- {line}" for line in cleaned)

    @property
    def strengths_block(self) -> str:
        return self._format_lines(self.strengths)

    @property
    def limits_block(self) -> str:
        return self._format_lines(self.limits)


PERSONA_CATALOG: Dict[str, NoxPersona] = {
    "nox": NoxPersona(
        scale="nox",
        central_name="nox",
        variant_name="nox",
        model_target="qwen2.5:0.5b",
        parameter_label="0.5B parameters",
        tagline="Smallest local profile tuned for fast answers and low memory use.",
        strengths=(
            "Responds quickly and keeps outputs focused.",
            "Great for terminal workflows, short code edits, and brief summaries.",
            "Optimized for low-resource local inference.",
        ),
        limits=(
            "Keep prompts concise; long context and deep reasoning can degrade quickly.",
            "For heavy research or long-form synthesis, use a remote model/instrument instead.",
        ),
    ),
}

DEFAULT_PERSONA = PERSONA_CATALOG["nox"]

PERSONA_ALIASES: Dict[str, str] = {}
for key, persona in PERSONA_CATALOG.items():
    PERSONA_ALIASES[key] = key
    PERSONA_ALIASES[persona.central_name] = key
    PERSONA_ALIASES[persona.variant_name] = key
    PERSONA_ALIASES[f"{persona.variant_name}:latest"] = key
    PERSONA_ALIASES[persona.model_target] = key
    PERSONA_ALIASES[persona.model_target.replace(":", "-")] = key

PERSONA_SUBSTRINGS = [
    ("0.5b", "nox"),
    ("qwen2.5", "nox"),
    ("nox", "nox"),
]


def _lookup_scale(token: str) -> Optional[str]:
    token = token.strip().lower()
    if not token:
        return None
    if token in PERSONA_ALIASES:
        return PERSONA_ALIASES[token]
    for pattern, scale in PERSONA_SUBSTRINGS:
        if pattern in token:
            return scale
    return None


def _candidate_persona_paths() -> Iterable[Path]:
    env_path = get_env(_PERSONA_FILE_ENV)
    if env_path:
        yield Path(env_path).expanduser()
    for path in _PERSONA_DEFAULT_LOCATIONS:
        yield path


def _load_override_file() -> Dict[str, object]:
    for path in _candidate_persona_paths():
        try:
            if path.exists():
                return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
    return {}


def _normalize_string(value: object) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, str):
        text = value.strip()
        return text or None
    return str(value).strip() or None


def _normalize_sequence(value: object) -> Optional[tuple[str, ...]]:
    if value is None:
        return None
    if isinstance(value, (list, tuple)):
        cleaned = tuple(str(item).strip() for item in value if str(item).strip())
        return cleaned or None
    text = _normalize_string(value)
    if not text:
        return None
    parts = [part.strip(" -\t") for part in re.split(r"[|,\n]", text) if part.strip(" -\t")]
    return tuple(parts) or None


def _normalize_override(raw: object) -> Dict[str, object]:
    if not isinstance(raw, dict):
        return {}
    normalized: Dict[str, object] = {}
    for attr, aliases in _OVERRIDE_FIELD_ALIASES.items():
        for alias in aliases:
            if alias in raw:
                if attr in {"strengths", "limits"}:
                    seq = _normalize_sequence(raw[alias])
                    if seq:
                        normalized[attr] = seq
                else:
                    text = _normalize_string(raw[alias])
                    if text is not None:
                        normalized[attr] = text
                break
    return normalized


@lru_cache(maxsize=1)
def _persona_override_cache() -> tuple[Dict[str, object], Dict[str, Dict[str, object]]]:
    data = _load_override_file()
    if "scales" in data and isinstance(data["scales"], dict):
        global_raw = data.get("global", {})
        scale_raw = data.get("scales", {})
    else:
        global_raw = {}
        scale_raw = data
    global_norm = _normalize_override(global_raw)
    scales_norm: Dict[str, Dict[str, object]] = {}
    if isinstance(scale_raw, dict):
        for key, value in scale_raw.items():
            scales_norm[key.lower()] = _normalize_override(value)
    return global_norm, scales_norm


def _env_override(scale: str) -> Dict[str, object]:
    result: Dict[str, object] = {}
    upper = scale.upper()
    env_map = {
        "central_name": ("NOX_PERSONA_NAME", f"NOX_PERSONA_NAME_{upper}"),
        "variant_name": ("NOX_PERSONA_VARIANT", f"NOX_PERSONA_VARIANT_{upper}"),
        "model_target": ("NOX_PERSONA_MODEL", f"NOX_PERSONA_MODEL_{upper}"),
        "parameter_label": ("NOX_PERSONA_PARAMETERS", f"NOX_PERSONA_PARAMETERS_{upper}"),
        "tagline": ("NOX_PERSONA_TAGLINE", f"NOX_PERSONA_TAGLINE_{upper}"),
        "strengths": ("NOX_PERSONA_STRENGTHS", f"NOX_PERSONA_STRENGTHS_{upper}"),
        "limits": ("NOX_PERSONA_LIMITS", f"NOX_PERSONA_LIMITS_{upper}"),
    }
    for attr, (base_key, scale_key) in env_map.items():
        raw = get_env(scale_key) or get_env(base_key)
        if raw is None:
            continue
        if attr in {"strengths", "limits"}:
            seq = _normalize_sequence(raw)
            if seq:
                result[attr] = seq
        else:
            text = _normalize_string(raw)
            if text is not None:
                result[attr] = text
    return result


def _apply_overrides(persona: NoxPersona, overrides: Dict[str, object]) -> NoxPersona:
    current = persona
    for attr, value in overrides.items():
        if not hasattr(current, attr):
            continue
        current = replace(current, **{attr: value})
    return current


def resolve_persona(model_name: Optional[str], *, scale_override: Optional[str] = None) -> NoxPersona:
    """Return the persona that best matches the configured model or override."""

    candidates = [
        scale_override or "",
        get_env("NOX_SCALE") or "",
        model_name or "",
    ]
    persona = None
    for token in candidates:
        scale = _lookup_scale(token)
        if scale and scale in PERSONA_CATALOG:
            persona = PERSONA_CATALOG[scale]
            break
    if persona is None:
        persona = DEFAULT_PERSONA
        scale = persona.scale
    else:
        scale = persona.scale

    global_override, scale_overrides = _persona_override_cache()
    if global_override:
        persona = _apply_overrides(persona, global_override)
    scale_override_dict = scale_overrides.get(scale, {})
    if scale_override_dict:
        persona = _apply_overrides(persona, scale_override_dict)
    env_overrides = _env_override(scale)
    if env_overrides:
        persona = _apply_overrides(persona, env_overrides)
    return persona


def render_system_prompt(template: Optional[str], persona: NoxPersona) -> Optional[str]:
    """Inject persona data into the system prompt template."""

    if not template or "{{" not in template:
        return template

    replacements = {
        "{{NOX_NAME}}": persona.central_name,
        "{{NOX_VARIANT}}": persona.variant_name,
        "{{NOX_VARIANT_DISPLAY}}": persona.variant_display,
        "{{NOX_SCALE}}": persona.scale,
        "{{NOX_SCALE_LABEL}}": persona.scale_label,
        "{{NOX_MODEL_TARGET}}": persona.model_target,
        "{{NOX_PERSONA_TAGLINE}}": persona.tagline,
        "{{NOX_PERSONA_SUMMARY}}": persona.summary_line,
        "{{NOX_PERSONA_STRENGTHS}}": persona.strengths_block,
        "{{NOX_PERSONA_LIMITS}}": persona.limits_block,
        "{{NOX_PERSONA_EMOJI}}": "",
    }
    rendered = template
    for key, value in replacements.items():
        rendered = rendered.replace(key, value)
    return rendered


def reload_persona_overrides() -> None:
    """Clear cached persona override data so subsequent lookups re-read the source."""

    _persona_override_cache.cache_clear()

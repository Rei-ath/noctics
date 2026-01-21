"""HUD helpers for the Noctics CLI with copy-paste friendly customization.

To tweak the splash screen, edit the constants below. Logos are stored as
multiline strings so you can paste ASCII art directly without worrying about
tuple formatting. The default layout controls the order of sections rendered in
the CLI status dashboard; override it with :func:`set_hud_layout` or by editing
``HUD_LAYOUT`` in-place.
"""

from __future__ import annotations

from pathlib import Path
from textwrap import dedent
from typing import Any, Dict, Iterable, List, Mapping, MutableMapping

from nox_env import get_env

__all__ = [
    "NOX_LOGO",
    "PLACEHOLDER_LOGO",
    "HUD_LAYOUT",
    "register_logo_preset",
    "set_default_logo",
    "set_hud_layout",
    "resolve_logo_lines",
    "resolve_hud_layout",
    "build_hud_content",
]


class _SafeDict(dict):
    """Format helper that returns an empty string for missing keys."""

    def __missing__(self, key: str) -> str:  # pragma: no cover - defensive
        return ""


def _normalize_string_art(art: str | Iterable[str]) -> List[str]:
    if isinstance(art, str):
        clean = dedent(art).strip("\n")
        lines = clean.splitlines()
    else:
        lines = [str(line) for line in art]
    normalized = [line.rstrip("\r") for line in lines]
    if not any(normalized):
        raise ValueError("Logo art must contain at least one visible line.")
    return normalized


# Default banner shipped with Nox. Paste your own art between the triple quotes.
NOX_LOGO: str = """\
╔╗╔┌─┐─┐┬
║║║││┌┴┬┘
╝╚╝└─┘┴└─"""

# Friendly placeholder that invites customization when no preset matches.
PLACEHOLDER_LOGO: str = """\
┌────────────────────────────┐
│        NOCTICS HUD        │
└────────────────────────────┘"""

# Core presets keyed by style name. Add your own variants here or via
# register_logo_preset("variant", YOUR_ASCII_ART).
_LOGO_PRESETS: MutableMapping[str, List[str]] = {}
_DEFAULT_STYLE = "default"


def register_logo_preset(
    name: str,
    art: str | Iterable[str],
    *,
    overwrite: bool = True,
) -> List[str]:
    """Register ``art`` under ``name`` so ``NOX_HUD_STYLE`` can select it."""

    key = name.strip().lower()
    if not key:
        raise ValueError("Logo preset name cannot be empty.")
    if key in _LOGO_PRESETS and not overwrite:
        raise ValueError(f"Logo preset '{key}' is already registered.")
    normalized = _normalize_string_art(art)
    _LOGO_PRESETS[key] = normalized
    return normalized


def set_default_logo(art: str | Iterable[str]) -> List[str]:
    """Replace the baseline logo used by the CLI."""

    return register_logo_preset(_DEFAULT_STYLE, art)


def _load_art_file(path: Path) -> List[str]:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return []
    try:
        return _normalize_string_art(text)
    except ValueError:
        return []


# Seed built-in presets. Edit here for repo-wide defaults.
set_default_logo(NOX_LOGO)
register_logo_preset("placeholder", PLACEHOLDER_LOGO)
register_logo_preset("nox", NOX_LOGO)


def resolve_logo_lines(*, style_hint: str | None = None) -> List[str]:
    """Return ASCII logo lines honoring env overrides and named presets."""

    inline_override = get_env("NOX_HUD_ASCII")
    if inline_override:
        try:
            return _normalize_string_art(inline_override.replace("\\r", ""))
        except ValueError:
            pass

    file_override = get_env("NOX_HUD_ASCII_FILE")
    if file_override:
        art = _load_art_file(Path(file_override).expanduser())
        if art:
            return art

    style = (get_env("NOX_HUD_STYLE") or style_hint or _DEFAULT_STYLE).strip().lower()
    preset = _LOGO_PRESETS.get(style)
    if not preset and style.endswith("-nox"):
        preset = _LOGO_PRESETS.get(style.split("-")[0])
    if not preset and ":" in style:
        preset = _LOGO_PRESETS.get(style.split(":", 1)[0])

    if preset:
        return list(preset)

    return _LOGO_PRESETS.get("placeholder", _normalize_string_art(PLACEHOLDER_LOGO))


# Default HUD layout. Edit this dict or call set_hud_layout(...) to customize
# ordering, text, and formatting. Placeholders follow str.format_map semantics.
HUD_LAYOUT: Dict[str, Any] = {
    "order": [
        "header",
        "developer",
        "separator",
        "logo",
        "separator",
        "sections",
        "separator",
        "tagline",
        "separator",
        "footer",
    ],
    "header": "{header}",
    "header_align": "center",
    "header_bold": True,
    "developer_line": "Developer      : {developer_display}",
    "developer_align": "left",
    "developer_bold": False,
    "logo_align": "center",
    "logo_bold": True,
    "logo_style": "{logo_style_hint}",
    "section_label_format": "{label:<16}: {value}",
    "section_align": "left",
    "section_bold": False,
    "sections": [
        {"label": "Version", "value": "{version}"},
        {"label": "Operator", "value": "{operator}"},
        {"label": "Hardware", "value": "{hardware}"},
        {"label": "Runtime", "value": "{runtime}"},
        {"label": "Runtime Source", "value": "{runtime_source}"},
        {"label": "Endpoint", "value": "{endpoint}"},
        {"label": "Model", "value": "{model}"},
        {"label": "Model Target", "value": "{model_target}"},
        {"label": "Persona", "value": "{persona_central_name}"},
        {"label": "Instrument Auto", "value": "{instrument_auto}"},
        {"label": "Instrument Roster", "value": "{instrument_roster}"},
        {"label": "Sessions Saved", "value": "{sessions_saved}"},
    ],
    "tagline": "{persona_tagline}",
    "tagline_align": "center",
    "tagline_bold": False,
    "footer": "{footer}",
    "footer_align": "center",
    "footer_bold": True,
}

_HUD_LAYOUT_OVERRIDE: Dict[str, Any] | None = None


def set_hud_layout(layout: Mapping[str, Any]) -> None:
    """Override the HUD layout at runtime."""

    global _HUD_LAYOUT_OVERRIDE
    _HUD_LAYOUT_OVERRIDE = dict(layout)


def resolve_hud_layout() -> Dict[str, Any]:
    """Return the effective HUD layout."""

    return dict(_HUD_LAYOUT_OVERRIDE or HUD_LAYOUT)


def build_hud_content(
    context: Mapping[str, Any],
    *,
    style_hint: str | None = None,
) -> List[Dict[str, Any]]:
    """Produce content specs consumed by the CLI renderer."""

    layout = resolve_hud_layout()
    safe_context = _SafeDict(context)
    order = layout.get("order") or []
    content_specs: List[Dict[str, Any]] = []

    def _add_text_block(
        template: Any,
        *,
        align_key: str,
        bold_key: str,
    ) -> None:
        if not template:
            return
        text = str(template).format_map(safe_context).strip()
        if not text:
            return
        align = layout.get(align_key, "left")
        bold = bool(layout.get(bold_key, False))
        content_specs.append({"text": text, "align": align, "bold": bold})

    logo_style_template = layout.get("logo_style")
    logo_style = (
        str(logo_style_template).format_map(safe_context).strip()
        if logo_style_template
        else None
    )
    logo_lines = resolve_logo_lines(style_hint=logo_style or style_hint)

    sections = layout.get("sections", [])
    section_template = layout.get("section_label_format", "{label}: {value}")
    default_section_align = layout.get("section_align", "left")
    default_section_bold = bool(layout.get("section_bold", False))

    for part in order:
        if part == "separator":
            content_specs.append({"separator": True})
            continue
        if part == "header":
            _add_text_block(layout.get("header"), align_key="header_align", bold_key="header_bold")
            continue
        if part == "developer":
            _add_text_block(
                layout.get("developer_line"),
                align_key="developer_align",
                bold_key="developer_bold",
            )
            continue
        if part == "logo":
            align = layout.get("logo_align", "center")
            bold = bool(layout.get("logo_bold", True))
            for line in logo_lines:
                text = line.format_map(safe_context) if "{" in line else line
                content_specs.append({"text": text, "align": align, "bold": bold})
            continue
        if part == "sections":
            for entry in sections:
                if isinstance(entry, Mapping):
                    label_template = entry.get("label", "")
                    value_template = entry.get("value", "")
                    align = entry.get("align", default_section_align)
                    bold = bool(entry.get("bold", default_section_bold))
                    fmt = entry.get("format", section_template)
                else:
                    label_template, value_template = entry
                    align = default_section_align
                    bold = default_section_bold
                    fmt = section_template
                label_text = str(label_template).format_map(safe_context).strip()
                value_text = str(value_template).format_map(safe_context).strip()
                if not value_text:
                    continue
                spec_context = _SafeDict(dict(context))
                spec_context.update({"label": label_text, "value": value_text})
                text = str(fmt).format_map(spec_context)
                content_specs.append({"text": text, "align": align, "bold": bold})
            continue
        if part == "tagline":
            _add_text_block(
                layout.get("tagline"),
                align_key="tagline_align",
                bold_key="tagline_bold",
            )
            continue
        if part == "footer":
            _add_text_block(
                layout.get("footer"),
                align_key="footer_align",
                bold_key="footer_bold",
            )
            continue

    return content_specs

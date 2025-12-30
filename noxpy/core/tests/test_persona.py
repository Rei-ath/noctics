import json
from pathlib import Path

from central.persona import reload_persona_overrides, render_system_prompt, resolve_persona


def test_resolve_persona_known_alias():
    persona = resolve_persona("qwen2.5:0.5b")
    assert persona.central_name == "nox"
    assert persona.scale == "nox"


def test_resolve_persona_env_override(monkeypatch):
    monkeypatch.setenv("NOX_SCALE", "nox")
    persona = resolve_persona("unknown-model")
    assert persona.central_name == "nox"
    assert persona.scale == "nox"


def test_render_system_prompt_is_idempotent():
    persona = resolve_persona("nox")
    template = "Name {{NOX_NAME}}\n{{NOX_PERSONA_STRENGTHS}}\n{{NOX_PERSONA_EMOJI}}"
    rendered = render_system_prompt(template, persona)
    assert "{{" not in rendered
    assert persona.central_name in rendered
    assert "- " in rendered
    assert "{{NOX_PERSONA_EMOJI}}" not in rendered
    assert "  " not in rendered  # no double spaces left behind
    assert render_system_prompt(rendered, persona) == rendered


def test_persona_override_file(monkeypatch, tmp_path: Path):
    override_path = tmp_path / "persona.override.json"
    override_path.write_text(
        json.dumps(
            {
                "global": {"tagline": "Custom signal"},
                "scales": {
                    "nox": {
                        "central_name": "spark-nox",
                        "strengths": ["Knows Rei's shortcuts"],
                        "limits": "Prefers tiny prompts",
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("NOX_PERSONA_FILE", str(override_path))
    reload_persona_overrides()
    persona = resolve_persona("qwen2.5:0.5b")
    assert persona.central_name == "spark-nox"
    assert persona.tagline == "Custom signal"
    assert persona.strengths == ("Knows Rei's shortcuts",)
    assert persona.limits == ("Prefers tiny prompts",)
    reload_persona_overrides()


def test_persona_environment_overrides(monkeypatch):
    monkeypatch.delenv("NOX_PERSONA_FILE", raising=False)
    monkeypatch.setenv("NOX_SCALE", "nox")
    monkeypatch.setenv("NOX_PERSONA_TAGLINE_NOX", "Hand-crafted by Rei")
    monkeypatch.setenv("NOX_PERSONA_STRENGTHS", "Dev-mode wizardry|Design feedback")
    reload_persona_overrides()
    persona = resolve_persona("ignored")
    assert persona.central_name == "nox"
    assert persona.scale == "nox"
    assert persona.tagline == "Hand-crafted by Rei"
    assert persona.strengths == ("Dev-mode wizardry", "Design feedback")
    reload_persona_overrides()

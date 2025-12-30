# Persona Remix Manual (Nox whispering in your ear)

Nox ships with a single built-in persona: `nox`. You can remix the name/tagline/strengths/limits without touching source.

## Default persona
| Key | Default name | Model target |
|-----|--------------|--------------|
| nox | nox          | qwen2.5:0.5b |

## Override hierarchy
1. JSON file (`config/persona.overrides.json` or path in `NOX_PERSONA_FILE`)
2. Environment variables (`NOX_PERSONA_*`)
3. Built-in catalog

`NOX_SCALE` can be set to `nox`, but everything maps to `nox` by default.

### Fields you can flip
- `central_name`
- `variant_name`
- `model_target`
- `parameter_label`
- `tagline`
- `strengths` (string or list; comma/pipe/newline split)
- `limits` (same deal)

### JSON template
```json
{
  "global": {
    "tagline": "Always-on studio co-pilot",
    "strengths": "Keeps private briefs tight|Checks every command twice"
  },
  "scales": {
    "nox": {
      "central_name": "spark-nox",
      "parameter_label": "0.5B tuned for dev loops",
      "limits": [
        "Prefers focused prompts",
        "Use a bigger/remote model for heavy research"
      ],
      "tagline": "Chief of staff for long-haul strategy"
    }
  }
}
```
Call:
```python
from central.persona import reload_persona_overrides
reload_persona_overrides()
```
to apply without restarting Python.

### Env quick tweaks
```bash
export NOX_SCALE=nox
export NOX_PERSONA_TAGLINE="Studio co-pilot"
export NOX_PERSONA_STRENGTHS="Knows Rei's dotfiles|Keeps dev shells tidy"
export NOX_PERSONA_LIMITS="Needs extra GPU juice"
```
Scale-specific env vars append `_NOX` (case-insensitive).

## Verify your remix
1. Reload overrides or restart the CLI.
2. Run `python main.py`.
3. Startup HUD should show the new name/tagline; system prompt will echo the change.
4. If defaults still show, check your JSON path, field names, or env overrides.

## Troubleshooting
- Lists collapsing to one bullet? Separate with commas, pipes, or provide a JSON array.
- Want defaults back? Delete the override file/env vars and call `reload_persona_overrides()`.
- Need deeper hooks (custom onboarding, scriptable quirks)? File an issue or extend the schema.

Go ahead—put your own swagger on the persona. I’ll still roast you if the typography is sloppy.

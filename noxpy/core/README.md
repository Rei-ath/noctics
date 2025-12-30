# Nox Core (the public brain)

Nox again. This folder is the upstream `noctics-core` project—the part you let
the world see. Everything here should be clean, tested, and mergeable. All the
private wizardry happens outside this directory.

## TL;DR boot
- `python -m venv jenv && source jenv/bin/activate`
- `python -m pip install -U pip`
- `python scripts/bootstrap.py` *or* install manually:
  - `python -m pip install -e .`
  - `python -m pip install -e ../` if you need the wrapper for local dev
- Launch: `python main.py --stream`

## Config cheat sheet
A `.env` next to the package or in CWD always auto-loads. Favorite variables:
- `NOX_LLM_URL` – default `http://127.0.0.1:11434/api/generate`
- `NOX_LLM_MODEL` – aim at `nox`
- `NOX_LLM_API_KEY` / `OPENAI_API_KEY` – when you’re hitting remote clouds
- `NOX_SCALE` – optional persona selector (defaults to `nox`)
- `NOX_PERSONA_*` – override name, tagline, strengths, limits
- `NOX_INSTRUMENTS` – comma-separated instrument roster for interactive selection
- `NOX_HELPER_AUTOMATION` – set `1` when a router is ready to auto-dispatch

Drop a JSON override at `config/persona.overrides.json` if you need a full persona rewrite.

## Runtime shim (`/api/chat`)
- `python -m central.runtime --host 127.0.0.1 --port 11437`
- Reuses `NOX_LLM_URL`, `NOX_LLM_MODEL`, and API keys so replies go through the exact ChatClient stack.
- Responds to `POST /api/chat` with `{message, meta}` so mobile shells can stay dumb while the core handles scoring/instruments.
- Pass `--no-strip-reasoning` for raw output or `--log-sessions` to persist chats from HTTP callers.

## What ships here
- `central/core/` – `ChatClient`, payload builders, reasoning cleanup
- `central/commands/` – sessions, instruments, completions, help text
- `central/cli/` – argument parsing + interactive shell
- `interfaces/` – session logging, PII sanitizer, dotenv loader
- `noxl/` – memory explorer CLI and utilities
- `tests/` – pytest suite; keep it green

## Developer loop
```bash
pytest -q
ruff check .
python main.py --stream
```
Need coverage for a new instrument or transport? Drop a test in `tests/`.

## Persona remix
```bash
export NOX_SCALE=nox
cat > config/persona.overrides.json <<'JSON'
{
  "global": {"tagline": "Always-on studio co-pilot"},
  "scales": {
    "nox": {
      "central_name": "spark-nox",
      "strengths": "Keeps private briefs in sync|Checks every command twice"
    }
  }
}
JSON
python -c "from central.persona import reload_persona_overrides; reload_persona_overrides()"
```

## Sessions + memory
- Logs land in `~/.local/share/noctics/memory/sessions/YYYY-MM-DD/`.
- `python -m noxl --limit 10` to peek at recent chats.
- `/title`, `/rename`, `/archive` work in the CLI.
- `NOX_INSTRUMENT_ANON=0` if you want raw instrument prompts stored (be careful).

## Instrument reality check
Nox tries local inference first. When it requests an external instrument:
1. It asks you which instrument to use (unless you passed `--instrument`).
2. Emits a sanitized `[INSTRUMENT QUERY]`.
3. Waits for the router/automation. No router? You’ll get a reminder to paste results.

## Dev mode
Gate it with a passphrase (`NOX_DEV_PASSPHRASE`). When unlocked:
- Skips onboarding, labels you as the developer.
- Enables `/shell` bridging and richer status HUD.
- Logs carry the developer identity flag.

## Release sync (for the private repo)
When you cut a release, the parent repo bumps the submodule pointer to a tagged
commit here. Keep history squeaky clean—no vendored binaries, no secrets. If you
need obfuscation, run `scripts/push_core_pinaries.sh` from the parent repo; that’s
where the compiled extensions live.

Keep it sharp, keep it tested, and don’t make me revert anything.

# Nox’s Handler Field Guide

If you found your way here, you’re on duty to wrangle the Nox core and the
private wrapper without face-planting. Read this, live it, and keep the roadmap
fresh.

## Spin-up checklist
- `python -m venv jenv && source jenv/bin/activate`
- `pip install -r requirements.txt` for the public repo; the private wrapper
  stays stdlib-only.
- `scripts/nox.run` will grab the Ollama runtime, hydrate the models, and launch
  Nox pointed at the right endpoint.
- Need overrides? Export `NOX_MODEL`, `NOX_LLM_URL_OVERRIDE`,
  `NOX_LLM_MODEL_OVERRIDE`, `OLLAMA_HOST`, `OLLAMA_REPO_URL` as needed.

## Roadmap protocol
- The living roadmap sits at `../agents.plan`. If you land a feature, shift a
  milestone, or promise anything to stakeholders, update it immediately. No ghost plans.

## Submodule etiquette
1. Hack in `core/` as if this were a normal public repo.
2. Commit and push there (`git -C core status`, `git -C core commit`, `git -C core push`).
3. In the parent repo, run `./scripts/update_core.sh <branch>` to bump the pointer.
4. Commit the pointer and any wrapper changes together.
5. `git config push.recurseSubmodules on-demand` so your push handles everything.
6. Never stage individual files under `core/` from the parent—only the submodule pointer.

## Repo layout, trash talk edition
- `core/` – public source of truth. Keep it spotless.
- `core_pinaries/` – binary payload for the secret builds (`central`, `config`,
  `inference`, `interfaces`, `noxl`).
- `central/cli/` – argument parsing, interactive shell, onboarding flow.
- `central/core/` – `ChatClient`, payload mixers, reasoning filters.
- `central/commands/` – sessions, instruments, prompt orchestration.
- `interfaces/` – dotenv loader, PII scrubber, session logger.
- `noxl/` – memory spelunker CLI + APIs.
- `memory/` – prompt templates (`system_prompt.md`, `system_prompt.dev.md`).
- `scripts/` – everything from submodule sync to release rituals.
- `tests/` – pytest suite; if you touch behavior, add coverage.
- `instruments/` – SDK-backed instruments. Start with OpenAI, add your own.

## Build rituals
| Script | Why you care |
|--------|--------------|
| `scripts/build_release.sh` | Full PyInstaller bundle with Ollama runtime + models. |
| `scripts/push_core_pinaries.sh` | Recompiles all Nuitka extensions and refreshes `core_pinaries/`. |

Every bundle packages `memory/system_prompt.md` + `memory/system_prompt.dev.md` so
the persona identifies itself correctly.

## Persona remix
```bash
cat > config/persona.overrides.json <<'JSON'
{
  "global": {"tagline": "Studio co-pilot for Rei"},
  "scales": {
    "nox": {"central_name": "spark-nox"}
  }
}
JSON
python -c "from central.persona import reload_persona_overrides; reload_persona_overrides()"
```

Env overrides beat JSON, and `NOX_SCALE` decides which persona wins when the
model alias is ambiguous.

## Dev workflow
- Activate env: `source jenv/bin/activate`
- Tests: `pytest -q` or target with `-k`
- Lint: `ruff check .`, `black .`, `isort .` (match CI expectations)
- Manual run: `scripts/nox.run`
- Binary smoke test: hide `core/`, leave `core_pinaries/` on `PYTHONPATH`, and run
  `python -c "from central.core import ChatClient"`

## Runtime & instrument behavior
- Nox self-scores replies; score ≤ 5 triggers instrument requests.
- `[INSTRUMENT QUERY]` is sanitized; automation only activates when
  `NOX_INSTRUMENT_AUTOMATION` or config says so.
- Dev mode (passphrase-gated) unlocks `/shell`, detailed HUD, and developer identity tagging.
- `--show-think` exposes reasoning blocks; otherwise they’re stripped before logging.

## Sessions & memory
- Logs: `~/.local/share/noctics/memory/sessions/YYYY-MM-DD/`
- CLI quick hits: `/sessions`, `/archive`, `/title`, `/load`
- `noxl` CLI: `python -m noxl --limit 10`, `--search`, `--rename`
- Telemetry: on-disk metrics land in `memory/telemetry/metrics.json` (run counts, timestamps)

## Security ops
- No secrets in history—use `.env` files or runtime export.
- Refresh `inference/ollama` via `scripts/nox.run` when LayMA ships a new binary.
- Validate any external instrument response before storing or streaming it.
- Release builds bundle everything; keep `assets/models/nox.gguf` and the runtime
  ModelFile in sync with the shipped bundle.

Stay sharp. Update the roadmap, keep CI green, and remember: if you ship without
tests or documentation, I will drag your name through the system prompt.

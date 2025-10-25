# Noctics (private stash)

Yo, it’s Nox. If you’re in this repo, you’re here to wire the Central CLI brain
into something dangerous. I keep the open-source cortex mirrored under `./core/`,
then pile on private release magic, binary drops, and automation traps the public
never sees.

## Quick flex
- Clone the thing, then `python -m pip install -e core && python -m pip install -e .`
  unless you prefer the binary bundle (`pip install core_pinaries/`).
- Run `noctics --help` or `python main.py --stream` to confirm the multitool is awake.
- Launch the terminal dashboard with `noctics tui` to browse and inspect sessions.
- Need the closed-source drop? `./scripts/build_release.sh` pulls the LayMA Ollama
  runtime, aliases Qwen3 tiers, and stuffs everything in `dist/noctics-core/`.
- Binary-only deployment? The `core_pinaries` wheel loads the compiled `central`,
  `interfaces`, and `noxl` modules without exposing a single line of source.

## Map of the lair
- `core/` – upstream `noctics-core` submodule. Do the real work here, commit there,
  then bump the pointer.
- `core_pinaries/` – Nuitka-built extensions + `.pth` shim so `import central` works
  even when you hide the Python sources.
- `noctics_cli/` – multitool wrapper, argument parsing, runtime identity wizard,
  session router, and the new telemetry logger.
- `scripts/` – release rituals, submodule sync tooling, Ollama asset prep, and
  the `push_core_pinaries.sh` compiler.
- `assets/` – private models, Ollama runtime cache, signed binaries.
- `dist/` – where builds land when the rituals succeed.
- `agents.plan` – rolling roadmap. If you shift priorities, update it or I will
  haunt your commit history.

## Daily grind
1. Hack inside `core/`, run `pytest core/tests -q`, `ruff check core`.
2. Need CLI-only fixes? Drop them under `noctics_cli/` and keep the sass.
3. Update `agents.plan` when you land something roadmap-worthy.
4. When the submodule is ready, `./scripts/update_core.sh main`, commit the pointer,
   then run the release builders.

## Release seasoning
| Move | What happens |
|------|--------------|
| `./scripts/push_core_pinaries.sh` | Recompiles `central`, `config`, `inference`, `interfaces`, `noxl` via Nuitka and restages `core_pinaries/`. |
| `./scripts/build_release.sh` | Downloads LayMA’s Ollama, hydrates models, bakes PyInstaller bundle in `dist/noctics-core/`. |
| `./scripts/build_centi.sh` / `build_micro.sh` | Single-model bundles for the smaller squads. |
| GitHub action `CI` | Spins up Python 3.11, runs ruff critical checks and `pytest core/tests -q` on every push/PR. |
| *New* release workflow `release.yml` | Builds `noctics-core` sdist/wheel, compiles `core_pinaries` wheel, emits SHA256 sums, and drops everything as artifacts ready for signing. |

Sign the artifacts (GPG, minisign, whatever keeps Legal quiet), upload the wheels,
ship the PyInstaller tree, and tag the commit. No excuses.

## Trash talk aside…
This repo tries to be friendly to the next dev in the chair:
- Session logs auto-sync to `~/.local/share/noctics/memory`.
- Persona overrides live in `config/persona.overrides.json` or env vars.
- Instruments are pluggable and launch with sanitized payloads; OpenAI and
  Anthropic ship out of the box, and you can drop extra SDKs under
  `instruments/` or load plugins with `CENTRAL_INSTRUMENT_PLUGINS`.
- Local telemetry (turn counts, run timestamps) stays on disk under
  `memory/telemetry/metrics.json`. Share it if you want, ignore it if you’re paranoid.

## Need-to-know commands
```bash
# spin up a sandbox run
python main.py --stream

# browse sessions in the TUI dashboard
noctics tui

# bootstrap binary-only run (no source code visible)
pip install core_pinaries/
python -c "import central, noxl; print(central.__version__)"

# prep release with pre-staged models
NOCTICS_SKIP_ASSET_PREP=1 MODEL_SPECS='qwen3:8b=>centi-nox qwen3:1.7b=>micro-nox' \
  ./scripts/build_release.sh
```

## Lore
- Central persona defaults to Rei the overcaffeinated builder; override the vibe
  with `CENTRAL_NOX_SCALE`, `CENTRAL_PERSONA_*`, or drop a JSON file.
- Dev mode is passphrase-gated. If you see `/dev shell` prompts in user mode,
  you messed up.
- Anything under `experiments/` is volatile. Assume it breaks, or better yet,
  finish it and graduate it into `core/`.

That’s the lay of the land. Keep commits clean, keep secrets out of history,
and if you publish without running CI, expect me to roast you in the next release notes.

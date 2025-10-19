# Noctics (private)

Greetings, traveler. I am Nox, resident memelord of the Central CLI, and this repo is my secret playground. The public brain (a.k.a. `noctics-core`) lives as a submodule in `./core`; everything else in here is my stash of packaging tricks, shiny assets, and automation spells that the mortals are not ready for.

## Lore drop
- Core logic: grab it from https://github.com/Rei-ath/noctics-core (already vendored under `core/`).
- This repo: glue code, release tooling, and the last shred of mystery. Keep it sealed.

## TL;DR boot sequence
```bash
# Step 0: bring your own Python 3.11+ (Termux? sure. macOS? yup. Windows? obviously.)

# Step 1: install the public brain
python -m pip install ./core    # swap for `pip install noctics-core` once it is live

# Step 2: install my multitool wrapper
python -m pip install .

# Step 3: flex
noctics --help
noctics chat
```

## Wheel flex for the gadgeteers
```bash
python -m pip install --upgrade build pipx
python -m build                  # behold: dist/noctics-X.Y.Z-py3-none-any.whl
pipx install dist/noctics-*.whl  # or: uv tool install dist/noctics-*.whl
```

## Dev mode grind
```bash
python -m venv jenv && source jenv/bin/activate  # or use your own venv ritual
python -m pip install -e core
python -m pip install -e .
python main.py        # same vibe as `noctics chat`
```

## Persona hacks (because memes demand custom flair)
1. Drop overrides into `config/persona.overrides.json` or ship your own `CENTRAL_PERSONA_*` env vars (see `core/docs/PERSONA.md`).
2. Tell me to reload:
   ```bash
   python -c "from central.persona import reload_persona_overrides; reload_persona_overrides()"
   ```

## Runtime loot table
- Universal wheel: `python -m build` kicks out `dist/noctics-<version>-py3-none-any.whl`. Install it anywhere Python exists, Termux included.
- Zipapp bonus: `python -m zipapp noctics_cli -m noctics_cli.multitool:main` gives you `noctics.pyz`. Run it with `python noctics.pyz chat` when you feel fancy.
- Dependency reality check: I no longer poke `sys.path`. Install `noctics-core>=0.1.0` and the imports just vibe.

## Map of the lair
- `core/` : public source from the official repo (respect it).
- `assets/` : private binaries, models, and assorted loot.
- `scripts/` : helper incantations for syncing and building.
- `release/` : PyInstaller spec plus secret sauce docs.
- `dist/` : where artifacts spawn after release rituals.

## Daily grind instructions
1. Hack on `core/` like a responsible wizard and push upstream.
2. When ready, update the submodule pointer here:
   ```bash
   ./scripts/update_core.sh main
   ```

## Release ritual (closed-source bundle)
1. `./scripts/build_release.sh` pulls the LayMA Ollama runtime and stages Qwen3 models into `assets/ollama/models/`.
2. Want multiple scales? Summon them:
   ```bash
   MODEL_SPECS="qwen3:8b=>centi-nox qwen3:1.7b=>micro-nox qwen3:4b=>milli-nox qwen3:0.6b=>nano-nox" ./scripts/build_release.sh
   ```
   Already hoarded the assets? Set `NOCTICS_SKIP_ASSET_PREP=1`.
3. Bonus bundles:
   ```bash
   ./scripts/build_centi.sh   # dist/centi-noctics/  -> centi-nox (Qwen3 8B)
   ./scripts/build_micro.sh   # dist/micro-noctics/  -> micro-nox (Qwen3 1.7B)
   ```
4. Final loot lands in `dist/noctics-core/`. Zip it, sign it, ship it, meme it.

## Smoke test arena
```bash
export OLLAMA_HOME="$(mktemp -d)"
export OLLAMA_MODELS="$PWD/dist/noctics-core/_internal/resources/ollama/models"
./dist/noctics-core/_internal/resources/ollama/bin/ollama serve --host 127.0.0.1:12570 &
OLLAMA_PID=$!
curl -s http://127.0.0.1:12570/api/version
echo "Hello" | ./dist/noctics-core/_internal/resources/ollama/bin/ollama run centi-nox
kill $OLLAMA_PID
rm -rf "$OLLAMA_HOME"
```

## Benchmark flexes
- Orchestration run (with optional reviewer judge):
  - `python scripts/orchestrate_eval.py --out data/orch_eval.json`
  - No network? `NO_NETWORK=1 python scripts/orchestrate_eval.py --simulate --out data/orch_eval.json`
- Multi-target latency showdown:
  ```json
  [
    {"name": "local-centi", "url": "http://127.0.0.1:11434/api/generate", "model": "centi-nox"},
    {"name": "openai", "url": "https://api.openai.com/v1/chat/completions", "model": "gpt-4o", "api_key": "${OPENAI_API_KEY}"}
  ]
  ```
  Then: `python scripts/benchmark_targets.py --targets targets.json --stream --out data/bench_results.json`

## Lore addendum
- Central is provider-agnostic: point `CENTRAL_LLM_URL` and `CENTRAL_LLM_MODEL` at any OpenAI-ish endpoint or Ollama `/api/generate`.
- Dev mode leans on `memory/system_prompt.dev.txt`; normal mortals use `memory/system_prompt.txt`.
- Persona overrides chill in `config/persona.overrides.json` (or whatever `CENTRAL_PERSONA_FILE` points to). Share responsibly.

Carry on, keep the memes dank, and do not forget to install the core brain before summoning me. - Nox

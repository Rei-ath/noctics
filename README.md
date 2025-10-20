# Noctics (private)

Step aside, interloper. Nox here—the Central CLI's resident trash talker with a ledger full of receipts. This repo is my after-hours war room: the public cortex (`noctics-core`) anchors `./core/`, while the surrounding folders stockpile packaging payloads, hardened assets, and automation traps for anyone who thinks they're ready.

## Lore drop
- Pull https://github.com/Rei-ath/noctics-core. It's already mirrored into `core/` so you can work offline without excuses.
- Everything else here is glue code, release tooling, and the parts we do not hand to the public.

## Why Noctics?
- Noctics is a session vault, not a toy chat shell. Every exchange lands in JSONL, titled, mergeable, and ready for `noxl` so you stop pretending to manage logs manually.
- The CLI routes helpers and instruments with intent. When the assistant needs outside firepower, the pipeline captures it inline and folds it back into the memory for downstream analysis or fine-tuning.
- Local-first is the rule. Persona overrides, memory, configs—they live on disk so you can operate disconnected, on a lab machine, or in a bunker Raspberry Pi without phoning home.
- Packaging comes as a two-piece. `noctics-core` ships the lightweight memory toolkit; the wrapper delivers the full CLI when you want the orchestration UX.
- The interface targets developers under load: `/sessions`, `/archive`, `/show`, `/title`, plus runtime fallbacks when a model misbehaves. This is a lab bench, not a novelty chatbot.

## TL;DR boot sequence
```bash
# Step 0: bring Python 3.11+ or stay out of the way.

# Step 1: install the public brain
python -m pip install ./core    # swap for `pip install noctics-core` once the public release happens

# Step 2: install the wrapper so the CLI lands on PATH
python -m pip install .

# Step 3: verify the tooling
noctics --help
noctics chat
```

## Wheel flex for the gadgeteers
```bash
python -m pip install --upgrade build pipx
python -m build                  # emits dist/noctics-X.Y.Z-py3-none-any.whl
pipx install dist/noctics-*.whl  # or use `uv tool install dist/noctics-*.whl`
```

## Dev mode grind
```bash
python -m venv jenv && source jenv/bin/activate  # pick your poison if you prefer another venv ritual
python -m pip install -e core
python -m pip install -e .
python main.py        # same execution path as `noctics chat`
```

## Persona overrides
1. Place overrides in `config/persona.overrides.json` or drive them through `CENTRAL_PERSONA_*` env vars (see `core/docs/PERSONA.md`).
2. Reload on command:
   ```bash
   python -c "from central.persona import reload_persona_overrides; reload_persona_overrides()"
   ```

## Runtime loot table
- Universal wheel: `python -m build` produces `dist/noctics-<version>-py3-none-any.whl`. If Python runs on the target, the tool installs.
- Zipapp: `python -m zipapp noctics_cli -m noctics_cli.multitool:main` builds `noctics.pyz`. Execute with `python noctics.pyz chat` when you need a single-file drop.
- Dependency reality: the wrapper no longer bends `sys.path`. Install `noctics-core>=0.1.0` and everything resolves cleanly.

## Map of the lair
- `core/` : upstream source of truth.
- `assets/` : private models, binaries, and supporting payloads.
- `scripts/` : automation for syncing, building, and packaging.
- `release/` : PyInstaller specs and internal release notes.
- `dist/` : generated artifacts once the rituals finish.

## Multitool guts
- `noctics_cli/multitool.py` injects `core/` (and `core_pyd/` if available) onto `sys.path` before importing Central so the repo runs even if you haven’t pip-installed `noctics-core`.
- It mirrors the Codex multitool UX: parses subcommands, prints helper/instrument status, and routes `noctics chat` into the chat app while keeping session tooling handy.
- Helper/instrument automation status plus any configured roster lines get stapled onto the system prompt at startup so the persona knows what external firepower is on tap.

## Daily grind instructions
1. Do the work in `core/` and upstream the changes properly.
2. Bump the submodule pointer here when it's time to sync:
   ```bash
   ./scripts/update_core.sh main
   ```

## Release ritual (closed-source bundle)
1. `./scripts/build_release.sh` pulls the LayMA Ollama runtime and refreshes Qwen3 models into `assets/ollama/models/`.
2. Need multiple variants? Specify the roster:
   ```bash
   MODEL_SPECS="qwen3:8b=>centi-nox qwen3:1.7b=>micro-nox qwen3:4b=>milli-nox qwen3:0.6b=>nano-nox" ./scripts/build_release.sh
   ```
   Already staged assets? Set `NOCTICS_SKIP_ASSET_PREP=1`.
3. Optional single-model bundles:
   ```bash
   ./scripts/build_centi.sh   # dist/centi-noctics/  -> centi-nox (Qwen3 8B)
   ./scripts/build_micro.sh   # dist/micro-noctics/  -> micro-nox (Qwen3 1.7B)
   ```
4. Final artifacts land in `dist/noctics-core/`. Zip, sign, and ship.

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
- Orchestration run (optionally with the Reviewer AI turned on):
  - `python scripts/orchestrate_eval.py --out data/orch_eval.json`
  - No network? `NO_NETWORK=1 python scripts/orchestrate_eval.py --simulate --out data/orch_eval.json`
- Multi-target latency sweep:
  ```json
  [
    {"name": "local-centi", "url": "http://127.0.0.1:11434/api/generate", "model": "centi-nox"},
    {"name": "openai", "url": "https://api.openai.com/v1/chat/completions", "model": "gpt-4o", "api_key": "${OPENAI_API_KEY}"}
  ]
  ```
  Then run: `python scripts/benchmark_targets.py --targets targets.json --stream --out data/bench_results.json`

## Lore addendum
- Central stays provider-agnostic; just aim `CENTRAL_LLM_URL` + `CENTRAL_LLM_MODEL` at anything OpenAI-adjacent or an Ollama `/api/generate` endpoint and we're vibing.
- System prompts now live in Markdown: dev mode slurps `memory/system_prompt.dev.md`, normal runs default to `memory/system_prompt.md`. When instruments/helpers are configured, the CLI appends the roster to the prompt so Nox knows who to call.
- Persona overrides chill in `config/persona.overrides.json` (or whatever `CENTRAL_PERSONA_FILE` points at). Share the sauce responsibly; no leakers.
- `noctics_cli/multitool.py` is the wrapper that injects the vendored `core/` packages ahead of imports, prints status banners, and routes into the chat client so you can hack locally without installing `noctics-core`.

Report back when you land something worth reading. #U2620#U2694

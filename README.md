# Noctics (private)

This repository contains the private release tooling for Noctics. The public
`noctics-core` codebase lives as a Git submodule under `./core`, while this
repo adds packaging, assets, and automation that should stay closed-source.

## Quick Start

```bash
# Activate your existing venv or the bundled jenv
source jenv/bin/activate  # or python -m venv jenv && source jenv/bin/activate

# Run the multitool (chat is the default command)
python main.py              # or ./noctics chat

# Need help?
./noctics --help            # overview of subcommands
./noctics sessions list     # inspect saved conversations
```

To customise the assistant’s voice, create `config/persona.overrides.json` or set `CENTRAL_PERSONA_*` environment variables (see `core/docs/PERSONA.md` for examples) and then run:

```bash
python -c "from central.persona import reload_persona_overrides; reload_persona_overrides()"
```

## Layout

- `core/` &mdash; public source code tracked at https://github.com/Rei-ath/noctics-core
- `assets/` &mdash; private binaries and models that must be included in the release
- `scripts/` &mdash; helper scripts for keeping the submodule in sync and building
- `release/` &mdash; PyInstaller spec and documentation for the private build
- `dist/` (generated) &mdash; build artifacts produced by the release script

## Daily development

Work on features inside the public repository (`core/`). Push changes upstream
there and cut tags as usual. When a release is needed, update the submodule to
the desired commit:

```bash
./scripts/update_core.sh main
```

## Building the closed-source package

1. Run `./scripts/build_release.sh`. By default it downloads the LayMA Ollama
   runtime and stages the Qwen3 cache under
   `assets/ollama/models/`, exposing it inside the bundle as
   `centi-nox`.
2. To stage additional aliases (for example the nano/micro/milli tiers), set the
   `MODEL_SPECS` environment variable before running the script, e.g.
  `MODEL_SPECS="qwen3:8b=>centi-nox qwen3:1.7b=>micro-nox qwen3:4b=>milli-nox qwen3:0.6b=>nano-nox"`.
   Re-run the build once the models are pulled. You can skip automatic
   downloads by setting `NOCTICS_SKIP_ASSET_PREP=1` if the assets are already in
   place.

Optional scale-specific bundles:

```bash
./scripts/build_centi.sh   # dist/centi-noctics/  (bundles Qwen3 8B)
./scripts/build_micro.sh   # dist/micro-noctics/  (bundles Qwen3 1.7B)
```

| Scale  | Bundle Directory    | Packaged Alias   | Upstream Model |
|--------|---------------------|------------------|----------------|
| micro  | `dist/micro-noctics/`   | `micro-nox`      | `qwen3:1.7b`   |
| centi  | `dist/centi-noctics/`   | `centi-nox`      | `qwen3:8b`     |

The PyInstaller bundle is emitted to `dist/noctics-core/`. Package or sign that
folder according to the distribution channel (zip, installer, private PyPI
wheel, etc.). Commit the updated submodule pointer and any packaging metadata
changes in this repo when you cut a release.


To smoke-test the packaged bits locally:

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

## Benchmarking

- Orchestration eval (end-to-end with optional reviewer):
  - `python scripts/orchestrate_eval.py --out data/orch_eval.json`
  - Simulated (no network): `NO_NETWORK=1 python scripts/orchestrate_eval.py --simulate --out data/orch_eval.json`

- Multi-target benchmark (latency, TTFT, instrument usage):
  - Prepare targets JSON (example):
    ```json
    [
      {"name": "local-centi", "url": "http://127.0.0.1:11434/api/generate", "model": "centi-nox"},
      {"name": "openai", "url": "https://api.openai.com/v1/chat/completions", "model": "gpt-4o", "api_key": "${OPENAI_API_KEY}"}
    ]
    ```
  - Run: `python scripts/benchmark_targets.py --targets targets.json --stream --out data/bench_results.json`

Notes:
- Central remains provider-agnostic: set `CENTRAL_LLM_URL` and `CENTRAL_LLM_MODEL` to point at any OpenAI-like endpoint or Ollama `/api/generate`.
- Dev mode uses `memory/system_prompt.dev.txt`; normal runs use `memory/system_prompt.txt`.
- Persona overrides live in `config/persona.overrides.json` (or any path referenced by `CENTRAL_PERSONA_FILE`). Track reusable tweaks in version control if they are safe to publish.

# Noctics (private)

This repository contains the private release tooling for Noctics. The public
`noctics-core` codebase lives as a Git submodule under `./core`, while this
repo adds packaging, assets, and automation that should stay closed-source.

## Layout

- `core/` &mdash; public source code tracked at https://github.com/Rei-ath/noctics-core
- `assets/` &mdash; private binaries and models that must be included in the release
- `scripts/` &mdash; helper scripts for keeping the submodule in sync and building
- `release/` &mdash; PyInstaller spec and documentation for the private build
- `dist/` (generated) &mdash; build artifacts produced by the release script

## Daily development46540

Work on features inside the public repository (`core/`). Push changes upstream
there and cut tags as usual. When a release is needed, update the submodule to
the desired commit:

```bash
./scripts/update_core.sh main
```

## Building the closed-source package

1. Run `./scripts/build_release.sh`. By default it downloads the LayMA Ollama
   runtime and stages the Gemma 3 cache under
   `assets/ollama/models/`, exposing it inside the bundle as
   `noctics-edge:latest`.
2. To stage additional aliases (for example `gemma3:1b=>edge-lite`), set the
   `MODEL_SPECS` environment variable before running the script, e.g.
   `MODEL_SPECS="gemma3:latest=>noctics-edge gemma3:1b=>edge-lite"`.
   Re-run the build once the models are pulled. You can skip automatic
   downloads by setting `NOCTICS_SKIP_ASSET_PREP=1` if the assets are already in
   place.

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
echo "Hello" | ./dist/noctics-core/_internal/resources/ollama/bin/ollama run noctics-edge:latest
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
      {"name": "local-edge", "url": "http://127.0.0.1:11434/api/generate", "model": "noctics-edge:latest"},
      {"name": "openai", "url": "https://api.openai.com/v1/chat/completions", "model": "gpt-4o", "api_key": "${OPENAI_API_KEY}"}
    ]
    ```
  - Run: `python scripts/benchmark_targets.py --targets targets.json --stream --out data/bench_results.json`

Notes:
- Central remains provider-agnostic: set `CENTRAL_LLM_URL` and `CENTRAL_LLM_MODEL` to point at any OpenAI-like endpoint or Ollama `/api/generate`.
- Dev mode uses `memory/system_prompt.dev.txt`; normal runs use `memory/system_prompt.txt`.

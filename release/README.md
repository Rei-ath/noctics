# Release guide

This directory turns the public `noctics-core` source into the closed-weight
bundle we ship to partners. Follow the playbook; everything else is garnish.

## Step-by-step
1. **Freeze the code** – land changes in the `core/` submodule, push, then from
   the repo root run `./scripts/update_core.sh <branch>` to bump the pointer.
2. **Prep assets** – `./scripts/prepare_assets.sh` stages Ollama and the default
   GGUF model. Skip downloads with `NOCTICS_SKIP_ASSET_PREP=1` if you already
   have them cached.
3. **Build** – `./scripts/build_release.sh` now bundles all CLI modules, the
   runtime hook, and the selected model into `dist/noctics-core/`.
4. **Sign** – create checksums, sign them, zip the bundle, and stash everything
   under `release/` until security signs off.
5. **Tag & publish** – push the submodule bump + release notes, create the tag,
   then upload the artifacts.

## Customising models
Remap aliases before building:

```bash
MODEL_SPECS="qwen3:8b=>centi-nox qwen3:4b=>milli-nox qwen3:1.7b=>micro-nox qwen3:0.6b=>nano-nox" \
  ./scripts/build_release.sh
```

Reusing staged blobs?

```bash
NOCTICS_SKIP_ASSET_PREP=1 ./scripts/build_release.sh
```

## What you get
- `dist/noctics-core/noctics-core` – the PyInstaller launcher. When no
  `CENTRAL_LLM_URL` is supplied it starts the embedded Ollama binary,
  creates/loads the `centi-nox` alias (Qwen 0.5B), and targets the local
  endpoint. Provide an external URL (e.g. OpenAI) to skip the embedded runtime
  and honour your remote model.
- `dist/noctics-core/_internal/resources/models` – shipped GGUF weights.
- `dist/noctics-core/_internal/resources/runtime/centi-nox.modelfile` – the
  ModelFile used to hydrate the alias on first run.

## Housekeeping
- Intermediate build products live in `.pyi-build/`; delete when space is tight.
- Generate checksums:

  ```bash
  find dist/noctics-core -type f -print0 | sort -z | xargs -0 sha256sum > release/dist.sha256
  ```

- Sign `release/dist.sha256` with your weapon of choice (GPG, minisign, etc.).

## Quick presets
- `scripts/build_centi.sh`, `build_micro.sh`, `build_nano.sh` just wrap the main
  script with preset `MODEL_SPECS` values.
- For smoke tests, point `OLLAMA_MODELS` at the embedded folder:

  ```bash
  export OLLAMA_MODELS=dist/noctics-core/_internal/resources/ollama/models
  ./dist/noctics-core/_internal/resources/ollama/bin/ollama serve --host 127.0.0.1:12570
  ```

Happy shipping.

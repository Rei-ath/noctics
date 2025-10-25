# Release Rituals (private eyes only)

Nox here. This folder is how we turn the polite public `noctics-core` into a
sealed binary drop dripping with Qwen3 juice and Ollama runtime bits.

## High-level hustle
1. Ship-ready code lives in the `core/` submodule. Commit and push there first.
2. From the repo root run `./scripts/update_core.sh <branch>` to bump the pointer.
3. Prep assets: `./scripts/prepare_assets.sh` (or let `build_release.sh` call it).
4. Bake the bundle: `./scripts/build_release.sh`.
5. Sign the artifacts, zip them, tag the release, and stash the checksums.

## Model buffet
Set `MODEL_SPECS` before building to remap aliases:
```
MODEL_SPECS="qwen3:8b=>centi-nox qwen3:4b=>milli-nox qwen3:1.7b=>micro-nox qwen3:0.6b=>nano-nox" \
  ./scripts/build_release.sh
```
Already staged blobs? `NOCTICS_SKIP_ASSET_PREP=1` keeps the script from pulling again.

## Outputs
- PyInstaller drop: `dist/noctics-core/`
- Embedded runtime: `_internal/resources/ollama/bin/ollama`
- Embedded models: `_internal/resources/ollama/models/`
- Active model pointer: `assets/ollama/models/.active_model`

## Clean-up + signage
- `.pyi-build/` holds intermediate junk—nuke it if space gets tight.
- Generate checksums:
  ```bash
  find dist/noctics-core -type f -print0 | sort -z | xargs -0 sha256sum > release/dist.sha256
  ```
- Sign the checksum file (GPG, minisign, pick your poison) and stash both alongside the bundle.

## Pro tips
- `scripts/build_centi.sh` / `build_micro.sh` / `build_nano.sh` are just presets if
  you need single-model bundles fast.
- The bundled Ollama stays self-contained. Point `OLLAMA_MODELS` at the embedded
  path when running smoke tests:
  ```bash
  export OLLAMA_MODELS=dist/noctics-core/_internal/resources/ollama/models
  ./dist/noctics-core/_internal/resources/ollama/bin/ollama serve --host 127.0.0.1:12570
  ```
- Keep the submodule pointer commit with the release; auditors will thank you later.

Ship smart, sign everything, and don’t forget to trash talk the changelog.

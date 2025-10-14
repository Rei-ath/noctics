# Noctics Release Toolkit

This directory contains the private-only tooling that turns the public `noctics-core`
source tree into a closed-source binary distribution that embeds the production GGUF
model and any Ollama runtime bits.

## Workflow

1. Work as usual in the public `noctics-core` repository (the submodule under
   `./core`). Commit and push upstream there.
2. When you are ready to ship, run `./scripts/update_core.sh [branch]` to fast-forward
   the submodule to the commit that should be released.
3. Execute `./scripts/build_release.sh`. The helper script downloads the LayMA
   Ollama runtime and stages the requested models inside
   `assets/ollama/models/`, exposing them inside the bundle as
   aliases (default: `gemma3:latest` → `noctics-edge:latest`). Set
   `MODEL_SPECS` (e.g. `gemma3:latest=>noctics-edge gemma3:1b=>edge-lite`) to
   add or rename aliases. Pass `NOCTICS_SKIP_ASSET_PREP=1` to opt out if you
   have staged assets manually.
4. The PyInstaller build lands under `./dist/noctics-core/` and already contains
   the runtime, the primary alias (noctics-edge), and any optional extra models.
5. Package `dist/noctics-core` however you distribute binaries (zip, installer,
   private PyPI wheel, etc.) and tag the private repo for the release.

## Notes

- The build script keeps the PyInstaller work directory outside of the repo so the
  tree stays clean. Delete `.pyi-build/` if you want to reclaim space.
- The submodule pointer is part of the private repo history. Remember to commit it
  alongside the release artifacts and any packaging metadata changes.
- The bundled Ollama bits stay self-contained. When exporting the cache, set
  `OLLAMA_MODELS=dist/noctics-core/_internal/resources/ollama/models` so the
  runtime uses the embedded aliases.

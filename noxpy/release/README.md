# Release guide

This directory turns the public `noctics-core` source into the closed-weight
bundle we ship to partners. Follow the playbook; everything else is garnish.

## Step-by-step
1. **Freeze the code** – land changes in the `core/` submodule, push, then from
   the repo root run `./scripts/update_core.sh <branch>` to bump the pointer.
2. **Confirm the model** – ensure `assets/models/nox.gguf` is present.
3. **Build & package** – `./scripts/build_release.sh` bundles the CLI modules,
   runtime hook, and selected model into `dist/noctics-core/`, then packages the
   installer archive (`dist/noctics-core-<slug>.tar.gz|zip`) and refreshes
   `dist/installer_manifest.json`.
4. **Sign** – create checksums, sign the archive + manifest, and stash
   everything under `release/` until security signs off.
5. **Tag & publish** – push the submodule bump + release notes, create the tag,
   then upload the artifacts.

## Customising models
Point the build at a different GGUF if needed:

```bash
MODEL_PATH=/absolute/path/to/model.gguf ./scripts/build_release.sh
```

## What you get
- `dist/noctics-core/noctics-core` – the PyInstaller launcher. When no
  `NOX_LLM_URL` is supplied it starts the embedded Ollama binary,
  creates/loads the `nox` alias (Qwen 0.5B), and targets the local
  endpoint. Provide an external URL (e.g. OpenAI) to skip the embedded runtime
  and honour your remote model.
- Need a pre-wired remote endpoint for environments that block loopback (e.g. PropelY)?
  - Drop a `resources/runtime/fallback_remote_url.txt` file containing the URL
    before zipping the bundle, or
  - Export `NOCTICS_FALLBACK_REMOTE_URL` alongside the binary.
  The launcher will fall back to that URL when it cannot reserve a local port.
- Build scripts now generate `dist/<name>.SHA256SUMS` automatically using
  `scripts/post_build_checksums.sh` so checksum publication stays consistent.
- `dist/noctics-core-<slug>.tar.gz|zip` – platform-specific installer payload,
  produced automatically once the bundle exists.
- `dist/installer_manifest.json` – JSON manifest consumed by the bootstrapper
  with per-slug `url`, `size`, and `sha256` entries.
- Every bundle includes `licenses/THIRD_PARTY_LICENSES.md` to surface Apache-2.0
  notices for the packaged Qwen weights.
- `dist/noctics-core/_internal/resources/models` – shipped GGUF weights.
- `dist/noctics-core/_internal/resources/runtime/nox.modelfile` – the
  ModelFile used to hydrate the alias on first run.

## Housekeeping
- Intermediate build products live in `.pyi-build/`; delete when space is tight.
- Override packaging defaults with `NOCTICS_INSTALLER_*` environment variables
  (slug/arch overrides, CDN prefix, manifest path, README template, version,
  build id). See `docs/installer_design.md` for the full list.
- Generate checksums:

  ```bash
  find dist/noctics-core -type f -print0 | sort -z | xargs -0 sha256sum > release/dist.sha256
  ```

- Sign `release/dist.sha256` with your weapon of choice (GPG, minisign, etc.).

## Quick presets
- For smoke tests, point `OLLAMA_MODELS` at the embedded folder:

  ```bash
  export OLLAMA_MODELS=dist/noctics-core/_internal/resources/ollama/models
  ./dist/noctics-core/_internal/resources/ollama/bin/ollama serve --host 127.0.0.1:12570
  ```

Happy shipping.

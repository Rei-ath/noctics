# Noctics (private stack)

Noctics packages the Nox orchestration brain, a multitool CLI, and a
closed-weight runtime in one place. The public repo lives inside `./core/`; this
wrapper adds binary builds, release scripts, and a friendlier developer
experience.

**Current version:** `0.1.39` (derived from the commit count on `main`).

## What’s inside
- `core/` – the upstream `noctics-core` source (submodule). All production logic
  lives here.
- `core_pinaries/` – Nuitka extensions plus a `.pth` shim for binary-only
  installs.
- `noctics_cli/` – multitool entrypoint, session router, and TUI.
- `scripts/` – build automation (`build_release.sh`, `push_core_pinaries.sh`,
  model staging helpers, etc.).
- `assets/` – cached Ollama runtime and model blobs for release builds.
- `dist/` – output folder for wheels and PyInstaller bundles.

## Quick start
```bash
# 1. install dev dependencies
python -m pip install -e core
python -m pip install -e .

# 2. provide secrets (see docs/configuration.md for production setups)
# export NOCTICS_SECRETS_FILE=/path/to/secrets.env

# 3. run the chat client
noctics --help
python main.py --stream        # streamed chat session
noctics tui                    # curses dashboard for saved sessions
# optional: run once to configure instrument API keys globally
noctics --setup
```

Prefer binaries? Install the compiled payload:

```bash
python -m pip install core_pinaries/
python -c "import central; print(central.__version__)"
```

## Release checklist
1. **Sync the submodule** – finish work in `core/`, push, then
   `./scripts/update_core.sh main` from the repo root.
2. **Run tests** – `pytest core/tests -q` and `ruff check core` (see
   `core/requirements.txt`).
3. **Refresh binaries** – `./scripts/push_core_pinaries.sh` rebuilds the Nuitka
   extensions in `core_pinaries/`.
4. **Bake the bundle** – `./scripts/build_release.sh` creates
   `dist/noctics-core/` with the PyInstaller runtime, Ollama binary, and the
   selected GGUF model (set `MODEL_SPECS` if you need different aliases). The
   script now also packages the installer archive
   (`dist/noctics-core-<slug>.tar.gz|zip`) and refreshes
   `dist/installer_manifest.json`.
5. **Sign & tag** – generate SHA256 sums, sign artifacts, push the release tag.
   Override installer packaging defaults with `NOCTICS_INSTALLER_*` variables
   (see `docs/installer_design.md`) when building on CI or targeting a CDN.

### Example: single-model bundles
```bash
MODEL_SPECS='qwen3:4b=>milli-nox' ./scripts/build_centi.sh
MODEL_SPECS='qwen3:1.7b=>micro-nox' ./scripts/build_micro.sh
```

## Packaging notes
- The PyInstaller spec (`release/noctics_release.spec`) bundles the CLI modules
  plus a tiny Qwen 0.5B GGUF. The runtime hook
  (`release/runtime_env.py`) auto-starts the embedded Ollama binary only when no
  external runtime is configured. Export `NOX_LLM_URL` (e.g.
  `https://api.openai.com/v1/chat/completions`) to skip the embedded server; the
  CLI maps scale aliases to real OpenAI ids via `NOX_OPENAI_MODEL`
  (default: `gpt-4o-mini`).
- Binary-only installs rely on `core/__init__.py` to fall back to the compiled
  extensions when the source tree is missing.
- Wheels and bundles are versioned off the commit count; bumping the tree adds a
  new patch version automatically.
- Bundled Qwen model weights remain under Apache-2.0; see `THIRD_PARTY_LICENSES.md`
  for attribution and ensure the file ships with every release artifact.
- `scripts/package_installer_artifacts.py` wraps the archive/manifest step; use
  `NOCTICS_INSTALLER_URL_PREFIX` and related environment variables to bake CDN
  links during CI runs.

## Working on docs & telemetry
- Docs live under `core/docs/` and `release/README.md` for release rituals.
- Session history lands in `~/.local/share/noctics/memory`.
- Persona overrides live in `config/persona.overrides.json` (or environment).

## Troubleshooting
- “`noctics-core` binary prints nothing” – rebuild with
  `./scripts/build_release.sh` (PyInstaller now bundles CLI modules).
- “ImportError: central not found” – ensure `core` is on `PYTHONPATH` or install
  `core_pinaries`.
- “Unable to reach any configured runtime” when targeting OpenAI – set
  `NOX_LLM_URL=https://api.openai.com/v1/chat/completions` and either
  `NOX_LLM_MODEL` or `NOX_OPENAI_MODEL` to a supported id (default:
  `gpt-4o-mini`).
- “pytest missing” – install dev deps: `python -m pip install -r core/requirements.txt`.

Questions? Drop updates in `agents.plan`, keep commits tidy, and ship with tests.

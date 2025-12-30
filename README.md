# Noctics (process stack pivot)

We are freezing the Python implementation as a legacy artifact (`./noxpy/`) and
building a process-first stack: Rust for orchestration, Zig for inference, and
plain stdin/stdout streaming instead of HTTP. The smallest model (`assets/models/nox.gguf`)
is the only model kept in this tree.

**Current legacy version:** `0.1.39` (Python, now locked under `noxpy/`).

## Repo layout (human readable)
- `noxpy/` — legacy Python runtime + CLI; still runnable via `cd noxpy && python main.py`
- `experiments/noxrs/` — Rust stdin/stdout runner prototype (no HTTP)
- `experiments/engine/` — Rust orchestrator/FFI scaffold (process-based, no HTTP)
- `experiments/zig-infer/` — Zig runner scaffold for direct GGUF inference
- `bin/` — global binaries (e.g., `noxlocal` Go runner build target)
- `assets/models/` — only the `nox.gguf` weight plus manifests
- `noxpy/vendor/ollama/` — vendored Ollama source used by the transitional Go runner
- `docs/` — user/developer docs; add new Rust/Zig notes here as they harden
- `scripts/` — build/test helpers (Python legacy + new build shims)

## Legacy Python quick start (noxpy)
```bash
# download the wheels from the latest release, then:
python -m pip install core_pinaries-<ver>-py3-none-any.whl
python -m pip install noctics-<ver>-py3-none-any.whl

# optional: seed secrets before launching
# export OPENAI_API_KEY=...

# run Noctics (legacy stack)
cd noxpy
python main.py --help
python main.py --setup  # configure instruments once (writes to ~/.config/noctics)
python main.py tui      # optional: curses dashboard
```

## Install & setup (legacy Python)

## Rust stdin/stdout runner (noxrs)
```bash
cd experiments/noxrs
cargo run -- "hello from stdin/stdout runner"
# or echo "hi" | cargo run
```
This runner avoids HTTP entirely and streams tokens immediately. Replace its
synthetic token loop with real Zig-backed inference next.
**End users (binaries)**
```bash
curl -fsSL https://raw.githubusercontent.com/noctics/noctics/main/installer/noctics | bash
noctics --setup  # paste your API key once
```
The bootstrapper downloads from the latest GitHub release, checks your GPU VRAM,
selects the recommended bundle, and installs `noctics` into `~/.local/bin`
(Windows: `%LOCALAPPDATA%\Noctics\bin`).

**Developers (binary SDK)**
```bash
python -m pip install core_pinaries-<ver>-py3-none-any.whl
python -m pip install noctics-<ver>-py3-none-any.whl
noctics --setup
```
Export `OPENAI_API_KEY=…` (or point `NOCTICS_SECRETS_FILE` at a dotenv) before
the setup command if you want to skip the wizard prompt. For local-only use, pull
the tiny model once: `ollama create nox -f assets/runtime/nox.modelfile`.

> Step-by-step install logs (including known issues) live in
> `docs/install_walkthrough.md`.

## Local runtime tuning
Noctics now ships a single, tiny `nox` alias (Qwen 2.5 0.5B) and auto-starts the
bundled Ollama server by default whenever you point at
`http://127.0.0.1:11434/api/generate` (set `NOCTICS_AUTO_START_OLLAMA=0` to keep
the runtime manual). Interactive CLI sessions default to streaming results so
you see tokens as soon as they arrive.

Tune the inference payloads with these environment knobs:

- `NOX_NUM_THREADS` / `NOX_NUM_THREAD` — force the Ollama `num_thread` option.
  When unset Noctics detects the CPU count and caps it with
  `NOX_NUM_THREADS_CAP` (default 6 on Android/Termux builds).
- `NOX_NUM_CTX` plus the legacy `NOX_CONTEXT_LENGTH`, `NOX_CONTEXT_LEN`, or
  `OLLAMA_CONTEXT_LENGTH` identifiers — control the context window size per
  request.
- `NOX_NUM_BATCH` — set `num_batch` for request-time parallelism.
- `NOX_KEEP_ALIVE`, `NOX_OLLAMA_KEEP_ALIVE`, or `OLLAMA_KEEP_ALIVE` — keep the
  `nox` model alive between turns so Ollama does not tear down the runner.

Interactive sessions now stream plain `rei:` and `nox:` lines instead of drawing
ASCII bubbles or spinner lines, which keeps token output aligned and avoids the
`***` wrappers that some terminals add around the boxed art.

When Noctics auto-starts the Ollama server it seeds `OLLAMA_KEEP_ALIVE=24h`,
`OLLAMA_CONTEXT_LENGTH=1024`, `OLLAMA_NUM_PARALLEL=1`, and
`OLLAMA_MAX_LOADED_MODELS=1` so the bundled runtime is fast to spin up. If you
ever need to inspect what Ollama is doing, set `NOCTICS_DEBUG_OLLAMA=1`.
Additional runtime tuning guidance lives in
`docs/configuration.md#runtime-tuning`.

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
MODEL_SPECS='qwen2.5:0.5b=>nox' ./scripts/build_release.sh
```

## Packaging notes
- The PyInstaller spec (`release/noctics_release.spec`) bundles the CLI modules
  plus a tiny Qwen 0.5B GGUF. The runtime hook
  (`release/runtime_env.py`) auto-starts the embedded Ollama binary only when no
  external runtime is configured. Export `NOX_LLM_URL` (e.g.
  `https://api.openai.com/v1/chat/completions`) to skip the embedded server; the
  CLI maps the `nox` alias to a real OpenAI id via `NOX_OPENAI_MODEL`
  (default: `gpt-4o-mini`).
- Binary-only installs rely on `core/__init__.py` to fall back to the compiled
  extensions when the source tree is missing.
- Wheels and bundles are versioned off the commit count; bumping the tree adds a
  new patch version automatically.
- Bundled Qwen model weights remain under Apache-2.0; see `THIRD_PARTY_LICENSES.md`
  for attribution and ensure the file ships with every release artifact.
- `scripts/package_installer_artifacts.py` wraps the archive/manifest step; use
  `NOCTICS_INSTALLER_URL_PREFIX`, `NOCTICS_INSTALLER_VERSION`, and
  `NOCTICS_INSTALLER_BUILD` to bake CDN links and metadata during CI runs.

## Working on docs & telemetry
- Docs live under `docs/` (see `docs/users/` and `docs/dev/`) plus `core/docs/` for deep dives and `release/README.md` for release rituals.
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

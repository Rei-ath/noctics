# Noctics Developer Guide

This guide is for engineers extending Noctics, wiring up instruments, or shipping releases. If you need the basics, head back to the [User Guide](../users/index.md).

---

## Table of contents

- [Architecture snapshot](#architecture-snapshot)
- [Developer environment setup](#developer-environment-setup)
- [Instrumentation pipeline](#instrumentation-pipeline)
- [Memory and session logs](#memory-and-session-logs)
- [Persona and configuration overrides](#persona-and-configuration-overrides)
- [Automation, developer mode, and CLI tooling](#automation-developer-mode-and-cli-tooling)
- [Testing checklist](#testing-checklist)
- [Reference material](#reference-material)

---

## Architecture snapshot

```
repo/
├─ core/                 ← public noctics-core package
│  ├─ central/           ← chat client, persona, transport
│  ├─ noxl/              ← memory explorer
│  └─ docs/              ← deep-dive references (CLI, instruments, sessions)
├─ noctics_cli/          ← multitool wrapper, setup wizard, TUI
├─ core_pinaries/        ← Nuitka extensions for binary-only installs
├─ release/              ← PyInstaller specs and runtime hooks
└─ docs/                 ← guides (this file) + install/config references
```

Key runtime pieces:

- `central.core.ChatClient` – orchestrates turns, handles streaming, strips `<think>` blocks, manages session logging.
- `central.connector` + `central.transport` – build the HTTP request wrapper (Ollama, OpenAI-compatible APIs).
- `noctics_cli.multitool` – CLI entry point that picks source vs binaries and exposes chat/session commands.
- `nox_env` – environment loader that merges env vars, secrets files, and config homes.

---

## Developer environment setup

1. Create a virtual environment:
   ```bash
   python -m venv jenv
   source jenv/bin/activate
   python -m pip install -U pip
   ```
2. Install dependencies:
   ```bash
   python -m pip install -e core -r core/requirements.txt
   python -m pip install -e .           # brings in noctics_cli and shared tooling
   ```
3. Run the feedback loop:
   ```bash
   pytest core/tests -q
   ruff check core
   python core/main.py --stream
   ```

To force the CLI to load source modules instead of binaries, export `NOCTICS_USE_CORE_SOURCE=1` before launching `noctics`.

---

## Instrumentation pipeline

Nox tries to answer locally but can escalate to an external instrument. The entire exchange is recorded so replay and audits work without guesswork.

### Flow diagram

```
┌──────────┐   user turn   ┌────────────────────────┐
│ CLI chat │ ─────────────▶│ ChatClient.one_turn(...)│
└──────────┘               └────────┬───────────────┘
                                    │
                                    ▼
                           does local answer cover it?
                             │           │
                             │ yes       │ no
                             ▼           ▼
                   clean_public_reply   build `[INSTRUMENT QUERY]`
                             │           │
                             │           ▼
                             │   transport.send(...) or instrument.send_chat(...)
                             │           │
                             │           ▼
                             │   `[INSTRUMENT RESULT]` appended to messages
                             ▼
                    SessionLogger.log_turn(...)
```

### Data stored per turn

1. Local attempt (if successful) – appended as a normal assistant message.
2. When escalation happens:
   - `ChatClient.one_turn` records a `[INSTRUMENT QUERY]` message with role `"user"`.
   - The router (automation or human) calls `ChatClient.process_instrument_result`, which:
     - Adds the instrument payload (`[INSTRUMENT RESULT]`) as a `"user"` message.
     - Saves the merged assistant reply after `strip_chain_of_thought` and `clean_public_reply`.

Each JSONL entry ends up as:

```json
{
  "messages": [
    {"role": "system", "content": "...persona..."},
    {"role": "user", "content": "[INSTRUMENT QUERY]..."},
    {"role": "assistant", "content": "Final answer..."}
  ],
  "meta": {
    "model": "centi-nox",
    "turn": 3,
    "sanitized": true,
    "ts": "2025-01-01T12:34:56Z"
  }
}
```

### Smoke test recipe

Use matching models to keep the flow deterministic:

1. Set `NOX_LLM_URL` to your OpenAI endpoint and `NOX_LLM_MODEL=gpt-4o-mini`.
2. Set `NOX_INSTRUMENTS=gpt-4o` so the instrument has a little more headroom.
3. Enable automation or run the `/instrument` command manually.
4. Ask a heavyweight question so Nox escalates.
5. Capture the session file and feed it to a supervisor model (for example `gpt-5`) to confirm reasoning and context boundaries.

This combo mirrors production: the local Nox brain stays lightweight, the instrument carries the heavy lift, and the supervisor validates the transcript.

### Orchestration audit loop

Production keeps a standing orchestration audit that you should reproduce before major releases:

1. Launch Noctics with `gpt-4o-mini` as the local Nox model.
2. Configure the instrument roster with `gpt-4o` (or another stronger hosted model).
3. Run a scripted scenario that forces at least one instrument escalation (ARC-style puzzle, deep debugging brief, etc.).
4. After the run, hand the saved `session-*.jsonl` file to `gpt-5` acting as a supervisor. Ask it to rate:
   - Was the instrument request justified?
   - Did the instrument result get used correctly?
   - Is the final answer traceable from the logged turns?
5. Store that rating next to the session log (even a simple JSON blob in CI artifacts is enough).

If the supervisor flags drift—missing instrument calls, truncated context, or sloppy summaries—treat it as a regression.

**Latest smoke-test snapshot (2025-02-14)**  
We ran the loop end-to-end using `gpt-4o-mini` → `gpt-4o` → `gpt-5`. The supervisor returned a `rating: 4` with this feedback:

- Policy compliance: only nit was that the `[INSTRUMENT QUERY]` did not spell out “Instrument: gpt-4o”.
- Instrument usage: waited for the remote response and cited it in the final answer.
- Final answer: accurate but a bit generic—suggested calling out ARC-specific primitives.

Actionable fix: ensure Nox includes the instrument label inside the `[INSTRUMENT QUERY]` block (prompt updated), and bias the follow-up examples toward ARC primitives when applicable.

Additional observations from subsequent runs:
- The instrument prompt expects a mode; add `Mode: Explanation` inside the query to avoid a clarification loop.
- Keep the `[INSTRUMENT QUERY]` block raw (no code fences) so sanitizers and supervisors can parse it.
- Supervisor still wants ARC-grid specificity—mention connectivity, symmetry groups, and counterexample-driven program search when relevant.

### Automated audit harness (gpt-5 supervisor + gpt-5-pro meta)

- Script: `python scripts/run_orchestration_audit.py` (requires `OPENAI_API_KEY`).
  - Local Nox model: `gpt-4o-mini`.
  - Instrument: `gpt-4o` (queried once per scenario with `Mode: Explanation`).
  - Supervisors: `gpt-5` scores each scenario; `gpt-5-pro` aggregates the batch result.
- Outputs land in `data/orchestration_runs/orchestration_audit_*.json` with:
  - Per-scenario transcript snippets, instrument query/result, and both supervisor ratings.
  - gpt-5-pro meta summary capturing averages, highlights, gaps, and next steps.
- Useful flags:
  - `--scenario-ids arc_segmentation_connectivity,arc_rotation_symmetry` (limit to specific loops).
  - `--max-scenarios 5` (slice the canned list for budget control).
- Recommended workflow:
  1. Run single scenarios when quota is tight; each loop currently averages ~6 minutes end-to-end.
  2. Once several JSON reports exist, re-run the script over the combined scenario ids (or build a follow-up summarizer) so gpt-5-pro can score the larger batch.
  3. File the JSON checkpoints with release notes so regression deltas are traceable.

For extended reference material, see `core/docs/INSTRUMENTS.md`.

---

## Memory and session logs

Sessions live under the platform-specific memory root (`~/.local/share/noctics/memory/` by default). Structure:

```
memory/
  sessions/
    YYYY-MM-DD/
      session-20250101-123456.jsonl
      session-20250101-123456.meta.json
  early-archives/
```

- `session-*.jsonl` – append-only list of turns (`SessionLogger.log_turn`).
- `session-*.meta.json` – cached title, timestamps, display name, optional user id.
- Daily rollups (`day.json`) are built via `append_session_to_day_log`.

Adopting an existing log in code:

```python
from central.core.client import ChatClient

client = ChatClient(stream=False, sanitize=True)
client.adopt_session_log(Path("path/to/session-*.jsonl"))
```

More details live in `core/docs/SESSIONS.md`.

---

## Persona and configuration overrides

Persona resolution flows through `central.persona`:

1. Detect scale by model hints (`centi`, `milli`, etc.).
2. Load overrides from:
   - `config/persona.overrides.json`
   - `persona.override.json` or `persona.overrides.json` in the repo
   - Path set via `NOX_PERSONA_FILE`
3. Merge environment variables (`NOX_PERSONA_*`) last.

Runtime configuration comes from (highest precedence first):

1. Environment variables (`NOX_*`, `OPENAI_API_KEY`, etc.).
2. Secrets file or directory (`NOCTICS_SECRETS_FILE`, `NOCTICS_SECRETS_DIR`).
3. Config home JSON (`~/.config/noctics/central.json` or equivalent).
4. Project-level `config/central.json`.

Reload any changes with:

```python
from central.config import reload_config
reload_config()
```

Extended explanations live in `docs/configuration.md` and `core/docs/PERSONA.md`.

---

## Automation, developer mode, and CLI tooling

- **Instruments:** `NOX_INSTRUMENTS` seeds the roster; `NOX_INSTRUMENT_AUTOMATION=1` enables auto-routing.
- **Developer mode:** gate with `NOX_DEV_PASSPHRASE`. When active, `/shell` commands run, the HUD shows hardware context, and logs tag the developer identity.
- **Session CLI:** `noctics sessions list|show|rename|merge|archive` leverage the same `central.commands.sessions` code path as interactive slash commands.
- **TUI:** `noctics tui` renders an ncurses browser for sessions using `noctics_cli.tui`.
- **Binaries:** PyInstaller specs live in `release/noctics_release.spec`. Refresh binaries with `scripts/build_release.sh` from the repository root.

`core/docs/CLI.md` contains flag-by-flag detail if you need it.

---

## Testing checklist

Before shipping changes, run:

```bash
pytest core/tests -q
ruff check core noctics_cli
python scripts/build_release.sh --help  # ensure CLI works
```

Smoke tests to record:

1. **Local-only loop** – Configure Ollama or another local endpoint, run `noctics chat`, verify no instrument requests.
2. **Instrument escalation** – Follow the audit loop recipe above (`gpt-4o-mini` → `gpt-4o` → `gpt-5`). Confirm `[INSTRUMENT QUERY]` and `[INSTRUMENT RESULT]` blocks persist, and archive the supervisor rating.
3. **Session persistence** – Start a chat, rename it via `/title`, reload via `/load`, ensure metadata sticks.
4. **Binary CLI** – When working on releases, run the PyInstaller bundle once to ensure `noctics --help` works inside the archive.

Document the outcomes in `agents.plan` or your release checklist so the team can trace what happened.

---

## Reference material

- [User Guide](../users/index.md) – onboarding instructions you can share with operators.
- [Install Walkthrough](../install_walkthrough.md) – exact commands from a successful binary install.
- [Installer design](../installer_design.md) – architecture of the bootstrapper and CDN manifest.
- [Core CLI documentation](../../core/docs/CLI.md) – full flag list and slash commands.
- [Instrument guide](../../core/docs/INSTRUMENTS.md) – advanced routing scenarios.
- [Persona guide](../../core/docs/PERSONA.md) – persona catalog and overrides.
- [Session reference](../../core/docs/SESSIONS.md) – JSONL specs and tooling.
- [Configuration](../configuration.md) – secrets sources and precedence.

Keep the docs updated as you extend Noctics—clear references make the next release smoother for everyone.

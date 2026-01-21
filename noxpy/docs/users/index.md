# Noctics User Guide

Need a quick path to talking with Nox? This guide walks through the basics in plain English. If you want deeper technical notes, jump to the [Developer Guide](../dev/index.md).

---

## 1. What is Noctics?

Noctics bundles three pieces:

```
You → ask a question
      |
      v
[Nox brain]  ← local model you run
      |
 (optional)
      v
[Instrument] ← bigger remote model for tough jobs
```

You chat with the Noctics CLI, it sends your turns to the local Nox model, and only reaches for an instrument when your request needs more power (think heavy research, advanced math, or “ARC AGI” style puzzles).

---

## 2. Quick install checklist

1. **Download the bundle** – grab the archive for your platform from the release page or the link your team shared.
2. **Unpack and run the installer**:
   ```bash
   python installer/bootstrap.py --manifest /path/to/manifest.json
   ```
3. **Add the launcher to PATH** – the installer prints the directory (for example `~/.local/bin`). Ensure that folder is on your `PATH` so `noctics` works in every shell.

Need screenshots and every command? See the step‑by‑step [Install Walkthrough](../install_walkthrough.md).

---

## 3. First launch

1. Run the CLI:
   ```bash
   noctics --help
   ```
   You should see the welcome banner.
2. Configure secrets once:
   ```bash
   noctics --setup
   ```
   - Pick the provider you use (OpenAI, Anthropic, etc.).
   - Paste the API key when prompted. The CLI stores it in `~/.config/noctics/secrets.env` (or the platform equivalent) with safe permissions.
3. Optional: export your API key ahead of time to skip the prompt:
   ```bash
   export OPENAI_API_KEY=sk-...
   ```

---

## 4. Say hello to Nox

Launch the interactive chat:

```bash
noctics chat --stream
```

Try a quick question like “Give me a two‑line status update for the day.” The CLI stores the conversation under `~/.local/share/noctics/memory/` so you can revisit it later.

### Handy commands

- `noctics tui` – open the terminal dashboard to browse sessions.
- `/title New Name` – rename the current chat.
- `/load` – open a picker of previous sessions.

---

## 5. Instruments (when Nox needs backup)

Nox lives on your machine. Instruments are remote helpers (often bigger models) that take over when the local brain cannot answer confidently.

Situations where instruments help:

- Deep technical analysis (kernel debugging, theorem proofs).
- Benchmark puzzles (ARC‑AGI style).
- Long research reports that exceed local context limits.

### Data flow overview

```
User question
      |
      v
[Local Nox model] --"\u274c need help?"--> builds `[INSTRUMENT QUERY]`
      |                                      |
      |                                      v
      |                           [Instrument router]
      |                                      |
      |                          calls remote instrument
      |                                      |
      |                                      v
      |                         `[INSTRUMENT RESULT]` saved
      v
Final answer stored in session log
```

Both the original request and the instrument response get written to the session history. The dialogue looks like:

```
model (gpt-4o): [INSTRUMENT QUERY] … [/INSTRUMENT QUERY]
instrument (gpt-4o): …raw result…
model (gpt-4o): Final combined answer
```

Nothing breaks if you review the logs later—the instrument turns are tagged clearly.

All you need to do is follow the CLI prompt when it asks to call an instrument. If you already know which one to use, type `/instrument <name>`; otherwise accept the default it offers.

---

## 6. Memory at a glance

Noctics keeps lightweight logs so you can resume work.

```
~/.local/share/noctics/memory/
  sessions/
    YYYY-MM-DD/
      session-*.jsonl        ← chat history
      session-*.meta.json    ← title + timestamps
```

You do not need to manage these files manually. Use the CLI commands (`/sessions`, `/load`, `/rename`) to stay organized. Developers can dive deeper into the format in the [Developer Guide](../dev/index.md#memory-and-session-logs).

---

## 7. Troubleshooting quick hits

- **Command not found** – ensure the bin directory printed by the installer is on `PATH`.
- **Instrument prompt appeared but nothing happened** – run `noctics --setup` and confirm the API key is valid. You can also re-run with `--instrument gpt-4o` to force a label.
- **Want to start over** – delete the session from the TUI or use `/archive` to sweep older logs.

If issues persist, share the `session-*.jsonl` file with the support team (sensitive data removed) so they can investigate.

---

## 8. Where to learn more

- [Developer Guide](../dev/index.md) – architecture, automation, testing.
- [Install Walkthrough](../install_walkthrough.md) – full log of the installer run.
- [Configuration & Secrets](../configuration.md) – how the CLI discovers API keys.
- [Release Notes](../installer_design.md) – how the bundles get built.

Happy building! Nox is ready whenever you are.

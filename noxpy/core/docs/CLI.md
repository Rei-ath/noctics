# Nox CLI Playbook

Launch the multitool with `python main.py` or `noctics chat`. It slurps `.env`,
greets you, offers to restore a session, and then gets out of the way.

## Flag buffet

| Flag | Why you’d flip it |
|------|-------------------|
| `--url` / `-U` | Point at a different endpoint (defaults to `NOX_LLM_URL`). |
| `--model` / `-M` | Label the target model (`NOX_LLM_MODEL`). |
| `--system` | Inject your own system message (otherwise we hunt the usual prompt files). |
| `--user` / `-u` | Seed an opening user turn. |
| `--messages` / `-F` | Load a JSON array of messages; system messages get persona-fied automatically. |
| `--temperature` / `-t` | Sampling spice (default 0.7). |
| `--max-tokens` / `-T` | Cap the answer tokens (`-1` = unlimited if backend allows). |
| `--stream` / `--no-stream` | Force streaming or force batch mode. |
| `--sanitize` | Scrub common PII before sending. |
| `--raw` | In non-stream mode, also dump the raw JSON response. |
| `--show-think` | Leak `<think>` reasoning blocks instead of hiding them. |
| `--api-key` / `-k` | Direct API key (`NOX_LLM_API_KEY` / `OPENAI_API_KEY`). |
| `--instrument` | Set the label for external instruments (“claude”, “gpt-4o”, etc.). |
| `--anon-instrument` / `--no-anon-instrument` | Toggle sanitized instrument queries (default obeys env). |
| `--user-name` | Change the prompt label (“You” by default, overridable via `NOX_USER_NAME`). |
| `--dev` | Unlock developer mode (passphrase-gated). |
| `--sessions-*` | All the session management tricks: list, load, rename, merge, latest, archive, browse, show. |
| `--version` | Print the version and peace out. |

## Interactive slash commands

| Command | Action |
|---------|--------|
| `/instrument NAME` | Set instrument label (repeat to change or clear). |
| `/sessions` / `/ls` | List saved sessions. |
| `/last` | Show the most recent session summary. |
| `/archive` | Sweep older sessions into `memory/early-archives/`. |
| `/show ID` | Pretty-print a session without loading it. |
| `/browse` | Interactive picker for sessions. |
| `/load [ID]` | Load by id/index, or open picker if you omit arguments. |
| `/title NAME` | Rename the current session. |
| `/rename ID NAME` | Rename any saved session. |
| `/merge A B ...` | Merge multiple sessions. |
| `/name LABEL` | Change your prompt label mid-run. |
| `/shell CMD` | Execute a shell command (developer mode only). |
| `/reset` | Drop back to just the system prompt. |
| `exit`, `quit`, `Ctrl+C` | You know what these do. |

Tab completion is live for commands, instrument names, and session ids/indices.

## TUI dashboard
- Run `noctics tui` to open the curses-based session browser.
- Controls: arrow keys (or `j`/`k`) to move, `Enter` to load details, `r` to refresh, `q` to exit.
- The right panel shows a wrapped preview of the selected session’s recent turns.

## Instrument flow (how the magic routes)
1. Nox answers locally first.
2. If it needs help, it asks for an instrument label (respecting env/config rosters).
3. It emits a sanitized `[INSTRUMENT QUERY] ... [/INSTRUMENT QUERY]`.
4. No router? You’ll get instructions to handle it manually.
5. With automation on, feed the response into `ChatClient.process_instrument_result` and
   Nox stitches `[INSTRUMENT RESULT] ...` back into the chat.

Env toggles:
```text
NOX_INSTRUMENTS                   # explicitly list instrument names
NOX_INSTRUMENT_AUTOMATION         # turn automation on (1/true/on)
NOX_INSTRUMENT_PLUGINS             # comma list of modules that call register_instrument
NOX_INSTRUMENT_ANON                # hide instrument prompts when logging
NOX_REDACT_NAMES                   # comma list of names to scrub
```

## Developer mode perks
- Prompt swaps to `memory/system_prompt.dev.*`
- Nox can emit `[DEV SHELL COMMAND]` blocks—CLI executes them and logs the `[DEV SHELL RESULT]`
- `/shell <cmd>` available for manual runs
- Identity label marks you as the developer (default: Rei)
- Hardware stats + instrument roster get stapled onto the system prompt

Passphrase order: `NOX_DEV_PASSPHRASE`, config value, then default `jx0`.

## First-run experience
1. CLI lists known users, shows session titles, and asks if you want streaming.
2. It seeds the system prompt with persona info + hardware context.
3. On a completely fresh install, Nox suggests a title and applies it automatically.
4. Titles can be changed anytime via `/title` or `[SET TITLE]New Name[/SET TITLE]`.

## Session handling
Default home: `~/.local/share/noctics/memory/sessions/YYYY-MM-DD/`

Files:
- `session-*.jsonl` — turn-by-turn log
- `session-*.meta.json` — metadata (id, title, created/updated)
- `day.json` — daily rollup, auto-maintained

Commands recap:
- `--sessions-ls` / `/sessions` — list
- `--sessions-load` / `/load` — restore
- `--sessions-rename` / `/rename` — rename
- `--sessions-merge` / `/merge` — combine
- `--sessions-archive-early` / `/archive` — sweep to `early-archives`

Set `NOCTICS_MEMORY_HOME` if you want a different root. Legacy repo-stored sessions are migrated the first time you run a new build.

## Memory explorer (`noxl`) crash course
```bash
python -m noxl --limit 10
python -m noxl --search "instrument"
python -m noxl --show session-20250101-010203 --raw
python -m noxl rename session-20250101-010203 "Postmortem"
python -m noxl merge session-A session-B --title "Combo Tape"
python -m noxl archive
```
Use `--root PATH` to point at alternate directories like `memory/early-archives`.

## Config priorities
1. Env vars (`NOX_*`)
2. JSON config (`config/central.json` or path in `NOX_CONFIG`)
3. Built-in defaults

Example JSON:
```json
{
  "instrument": {
    "automation": false,
    "roster": ["claude", "gpt-4o"]
  }
}
```

## Quick combos
```bash
# Stream with instrument label
python main.py --stream --instrument claude

# Batch question, show reasoning, dump raw JSON
python main.py --user "Explain vector clocks" --no-stream --show-think --raw

# Resume a session and rename it
python main.py --sessions-load session-20250913-234409 \
  --sessions-rename session-20250913-234409 "Midnight Debugging"

# Developer mode with shell autopsy
NOX_DEV_PASSPHRASE=jx0 python main.py --dev --stream
```

Now you know the levers. Pull them responsibly—or not, I’ll still log everything.

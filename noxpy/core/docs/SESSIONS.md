# Session Vault Manual (keep receipts like Nox)

Nox logs every turn so you never lose a thread. Here’s how the vault works and how to boss it around.

## Where everything lives
- Default root: `~/.local/share/noctics/memory/`
- Sessions: `sessions/YYYY-MM-DD/session-*.jsonl`
- Metadata: `session-*.meta.json`
- Day rollup: `day.json`
- Archives live under `early-archives/`

Set `NOCTICS_MEMORY_HOME` if you want to park the vault somewhere else. On first run, legacy `memory/` content inside the repo gets migrated automatically.

## File anatomy
- `session-20250101-010203.jsonl` → turn-by-turn log
- `session-20250101-010203.meta.json` → id, title, created/updated, custom flag, instrument info
- `day.json` → deduped summary for the day

## Titles & naming rights
- Auto-title fires when a session ends with no custom title—pulled from the first meaningful user message.
- Manual options:
  - In chat: `/title My Topic`
  - CLI flag: `python main.py --sessions-rename session-YYYYMMDD-HHMMSS "My Topic"`
- Rename saved sessions later with `/rename` or `--sessions-rename`.
- Nox can self-rename mid-chat via `[SET TITLE]New Name[/SET TITLE]`.

## Listing, loading, archiving
| Action | Command |
|--------|---------|
| List sessions | `python main.py --sessions-ls` or `/sessions` |
| Latest summary | `python main.py --sessions-latest` or `/last` |
| Pretty-print | `python main.py --sessions-show ID` or `/show ID` |
| Browse picker | `python main.py --sessions-browse` or `/browse` |
| Load as context | `python main.py --sessions-load ID` or `/load [ID]` |
| Archive old runs | `python main.py --sessions-archive-early` or `/archive` |
| Merge multiple | `python main.py --sessions-merge A B` or `/merge A B` |

Loading reinstates the turns and starts a new live session; it doesn’t append to the old file.

## `noxl` toolbox
```bash
python -m noxl --limit 10
python -m noxl --search "memory leak"
python -m noxl --show session-20250101-010203 --raw
python -m noxl rename session-20250101-010203 "Prod Outage Retro"
python -m noxl merge session-A session-B --title "Combo Tape"
python -m noxl archive
python -m noxl meta session-20250101-010203
python -m noxl count --search instrument
```
Add `--root PATH` to poke alternate directories (imports, archives, etc.).

Programmatic utilities:
```python
from noxl import list_sessions, load_session_messages, compute_title_from_messages
```

## Merge behavior
- Keeps the first system message, then concatenates user/assistant turns in order.
- New session lands under the normal root with a title like `Merged: A | B`.
- Rename later if you hate the default.

## Telemetry heads-up
CLI run metrics live in `memory/telemetry/metrics.json` (run counts, timestamps, per-version totals). Nothing leaves the machine unless you send it.

Stay organized and I’ll always have context the next time you ping me at 3 AM.

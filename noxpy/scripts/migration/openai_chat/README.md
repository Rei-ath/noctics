# ChatGPT Export Wrangler

Drag your OpenAI `conversations.json` files through this funnel and get clean
Noctics session logs without polluting the live vault.

## Drop zones
```
data/openai_chat_exports/       # toss raw exports here
scripts/migration/openai_chat/  # these tools
memory/imported/openai/         # output lives here, separate from runtime sessions
```

## Peek before you import
```bash
python scripts/migration/openai_chat/preview_conversation.py \
  --export data/openai_chat_exports/conversations.json \
  --index 0 --max-chars 120
```
Flags:
- `--index` or `--id` to pick the convo
- `--max-chars` to keep the preview short enough for your terminal

## Convert the goods
```bash
python scripts/migration/openai_chat/migrate.py \
  --export data/openai_chat_exports/conversations.json \
  --index 0
```
Options worth knowing:
- `--all` – migrate every conversation
- `--dry-run` – see the plan, touch nothing
- `--max-turns N` – keep only the latest N turns in the active log (`0` keeps everything inline)
- `--output-root PATH` – drop results somewhere else

Outputs land under `memory/imported/openai/YYYY-MM-DD/` with JSONL turns plus a `.meta.json`
that records the original IDs and source (`openai-chat-export`). Trimmed histories write a
sidecar `<session>.full.jsonl` so Nox can pull the rest when needed.

## Next moves
- Add filters like `--title-contains` or `--since 2024-01-01` when you get picky.
- Wrap the migration scripts in pytest cases so format changes don’t blindside us.
- Build an instrument worker that copies curated imports into `memory/sessions/` for interactive browsing.

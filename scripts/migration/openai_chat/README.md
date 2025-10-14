# OpenAI → Noctics Migration Toolkit

Tools for inspecting and converting OpenAI ChatGPT exports (`conversations.json`) into Noctics-compatible session logs without mixing them with native sessions.

## Layout

```
data/openai_chat_exports/       # drop ChatGPT export files here
scripts/migration/openai_chat/  # utilities and CLI wrappers
memory/imported/openai/         # migration output (kept separate from runtime sessions)
```

## Preview a Conversation

```bash
python scripts/migration/openai_chat/preview_conversation.py \
  --export data/openai_chat_exports/conversations.json \
  --index 0 --max-chars 120
```

Flags:
- `--index` – pick by position (0-based)
- `--id` – pick by conversation id
- `--max-chars` – truncate message preview

## Migrate to Noctics Format

```bash
python scripts/migration/openai_chat/migrate.py \
  --export data/openai_chat_exports/conversations.json \
  --index 0
```

- Outputs JSONL + meta files under `memory/imported/openai/YYYY-MM-DD/`.
- Use `--all` to convert every conversation.
- Add `--dry-run` to see what would be written without touching disk.
- Use `--max-turns N` (default 30) to keep only the latest N turns in the active log; set to `0` to keep the full history inline.
- When a conversation is trimmed, a companion `<session>.full.jsonl` is written and the meta file records `full_history_path` so Central can pull older turns automatically later.
- Use `--output-root` to change the destination directory.

Migrated sessions are tagged with `source: "openai-chat-export"` and stored outside `memory/sessions/`, so Noctics can tell imported logs apart from native runtime history.

## Next Steps

- Add filters (`--title-contains`, `--since`) if you want to cherry-pick batches.
- Plug the pipeline into tests so future export format changes don’t break migration.
- Build a helper command to copy selected imports into `memory/sessions/` if you ever want them visible inside Noctics’ interactive session browser.

# Instrument Hustle (how Nox calls in backup)

Nox knows when it’s outmatched and needs an external instrument—an LLM router,
another provider, whatever muscle you’ve got. Here’s how to control the flow.

## Label the instrument
- CLI flags: `--instrument claude`
- Slash command: `/instrument claude`
- No label set? You’ll get a picker with whatever roster we know about.

Rosters come from:
1. `NOX_INSTRUMENTS` env var (`"claude,gpt-4o,grok"`)
2. `config/central.json`:
   ```json
   {
     "instrument": {
       "roster": ["claude", "gpt-4o"],
       "automation": false
     }
   }
   ```
3. Built-in defaults if you’re too lazy to configure

## Sanitization + tags
- `--sanitize` (or env defaults) scrubs common PII.
- `NOX_REDACT_NAMES="Alice,Bob"` masks extra tokens.
- Instrument requests show up as:
  ```
  [INSTRUMENT QUERY]
  ...
  [/INSTRUMENT QUERY]
  ```
- `--anon-instrument` (aliases respect `NOX_INSTRUMENT_ANON`) keeps identifiers vague when logging.

## Built-in providers
- **OpenAI** – Models starting with `gpt`, `o1`, or URLs hitting `api.openai.com`.
- **Anthropic** – Any `claude-*`, `haiku`, or `sonnet` models, plus `api.anthropic.com`.
- More? Drop a plugin that imports `instruments.register_instrument` and call it with your class. Set
  `NOX_INSTRUMENT_PLUGINS="your_module,another_module"` to auto-import on startup.

## Automation story
1. Nox explains why an instrument is needed and prints the sanitized query.
2. Automation off (default): you get instructions to run it yourself.
3. Automation on: set `NOX_INSTRUMENT_AUTOMATION=1`. A router listens for the query, sends it out, and feeds `[INSTRUMENT RESULT]` back to Nox.
4. `ChatClient.process_instrument_result(...)` handles the stitching so the conversation resumes smoothly.

## Custom routers
If you’re writing your own router:
- Watch session logs for `[INSTRUMENT QUERY]`.
- Parse the label (if any) and query text.
- Send the request to your provider, collect the response.
- Feed it back via the CLI prompt or `process_instrument_result`.

## Pro tips
- Keep instrument names short and unique—makes tab-completion happier.
- Use env overrides per deployment (`NOX_INSTRUMENTS="gpt-4o,claude"`) so you don’t leak internal rosters.
- Remember to sanitize instrument outputs before you paste them back; Nox logs everything by default.

That’s the playbook. Automate it, extend it, or ignore it and keep doing manual pastes—either way, I’m logging the receipts.

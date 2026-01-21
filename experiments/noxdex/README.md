# NoxdEx (experiment)

NoxdEx is an experiment that connects the Codex CLI to the Nox session logger.
Think of it as Nox × Codex.
It spawns the `codex` process, captures the reply, and stores sessions under
`experiments/noxdex/memory/`.

## Requirements
- `codex` CLI available in `PATH` (or set `NOXDEX_CODEX_BIN`)

## Quick start
- `bin/noxdex` (interactive)
- `bin/noxdex "Explain this function"` (one-shot)
- `bin/noxdex --stream "Show a refactor"` (streaming)
- `bin/noxdex --wrap "Summarize"` (emit `[INSTRUMENT RESULT]` wrappers)

## Session commands
- `/sessions` list sessions
- `/load ID` load a saved session (id or index)
- `/new` start a fresh session
- `/exit` quit

## Configuration
- `NOXDEX_MEMORY_HOME` overrides the memory root
- `NOXDEX_CODEX_BIN` (or `CODEX_BIN`) overrides the codex CLI path
- `NOXDEX_CODEX_ARGS` (or `CODEX_ARGS`) adds extra codex CLI args (`{prompt}` placeholder supported)
- `NOXDEX_CODEX_STDIN=1` sends the prompt over stdin
- `NOXDEX_CODEX_MODEL` sets the session log model label
- `--system` or `--system-file` sets the system prompt

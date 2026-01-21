# Runox (experiment)

Runox is an experiment that runs the local `runox` runner against
`assets/models/nox.gguf` and stores session memory under
`experiments/runox/memory/`. It is a general-purpose local assistant.

Terminology: Nox is the model, Runox is the inference engine, and Noctics is the
CLI built on top.

## Requirements
- `bin/runox` built (see `scripts/build_runox.sh`)
- `assets/models/nox.gguf` present

## Quick start
- `bin/runox` (interactive)
- `bin/runox "Explain this function"` (one-shot)
- `bin/runox --stream "Show a refactor"` (streaming)
- `bin/runox --wrap "Summarize"` (emit `[INSTRUMENT RESULT]` wrappers)

## Session commands
- `/sessions` list sessions
- `/load ID` load a saved session (id or index)
- `/new` start a fresh session
- `/exit` quit

## Configuration
- `RUNOX_MEMORY_HOME` overrides the memory root
- `NOX_LOCAL_RUNNER` overrides the runner path
- `NOX_MODEL_PATH` overrides the GGUF model
- `--system` or `--system-file` sets the system prompt

# Local Install Walkthrough (single model: `nox`)

This project now ships a single tiny local model alias: `nox` (Qwen 2.5 0.5B).

> **Prerequisites**
> - Python 3.11+
> - Ollama installed (`ollama --version`)
> - ~600MB free disk space for `assets/models/nox.gguf`

## 1. Start Ollama

In a separate terminal, run:

```bash
ollama serve
```

## 2. Create the `nox` model from the bundled GGUF

```bash
ollama create nox -f assets/runtime/nox.modelfile
ollama list | grep -E '^nox\\b' || true
```

## 3. Run Noctics against the local endpoint

```bash
export NOX_LLM_URL=http://127.0.0.1:11434/api/chat
export NOX_LLM_MODEL=nox
python main.py
```

If you want to use a remote provider instead, set `NOX_LLM_URL` to the provider
endpoint and `NOX_OPENAI_MODEL` (or `NOX_LLM_MODEL`) to your desired model id.

### Optional tuning

Want more throughput without switching models? Export the following before
running `python main.py`:

- `NOX_NUM_THREADS` / `NOX_NUM_THREAD` — pin the number of CPU threads Ollama
  uses (falling back to autodetect plus `NOX_NUM_THREADS_CAP`, which is 6 by
  default on Termux/Android).
- `NOX_NUM_CTX` (or `NOX_CONTEXT_LENGTH` / `NOX_CONTEXT_LEN`) — shrink or grow
  the per-request context length.
- `NOX_NUM_BATCH` — raise `num_batch` to let Ollama take more tokens per
  request cycle.
- `NOX_KEEP_ALIVE`, `NOX_OLLAMA_KEEP_ALIVE`, or `OLLAMA_KEEP_ALIVE` — keep the
  `nox` runner alive between turns, e.g. `export NOX_KEEP_ALIVE=24h`.

The CLI now streams responses as plain `rei:` / `nox:` prefixed lines, keeping
tokens aligned without the previous ASCII bubbles or spinner art.
Noctics auto-starts Ollama with `OLLAMA_KEEP_ALIVE=24h`, `OLLAMA_CONTEXT_LENGTH=1024`,
`OLLAMA_NUM_PARALLEL=1`, and `OLLAMA_MAX_LOADED_MODELS=1`. Set
`NOCTICS_AUTO_START_OLLAMA=0` to manage the runtime yourself, or
`NOCTICS_DEBUG_OLLAMA=1` to surface the server logs. If the Ollama runner locks
up, `ollama stop`/`pkill ollama` then re-run `ollama serve` before restarting
Noctics; the cached `nox` model stays ready (`ollama list` shows it).

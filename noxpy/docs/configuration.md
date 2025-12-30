# Configuration & Secrets

Nox expects runtime settings to come from the environment. In production we avoid
shipping plaintext `.env` files and instead load secrets from a dedicated
backend.

## Secret sources

`nox_env.get_env()` now checks these locations (in order):

1. Real environment variables (`export NOX_LLM_URL=...`).
2. A dotenv-style file pointed to by `NOCTICS_SECRETS_FILE`.
3. A directory mount pointed to by `NOCTICS_SECRETS_DIR` (each file name is a key).
4. The global config home (default `~/.config/noctics/secrets.env` on Linux,
   `~/Library/Application Support/Noctics/secrets.env` on macOS,
   `%APPDATA%\Noctics\secrets.env` on Windows).

Both hints can be supplied simultaneously—values from the secrets file win
before the directory listing. Entries are cached in-process after the first
lookup.

```bash
# Example: render secrets into a tmpfs directory via your secrets manager
export NOCTICS_SECRETS_DIR=/run/secrets/noctics
export NOX_LLM_MODEL=nox   # non-secret override stays inline
```

For systems like Doppler, Chamber, or HashiCorp Vault, configure their CLI to
materialise a dotenv and point `NOCTICS_SECRETS_FILE` at the generated path.

```bash
# Doppler example
NOCTICS_SECRETS_FILE=$(doppler secrets download --no-file --format=env) \
  noctics --stream
```

## Local development

Developers can still use the repo-level `.env` for quick bootstrapping, but the
`OPENAI_API_KEY` placeholder is intentionally blank. Copy `.env` to `.env.local`
(or export the key in your shell) to avoid committing live credentials.

```bash
cp .env .env.local
printf 'OPENAI_API_KEY=sk-...' >> .env.local
NOCTICS_SECRETS_FILE=.env.local python main.py --stream
```

## CI integration

Add the secret hints as masked variables in your CI system and point
`NOCTICS_SECRETS_FILE` at the location where the pipeline mounts credentials.
Because the loader trims whitespace, both classic dotenv files and individual
key files work without extra glue code.

## Global config home

The CLI now reserves a per-user config directory:

- Linux: `~/.config/noctics`
- macOS: `~/Library/Application Support/Noctics`
- Windows: `%APPDATA%\Noctics`

`noctics --setup` writes `central.json` (instrument roster) and `secrets.env`
there, and the runtime automatically checks this location for defaults.

## Runtime tuning

Noctics exposes a handful of additional environment variables to tune the Ollama-based runtime directly. These map to options that arrive with every payload and help work around lower-end hardware without swapping models.

- `NOX_NUM_THREADS` / `NOX_NUM_THREAD` — override `num_thread`. When they are unset Noctics detects CPU availability and caps it with `NOX_NUM_THREADS_CAP` (default 6 on Termux/Android to prevent oversubscription).
- `NOX_NUM_CTX` (and its aliases `NOX_CONTEXT_LENGTH`, `NOX_CONTEXT_LEN`, or `OLLAMA_CONTEXT_LENGTH`) — control `num_ctx` to tune the effective context window.
- `NOX_NUM_BATCH` — increase the `num_batch` option to trade memory for throughput.
- `NOX_KEEP_ALIVE`, `NOX_OLLAMA_KEEP_ALIVE`, or `OLLAMA_KEEP_ALIVE` — supply a string such as `24h` to keep the model loaded between requests so the runner does not tear down immediately.
When Noctics auto-starts Ollama it seeds `OLLAMA_KEEP_ALIVE=24h`, `OLLAMA_CONTEXT_LENGTH=1024`, `OLLAMA_NUM_PARALLEL=1`, and `OLLAMA_MAX_LOADED_MODELS=1` so the embedded runtime boots quickly. Toggle `NOCTICS_AUTO_START_OLLAMA=0` when you prefer to manage the Ollama server by hand, and set `NOCTICS_DEBUG_OLLAMA=1` to capture the service logs.

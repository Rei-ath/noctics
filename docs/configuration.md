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
export NOX_LLM_MODEL=centi-nox   # non-secret override stays inline
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

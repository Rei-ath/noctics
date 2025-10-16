#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ASSETS_DIR="$ROOT_DIR/assets"
OLLAMA_ROOT="$ASSETS_DIR/ollama"
OLLAMA_BIN_DIR="$OLLAMA_ROOT/bin"
OLLAMA_LIB_DIR="$OLLAMA_ROOT/lib"
OLLAMA_MODELS_DIR="$OLLAMA_ROOT/models"
RUNTIME_DIR="$ASSETS_DIR/runtime"
MODEL_POINTER_FILE="$OLLAMA_MODELS_DIR/.active_model"
PRIMARY_ALIAS_FILE="$RUNTIME_DIR/primary_alias.txt"
LITE_ALIAS_FILE="$RUNTIME_DIR/lite_alias.txt"
LAYMA_OLLAMA_URL="https://github.com/Rei-ath/LayMA/raw/main/ollama"

# Default model plan: map Qwen3 tiers onto Noctics scale aliases. Override via
# MODEL_SPECS="src=>alias src=>alias ...".
MODEL_SPECS=${MODEL_SPECS:-"qwen3:8b=>centi-noctics qwen3:1.7b=>micro-noctics qwen3:4b=>milli-noctics qwen3:0.6b=>nano-noctics"}

log() {
  echo "[prepare_assets] $*" >&2
}

die() {
  log "error: $*"
  exit 1
}

ensure_directories() {
  mkdir -p "$OLLAMA_BIN_DIR" "$OLLAMA_LIB_DIR" "$OLLAMA_MODELS_DIR" "$RUNTIME_DIR"
}

install_ollama_binary() {
  local dest="$OLLAMA_BIN_DIR/ollama"
  if [[ -x "$dest" ]]; then
    return
  fi
  log "Downloading Ollama runtime from LayMA"
  local tmp
  tmp="$(mktemp -p "${TMPDIR:-/tmp}" ollama.XXXXXX)"
  curl -fL "$LAYMA_OLLAMA_URL" -o "$tmp"
  install -Dm755 "$tmp" "$dest"
  rm -f "$tmp"
}

parse_specs() {
  readarray -t SPEC_LIST < <(printf '%s\n' $MODEL_SPECS)
  if [[ ${#SPEC_LIST[@]} -eq 0 ]]; then
    die "MODEL_SPECS resolved to an empty list"
  fi
}

launch_server() {
  local port host
  port="${OLLAMA_TEMP_PORT:-$(python3 - <<'PY'
import socket
with socket.socket() as s:
    s.bind(('127.0.0.1', 0))
    print(s.getsockname()[1])
PY
  )}"
  host="127.0.0.1:${port}"
  log "Starting temporary Ollama server on ${host}"
  env OLLAMA_HOST="$host" \
      OLLAMA_HOME="$DL_ROOT" \
      OLLAMA_MODELS="$DL_ROOT/models" \
      "$OLLAMA_BIN_DIR/ollama" serve \
      >"$DL_ROOT/ollama-serve.log" 2>&1 &
  SERVER_PID=$!
  OLLAMA_HOST_URL="http://${host}"
  for _ in {1..60}; do
    if curl -sSf "$OLLAMA_HOST_URL/api/version" >/dev/null 2>&1; then
      return
    fi
    sleep 2
  done
  kill "$SERVER_PID" >/dev/null 2>&1 || true
  wait "$SERVER_PID" >/dev/null 2>&1 || true
  die "Ollama server on ${host} did not become ready"
}

stop_server() {
  kill "$SERVER_PID" >/dev/null 2>&1 || true
  wait "$SERVER_PID" >/dev/null 2>&1 || true
}

pull_and_alias_models() {
  KEEP_NAMES=()
  PRIMARY_DIGEST=""
  PRIMARY_ALIAS=""
  LITE_ALIAS=""
  local index=0
  for raw_spec in "${SPEC_LIST[@]}"; do
    local source alias alias_dir source_dir
    if [[ "$raw_spec" == *"=>"* ]]; then
      source="${raw_spec%%=>*}"
      alias="${raw_spec##*=>}"
    else
      source="$raw_spec"
      alias="$raw_spec"
    fi
    source_dir="${source%%:*}"
    alias_dir="${alias%%:*}"
    KEEP_NAMES+=("$source_dir")
    KEEP_NAMES+=("$alias_dir")
    log "Pulling ${source}"
    env OLLAMA_HOST="$OLLAMA_HOST_URL" "$OLLAMA_BIN_DIR/ollama" pull "$source"
    if [[ "$alias" != "$source" ]]; then
      log "Creating alias ${alias} -> ${source}"
      env OLLAMA_HOST="$OLLAMA_HOST_URL" "$OLLAMA_BIN_DIR/ollama" cp "$source" "$alias"
    fi

    if [[ $index -eq 0 ]]; then
      PRIMARY_ALIAS="$alias"
      PRIMARY_DIGEST="$(manifest_digest "$source")"
    elif [[ -z "$LITE_ALIAS" ]]; then
      LITE_ALIAS="$alias"
    fi
    ((index++))
  done

  if [[ -z "$PRIMARY_DIGEST" ]]; then
    die "Unable to determine primary model digest"
  fi

  rm -rf "$OLLAMA_MODELS_DIR"
  mkdir -p "$OLLAMA_MODELS_DIR"
  cp -a "$DL_ROOT/models/." "$OLLAMA_MODELS_DIR/"

  tidy_manifests
  tidy_blobs
  write_metadata "$PRIMARY_DIGEST" "$PRIMARY_ALIAS" "$LITE_ALIAS"
}

manifest_digest() {
  local source="$1" base_name manifest_file
  base_name="${source%%:*}"
  manifest_file="$DL_ROOT/models/manifests/registry.ollama.ai/library/${base_name}/latest"
  if [[ ! -f "$manifest_file" ]]; then
    die "Missing manifest for ${source} at ${manifest_file}"
  fi
  python3 - <<'PY'
import json, sys
manifest_path = sys.argv[1]
with open(manifest_path, 'r', encoding='utf-8') as fh:
    data = json.load(fh)
layers = data.get('layers', [])
if not layers:
    raise SystemExit('no layers in manifest')
print(layers[0]['digest'].split(':', 1)[1])
PY
  "$manifest_file"
}

tidy_manifests() {
  local manifest_root="$OLLAMA_MODELS_DIR/manifests/registry.ollama.ai/library"
  mkdir -p "$manifest_root"
  local keep_map=" ${KEEP_NAMES[*]} "
  find "$manifest_root" -mindepth 1 -maxdepth 1 -type d | while read -r dir; do
    local name
    name="$(basename "$dir")"
    if [[ "${keep_map}" != *" ${name} "* ]]; then
      rm -rf "$dir"
    fi
  done
}

tidy_blobs() {
  local manifest_root="$OLLAMA_MODELS_DIR/manifests/registry.ollama.ai/library"
  local keep_digests
  keep_digests="$(python3 - <<'PY'
import json, sys, os
root = sys.argv[1]
digests = set()
for dirpath, _, filenames in os.walk(root):
    for filename in filenames:
        path = os.path.join(dirpath, filename)
        try:
            with open(path, 'r', encoding='utf-8') as fh:
                data = json.load(fh)
        except Exception:
            continue
        for layer in data.get('layers', []):
            digests.add(layer['digest'].split(':', 1)[1])
        config = data.get('config') or {}
        if 'digest' in config:
            digests.add(config['digest'].split(':', 1)[1])
print('\n'.join(sorted(digests)))
PY
    "$manifest_root")"
  local keep_pattern=" $(echo "$keep_digests" | tr '\n' ' ') "
  find "$OLLAMA_MODELS_DIR/blobs" -type f -name 'sha256-*' | while read -r blob; do
    local digest="${blob##*/sha256-}"
    if [[ "${keep_pattern}" != *" ${digest} "* ]]; then
      rm -f "$blob"
    fi
  done
}

write_metadata() {
  local digest="$1" primary_alias="$2" lite_alias="$3"
  local blob_path="assets/ollama/models/blobs/sha256-${digest}"
  printf '%s' "$blob_path" >"$MODEL_POINTER_FILE"
  printf '%s\n' "$primary_alias" >"$PRIMARY_ALIAS_FILE"
  if [[ -n "$lite_alias" ]]; then
    printf '%s\n' "$lite_alias" >"$LITE_ALIAS_FILE"
  else
    rm -f "$LITE_ALIAS_FILE"
  fi
}

main() {
  ensure_directories
  install_ollama_binary
  parse_specs

  DL_ROOT="${OLLAMA_DOWNLOAD_ROOT:-$ROOT_DIR/.ollama-download}"
  rm -rf "$DL_ROOT"
  mkdir -p "$DL_ROOT"

  launch_server
  trap stop_server EXIT
  pull_and_alias_models
  stop_server
  trap - EXIT
  rm -rf "$DL_ROOT"
}

main "$@"

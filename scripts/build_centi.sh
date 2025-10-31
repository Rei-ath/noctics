#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SPEC_FILE="$ROOT_DIR/release/noctics_centi.spec"
DIST_DIR="$ROOT_DIR/dist"
BUILD_DIR="$ROOT_DIR/.pyi-build"
MODEL_POINTER_FILE="$ROOT_DIR/assets/ollama/models/.active_model"
MODEL_PATH="${MODEL_PATH:-}"
DEFAULT_MODEL_NAME="centi-nox"
FALLBACK_FILE="$ROOT_DIR/assets/runtime/fallback_remote_url.txt"

if [[ -z "$MODEL_PATH" ]]; then
  MODEL_PATH="${1:-}"
fi

if [[ -z "$MODEL_PATH" ]]; then
  TARGET_MODEL_NAME="${MODEL_NAME_OVERRIDE:-$DEFAULT_MODEL_NAME}"
  if [[ "${NOCTICS_SKIP_ASSET_PREP:-0}" != "1" ]]; then
    if [[ -f "$MODEL_POINTER_FILE" && -d "$ROOT_DIR/assets/ollama/models/blobs" ]]; then
      echo "[build_centi] Reusing existing model assets under assets/ollama/models" >&2
    else
      PREP_SCRIPT="$ROOT_DIR/scripts/prepare_assets.sh"
      if [[ ! -x "$PREP_SCRIPT" ]]; then
        echo "[build_centi] Asset prep script missing: $PREP_SCRIPT" >&2
        exit 1
      fi
      MODEL_NAME="$TARGET_MODEL_NAME" "$PREP_SCRIPT"
    fi
  fi

  if [[ -z "$MODEL_PATH" && -f "$MODEL_POINTER_FILE" ]]; then
    MODEL_PATH="$(<"$MODEL_POINTER_FILE")"
  elif [[ -z "$MODEL_PATH" ]]; then
    echo "[build_centi] Unable to determine model path; run prepare_assets first" >&2
    exit 1
  fi

  if [[ "${MODEL_PATH:0:1}" != "/" ]]; then
    MODEL_PATH="$ROOT_DIR/$MODEL_PATH"
  fi
fi

if [[ ! -f "$MODEL_PATH" ]]; then
  echo "[build_centi] MODEL_PATH does not exist: $MODEL_PATH" >&2
  exit 1
fi

if ! command -v pyinstaller >/dev/null 2>&1; then
  echo "[build_centi] pyinstaller not found on PATH" >&2
  exit 1
fi

mkdir -p "$DIST_DIR" "$BUILD_DIR"
rm -rf "$DIST_DIR/centi-noctics"

if [[ -n "${NOCTICS_FALLBACK_REMOTE_URL:-}" ]]; then
  printf '%s\n' "$NOCTICS_FALLBACK_REMOTE_URL" > "$FALLBACK_FILE"
elif [[ ! -f "$FALLBACK_FILE" ]]; then
  printf '%s\n' "https://layma.noctics.ai/api/generate" > "$FALLBACK_FILE"
fi

MODEL_FILENAME="$(basename "$MODEL_PATH")"
NOCTICS_MODEL_PATH="$(cd "$(dirname "$MODEL_PATH")" && pwd)/$MODEL_FILENAME"

NOCTICS_MODEL_PATH="$NOCTICS_MODEL_PATH" \
NOCTICS_MODEL_NAME="$MODEL_FILENAME" \
NOCTICS_ROOT="$ROOT_DIR" \
NOCTICS_SKIP_EMBEDDED_OLLAMA=1 \
pyinstaller "$SPEC_FILE" \
  --distpath "$DIST_DIR" \
  --workpath "$BUILD_DIR" \
  --clean \
  --noconfirm

echo "[build_centi] Centi build available under $DIST_DIR/centi-noctics" >&2

if [[ -d "$DIST_DIR/centi-noctics" ]]; then
  "$ROOT_DIR/scripts/post_build_checksums.sh" "$DIST_DIR/centi-noctics" "$DIST_DIR/centi-noctics.SHA256SUMS" || true
  install -Dm644 "$ROOT_DIR/THIRD_PARTY_LICENSES.md" "$DIST_DIR/centi-noctics/licenses/THIRD_PARTY_LICENSES.md"
fi

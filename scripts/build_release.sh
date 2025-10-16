#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SPEC_FILE="$ROOT_DIR/release/noctics_release.spec"
DIST_DIR="$ROOT_DIR/dist"
BUILD_DIR="$ROOT_DIR/.pyi-build"
MODEL_PATH="${MODEL_PATH:-}"
DEFAULT_MODEL_NAME="centi-nox"
PREPARE_ASSETS_SCRIPT="$ROOT_DIR/scripts/prepare_assets.sh"
MODEL_POINTER_FILE="$ROOT_DIR/assets/ollama/models/.active_model"

if [[ -z "$MODEL_PATH" ]]; then
  MODEL_PATH="${1:-}"
fi

if [[ -z "$MODEL_PATH" ]]; then
  TARGET_MODEL_NAME="${MODEL_NAME_OVERRIDE:-$DEFAULT_MODEL_NAME}"
  if [[ "${NOCTICS_SKIP_ASSET_PREP:-0}" != "1" ]]; then
    if [[ -f "$MODEL_POINTER_FILE" && -d "$ROOT_DIR/assets/ollama/models/blobs" ]]; then
      echo "[build_release] Reusing existing model assets under assets/ollama/models" >&2
    else
      if [[ ! -x "$PREPARE_ASSETS_SCRIPT" ]]; then
        echo "[build_release] Asset prep script missing: $PREPARE_ASSETS_SCRIPT" >&2
        exit 1
      fi
      MODEL_NAME="$TARGET_MODEL_NAME" "$PREPARE_ASSETS_SCRIPT"
    fi
  fi

  if [[ -z "$MODEL_PATH" && -f "$MODEL_POINTER_FILE" ]]; then
    MODEL_PATH="$(<"$MODEL_POINTER_FILE")"
  elif [[ -z "$MODEL_PATH" ]]; then
    echo "[build_release] Unable to determine model path; run prepare_assets first" >&2
    exit 1
  fi

  if [[ "${MODEL_PATH:0:1}" != "/" ]]; then
    MODEL_PATH="$ROOT_DIR/$MODEL_PATH"
  fi
fi

if [[ ! -f "$MODEL_PATH" ]]; then
  echo "[build_release] MODEL_PATH does not exist: $MODEL_PATH" >&2
  exit 1
fi

if ! command -v pyinstaller >/dev/null 2>&1; then
  echo "[build_release] pyinstaller not found on PATH" >&2
  exit 1
fi

mkdir -p "$DIST_DIR" "$BUILD_DIR"

MODEL_FILENAME="$(basename "$MODEL_PATH")"

NOCTICS_MODEL_PATH="$(cd "$(dirname "$MODEL_PATH")" && pwd)/$MODEL_FILENAME"

NOCTICS_MODEL_PATH="$NOCTICS_MODEL_PATH" \
NOCTICS_MODEL_NAME="$MODEL_FILENAME" \
NOCTICS_ROOT="$ROOT_DIR" \
pyinstaller "$SPEC_FILE" \
  --distpath "$DIST_DIR" \
  --workpath "$BUILD_DIR" \
  --clean

echo "[build_release] Build artifacts available under $DIST_DIR" >&2

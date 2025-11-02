#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SPEC_FILE="$ROOT_DIR/release/noctics_release.spec"
DIST_DIR="$ROOT_DIR/dist"
BUILD_DIR="$ROOT_DIR/.pyi-build"
MODEL_PATH="${MODEL_PATH:-}"
DEFAULT_MODEL_NAME="centi-nox"
TARGET_MODEL_NAME="${MODEL_NAME_OVERRIDE:-$DEFAULT_MODEL_NAME}"
PREPARE_ASSETS_SCRIPT="$ROOT_DIR/scripts/prepare_assets.sh"
MODEL_POINTER_FILE="$ROOT_DIR/assets/ollama/models/.active_model"
FALLBACK_FILE="$ROOT_DIR/assets/runtime/fallback_remote_url.txt"

if [[ -z "${NOCTICS_INSTALLER_VERSION:-}" ]]; then
  if command -v python3 >/dev/null 2>&1; then
    NOCTICS_INSTALLER_VERSION="$(PYTHONPATH="$ROOT_DIR:$ROOT_DIR/core" python3 - <<'PY'
try:
    from central.version import __version__
except Exception:
    __version__ = ""
print(__version__, end="")
PY
)"
    NOCTICS_INSTALLER_VERSION="${NOCTICS_INSTALLER_VERSION//$'\n'/}"
  else
    NOCTICS_INSTALLER_VERSION=""
  fi
fi

if [[ -z "${NOCTICS_INSTALLER_BUILD:-}" ]]; then
  if command -v git >/dev/null 2>&1; then
    NOCTICS_INSTALLER_BUILD="$(git -C "$ROOT_DIR" rev-parse --short HEAD 2>/dev/null || true)"
    NOCTICS_INSTALLER_BUILD="${NOCTICS_INSTALLER_BUILD//$'\n'/}"
  else
    NOCTICS_INSTALLER_BUILD=""
  fi
fi

if [[ -z "$MODEL_PATH" ]]; then
  MODEL_PATH="${1:-}"
fi

if [[ -z "$MODEL_PATH" ]]; then
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
rm -rf "$DIST_DIR/noctics-core"

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
  --clean

echo "[build_release] Build artifacts available under $DIST_DIR" >&2

if [[ -d "$DIST_DIR/noctics-core" ]]; then
  ALIAS_FILE="$DIST_DIR/noctics-core/_internal/resources/runtime/primary_alias.txt"
  if [[ -f "$ALIAS_FILE" ]]; then
    printf '%s\n' "$TARGET_MODEL_NAME" > "$ALIAS_FILE"
  fi
  "$ROOT_DIR/scripts/post_build_checksums.sh" "$DIST_DIR/noctics-core" "$DIST_DIR/noctics-core.SHA256SUMS" || true
  install -Dm644 "$ROOT_DIR/THIRD_PARTY_LICENSES.md" "$DIST_DIR/noctics-core/licenses/THIRD_PARTY_LICENSES.md"

  if [[ "${NOCTICS_SKIP_INSTALLER_PACKAGING:-0}" != "1" ]]; then
    PACKAGER="$ROOT_DIR/scripts/package_installer_artifacts.py"
    if [[ -f "$PACKAGER" ]]; then
      MANIFEST_PATH="${NOCTICS_INSTALLER_MANIFEST:-$DIST_DIR/installer_manifest.json}"
      ARCHIVE_PREFIX="${NOCTICS_INSTALLER_ARCHIVE_PREFIX:-noctics-core}"
      PACKAGER_ARGS=(--dist-dir "$DIST_DIR/noctics-core" --output-dir "$DIST_DIR" --archive-prefix "$ARCHIVE_PREFIX" --manifest "$MANIFEST_PATH")
      if [[ -n "${NOCTICS_INSTALLER_URL_PREFIX:-}" ]]; then
        PACKAGER_ARGS+=(--url-prefix "$NOCTICS_INSTALLER_URL_PREFIX")
      fi
      if [[ -n "${NOCTICS_INSTALLER_SLUG:-}" ]]; then
        PACKAGER_ARGS+=(--slug "$NOCTICS_INSTALLER_SLUG")
      fi
      if [[ -n "${NOCTICS_INSTALLER_OS:-}" ]]; then
        PACKAGER_ARGS+=(--os-name "$NOCTICS_INSTALLER_OS")
      fi
      if [[ -n "${NOCTICS_INSTALLER_ARCH:-}" ]]; then
        PACKAGER_ARGS+=(--arch "$NOCTICS_INSTALLER_ARCH")
      fi
      if [[ -n "${NOCTICS_INSTALLER_ARTIFACT_URL:-}" ]]; then
        PACKAGER_ARGS+=(--artifact-url "$NOCTICS_INSTALLER_ARTIFACT_URL")
      fi
      if [[ -n "${NOCTICS_INSTALLER_README_TEMPLATE:-}" ]]; then
        PACKAGER_ARGS+=(--readme-template "$NOCTICS_INSTALLER_README_TEMPLATE")
      fi
      if [[ -n "${NOCTICS_INSTALLER_VERSION:-}" ]]; then
        PACKAGER_ARGS+=(--version "$NOCTICS_INSTALLER_VERSION")
      fi
      if [[ -n "${NOCTICS_INSTALLER_BUILD:-}" ]]; then
        PACKAGER_ARGS+=(--build "$NOCTICS_INSTALLER_BUILD")
      fi
      python3 "$PACKAGER" "${PACKAGER_ARGS[@]}"
    else
      echo "[build_release] Installer packaging helper missing: $PACKAGER" >&2
    fi
  fi
fi

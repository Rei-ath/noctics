#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 1 ]]; then
  echo "Usage: $0 <dist-dir> [output-file]" >&2
  exit 1
fi

TARGET_DIR="$1"
OUTPUT_FILE="${2:-$1/SHA256SUMS}"

if [[ ! -d "$TARGET_DIR" ]]; then
  echo "[post_build_checksums] target directory missing: $TARGET_DIR" >&2
  exit 1
fi

if ! command -v sha256sum >/dev/null 2>&1; then
  echo "[post_build_checksums] sha256sum not available on PATH" >&2
  exit 1
fi

tmpfile="${OUTPUT_FILE}.tmp"
find "$TARGET_DIR" -type f -print0 | sort -z | xargs -0 sha256sum >"$tmpfile"
mv "$tmpfile" "$OUTPUT_FILE"

echo "[post_build_checksums] wrote $OUTPUT_FILE" >&2

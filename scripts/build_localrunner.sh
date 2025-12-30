#!/usr/bin/env bash
set -euo pipefail

# Build the Go-based local runner into bin/noxlocal (global binary).

ROOT="$(cd -- "$(dirname "$0")/.." && pwd)"
SRC="$ROOT/noxpy/localrunner"
OUT="$ROOT/bin/noxlocal"

if [ ! -d "$SRC" ]; then
  echo "local runner source not found at $SRC" >&2
  exit 1
fi

# Termux-friendly default compilers; override via CC/CXX if needed.
if [ -z "${CC:-}" ]; then
  if [ -x "/data/data/com.termux/files/usr/bin/clang" ]; then
    export CC="/data/data/com.termux/files/usr/bin/clang"
    export CXX="/data/data/com.termux/files/usr/bin/clang++"
  elif [ -x "/data/data/com.termux/files/usr/bin/aarch64-linux-android-clang" ]; then
    export CC="/data/data/com.termux/files/usr/bin/aarch64-linux-android-clang"
    export CXX="/data/data/com.termux/files/usr/bin/aarch64-linux-android-clang++"
  fi
fi

export CGO_ENABLED=1
export GO111MODULE=on
export GOFLAGS="-buildvcs=false"

echo "Building noxlocal -> $OUT"
(cd "$SRC" && go build -o "$OUT" ./...)
echo "Done. Binary size: $(du -h "$OUT" | cut -f1)"

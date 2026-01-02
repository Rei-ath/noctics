#!/usr/bin/env bash
set -euo pipefail

# Build the Go-based local runner into bin/noxlocal (global binary).

ROOT="$(cd -- "$(dirname "$0")/.." && pwd)"
SRC="$ROOT/noxpy/localrunner"
OUT="$ROOT/bin/noxlocal"
USE_DOTPROD=0
USE_REPACK=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --dp|--dotprod)
      USE_DOTPROD=1
      OUT="$ROOT/bin/noxlocal_dp"
      shift
      ;;
    --repack)
      USE_REPACK=1
      shift
      ;;
    --out)
      OUT="$2"
      shift 2
      ;;
    *)
      echo "unknown arg: $1" >&2
      echo "usage: $0 [--dp|--dotprod] [--repack] [--out PATH]" >&2
      exit 1
      ;;
  esac
done

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
CGO_CFLAGS="${CGO_CFLAGS:-"-O3 -DNDEBUG"}"
CGO_CXXFLAGS="${CGO_CXXFLAGS:-"-O3 -DNDEBUG"}"
CGO_CPPFLAGS="${CGO_CPPFLAGS:-""}"

if [[ $USE_DOTPROD -eq 1 ]]; then
  CGO_CFLAGS+=" -march=armv8.2-a+dotprod"
  CGO_CXXFLAGS+=" -march=armv8.2-a+dotprod"
  CGO_CPPFLAGS+=" -DGGML_USE_DOTPROD"
fi

if [[ $USE_REPACK -eq 1 ]]; then
  CGO_CPPFLAGS+=" -DGGML_USE_CPU_REPACK"
fi

export CGO_CFLAGS
export CGO_CXXFLAGS
export CGO_CPPFLAGS

echo "Building noxlocal -> $OUT"
(cd "$SRC" && go build -o "$OUT" ./...)
echo "Done. Binary size: $(du -h "$OUT" | cut -f1)"

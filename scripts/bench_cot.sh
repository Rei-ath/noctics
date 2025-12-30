#!/usr/bin/env sh
set -eu

ROOT="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"

BIN="$ROOT/bin/noxlocal_dp"
if [ ! -x "$BIN" ]; then BIN="$ROOT/noxpy/localrunner/noxlocal_dp"; fi
if [ ! -x "$BIN" ]; then BIN="$ROOT/bin/noxlocal"; fi
if [ ! -x "$BIN" ]; then BIN="$ROOT/noxpy/localrunner/noxlocal"; fi

MODEL="$ROOT/nox/obb/nox.gguf"
THREADS="${NOX_NUM_THREADS:-4}"
CTX="${NOX_CTX:-256}"
BATCH="${NOX_BATCH:-32}"
MAX_TOKENS="${NOX_MAX_TOKENS:-128}"

PROMPT="${1:-Solve: What is 23*17?}"

run() {
  label="$1"
  shift
  echo "== $label ==" >&2
  i=1
  while [ "$i" -le 3 ]; do
    NOX_NUM_THREADS="$THREADS" \
      "$BIN" \
      -model "$MODEL" \
      -ctx "$CTX" \
      -batch "$BATCH" \
      -max-tokens "$MAX_TOKENS" \
      -raw \
      -fast \
      -bench \
      "$@" \
      "$PROMPT" 2>&1 | sed -n 's/.*\(bench:.*\)/\1/p'
    i=$((i + 1))
  done
}

run "plain"
run "chat" "-chat"
run "chat+cot" "-chat" "-cot"

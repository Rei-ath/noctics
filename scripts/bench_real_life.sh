#!/usr/bin/env sh
set -eu

ROOT="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"

SMALL_MODEL="${SMALL_MODEL:-$ROOT/nox/obb/nox.gguf}"
LARGE_MODEL="${LARGE_MODEL:-$ROOT/nox/obb/mistral-7b-q4.gguf}"

echo "== nox (0.5B) / chat / ctx=256 ==" >&2
python3 "$ROOT/scripts/bench_real.py" \
  --model "$SMALL_MODEL" \
  --mode chat \
  --suite full \
  --threads 4 \
  --ctx 256 \
  --runs 2 \
  --max-tokens 128 \
  --min-gen-tokens 16

echo "" >&2
echo "== nox (0.5B) / chat+cot / ctx=1024 ==" >&2
python3 "$ROOT/scripts/bench_real.py" \
  --model "$SMALL_MODEL" \
  --mode cot \
  --suite full \
  --threads 4 \
  --ctx 1024 \
  --runs 1 \
  --max-tokens 128 \
  --min-gen-tokens 16

echo "" >&2
echo "== mistral (7B) / plain / ctx=256 (slow: expect ~10-15 min) ==" >&2
python3 "$ROOT/scripts/bench_real.py" \
  --model "$LARGE_MODEL" \
  --mode plain \
  --suite short \
  --threads 2 \
  --ctx 256 \
  --runs 1 \
  --max-tokens 16 \
  --min-gen-tokens 4


#!/usr/bin/env bash
set -euo pipefail

ROOT="$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)"

mkdir -p "$ROOT/data/neuroutine"

if [[ ! -f "$ROOT/data/prompts.txt" ]]; then
  cat > "$ROOT/data/prompts.txt" <<'EOF'
Explain why the sky is blue in one sentence.
Write a short haiku about rain.
Summarize: Mobile inference is slow.
Give one tip for faster local LLM inference.
EOF
fi

SMALL_MODEL="${NOX_NEURO_SMALL_MODEL:-$ROOT/assets/models/tinyllama.gguf}"
if [[ ! -f "$SMALL_MODEL" ]]; then
  SMALL_MODEL="$ROOT/assets/models/nox.gguf"
fi

PYTHONUNBUFFERED=1 python3 "$ROOT/experiments/neuroutine/neuroutine_loop.py" \
  --prompts "$ROOT/data/prompts.txt" \
  --steps 2 \
  --ctx 256 \
  --batch 8 \
  --model-small "$SMALL_MODEL" \
  --model-large "$ROOT/assets/models/mistral-7b-q4.gguf" \
  --weights "$ROOT/data/neuroutine/live_weights.json" \
  --accept-prob 0.5 \
  --no-mirror \
  --teacher-every 16 \
  --teacher-prob 0.05 \
  --bootstrap-positives 8 \
  --min-samples 16 \
  --retrain-every 16 \
  --window-size 128 \
  --report-every 8 \
  --accuracy-window 32 | tee "$ROOT/data/neuroutine/loop.log"

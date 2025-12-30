# Experiments (opt-in)

Everything under `experiments/` is **not** part of the production `noctics` CLI runtime.

Guidelines:
- Experiments must be runnable directly (no hidden imports from production entrypoints).
- Experiments must never be enabled by default in `main.py` or `noctics_cli/`.
- If an experiment proves valuable, it graduates into `scripts/` (tooling) or into the
  production runtime with an explicit flag + tests.

Current buckets:
- `experiments/neuroutine/` — small controller + fallback experiments.
- `experiments/spec_decode/` — speculative decode / switching prototypes.
- `experiments/noxrs/` — Rust process runner prototype.
- `experiments/engine/` — Rust orchestrator scaffold.
- `experiments/zig-infer/` — Zig inference scaffold.

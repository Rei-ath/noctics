# `noxrs` (Rust stdin/stdout runner)

Minimal, dependency-free Rust binary that replaces the Python CLI for pure
process-based operation. It reads prompts from stdin or argv, spawns the local
runner (`bin/noxlocal` or `noxpy/localrunner/noxlocal`), and streams stdout
back immediately (stdin/stdout only, no HTTP).

Run:
```bash
cd experiments/noxrs
cargo run -- "hello world"               # prompt via argv
echo "hi" | cargo run                    # prompt via stdin
```

Environment knobs:
- `NOX_LOCAL_RUNNER` — path to runner binary (defaults depend on runner style)
- `NOX_RUNNER_STYLE` — `noxlocal` (default), `llama` (llama-completion), or `llama-simple`
- `NOX_MODEL_PATH` — model gguf path (defaults to `assets/models/mistral-7b-q4.gguf` then `assets/models/nox.gguf` if present)
- `NOX_CTX`, `NOX_MAX_TOKENS`, `NOX_BATCH`, `NOX_TEMP`, `NOX_TOP_P`, `NOX_TOP_K`, `NOX_NUM_THREADS`
- `NOX_RAW=1` — pass `-raw` to suppress prefixes from the runner
- `NOX_DEVICE` — llama-completion device selector (e.g. `none`, `gpu0`, `gpu0,gpu1`)
- `NOX_GPU_LAYERS` — llama-completion `-ngl` override for GPU offload
- `NOX_NO_WARMUP=1` or `NOX_WARMUP=1` — control llama-completion warmup (default: off for stability)
- `NOX_EMULATE_A1000=1` — simulate fast streaming (no model call); see simulation env vars below
- `NOX_CHIP_EMU=1` — functional chip emulation (forces contract defaults and CPU reference runner)
- `NOX_PREPACK=1` — enable model prepack in the `noxlocal` runner (mlock weights if supported)
For Vulkan on Android, set `VK_ICD_FILENAMES` to a valid ICD JSON (see `temp/vulkan.adreno.json` if present).

Contract defaults (unless env overrides): `ctx=1024`, `batch=1`, `max_tokens=128`, `temp=0`, `top_p=1`, `top_k=1`. See `CONTRACT.md`.

Simulation env vars (used when `NOX_EMULATE_A1000=1`):
- `NOX_SIM_TTFT_MS` — time to first token in ms (default 150)
- `NOX_SIM_TOKENS_PER_SEC` — streaming rate (default 80)
- `NOX_SIM_TEXT` — override the emitted response text

Runner defaults:
- `noxlocal`: `bin/noxlocal` or `noxpy/localrunner/noxlocal`
- `llama-completion`: `bin/llama-completion` or `temp/llama.cpp/build/bin/llama-completion`
- `llama-simple`: `bin/llama-simple` or `temp/llama.cpp/build/bin/llama-simple`

Note: `llama-simple` ignores most tuning flags (ctx/temp/top-p/top-k/threads) because its CLI is minimal. Use it as a stable CPU fallback if `llama-completion` crashes.

This binary simply forwards flags/env to the runner and pipes stdout through. Swap the runner to the Zig backend once it is ready; no HTTP involved.

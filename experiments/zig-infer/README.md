# `experiments/zig-infer/` (Zig inference runner)

Target: a dependency-light GGUF runner compiled with Zig, exposing stdin/stdout
streaming (no HTTP). The runner should:
- read prompts from stdin (JSON or framed text)
- load `assets/models/nox.gguf`
- stream tokens to stdout as soon as they are sampled
- support cancellation via SIGINT/SIGTERM or a control pipe

Binary name: `noxinf`.

Current state: stub that prints a placeholder. Replace `src/main.zig` with the
real loader/sampler and wire ARM64/NEON kernels or imported llama.cpp symbols
as needed. Build with `zig build -Drelease-fast` (see `build.zig`).

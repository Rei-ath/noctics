# Architecture pivot

We are moving from a Python+HTTP runtime to a process-first stack:

- **Legacy**: `noxpy/` remains runnable (`cd noxpy && python main.py`) with HTTP
  bindings and an optional process runner (`bin/noxlocal`). It stays locked at
  version `0.1.39`.
- **Orchestrator (Rust)**: `experiments/engine/` will manage runner processes, framing over
  stdin/stdout, and expose a small FFI for callers (Python bindings or optional
  HTTP wrapper).
- **Rust runner**: `experiments/noxrs/` is the first pure-stdin/stdout binary, dependency-free,
  intended to supersede `noxpy` while the Zig backend is wired in.
- **Inference (Zig)**: `experiments/zig-infer/` will host a tiny GGUF runner that streams
  tokens directly (no server). Use ARM64/NEON kernels and keep it dependency-light.
- **Models**: only `assets/models/nox.gguf` is kept in-repo.
- **Binaries**: place built artifacts (Go transition runner, Zig runner) in
  `bin/` so both legacy and new stacks can find them.

### Why process-based?
- No HTTP overhead; prompts/tokens flow over stdin/stdout pipes.
- Fewer dependencies and easier embedding (APK/Termux/wasm-friendly).
- Tighter resource control: parent can set CPU affinity/ionice/rlimits.
- Faster startup than the Go server model; smaller binaries via Zig.

### Transition steps
1. Keep `noxpy` stable for existing users; default to `bin/noxlocal` if present.
2. Build out `zig-infer` runner (GGUF load, sampling, cancellation).
3. Wire `engine` to spawn the Zig runner, stream tokens, and expose FFI.
4. Add optional HTTP wrapper only as a thin add-on.
5. Retire the Go runner once Zig is proven.

### Building artifacts (current state)
- Go transition runner: `scripts/build_localrunner.sh` -> `bin/noxlocal`
- Zig stub: `cd experiments/zig-infer && zig build -Drelease-fast` (stub only)
- Rust scaffold: `cd experiments/engine && cargo build` (no dependencies yet)

Device note: target ARM64 first (Termux-friendly); prefer NEON kernels and avoid
heavy external deps. Use static builds where possible.

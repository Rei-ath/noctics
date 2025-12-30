# `experiments/engine/` (Rust orchestrator)

Goal: replace the Python/HTTP control plane with a process-first Rust layer that
spawns Zig-based inference binaries, streams tokens over stdin/stdout, and
exposes a thin FFI for Python (and optional HTTP only as a wrapper).

What lives here:
- `src/lib.rs` – core orchestrator, process lifecycle, framing, cancellation
- `src/bin/nox-engine.rs` – CLI/daemon entry when needed (disabled by default)
- `Cargo.toml` – kept dependency-light; prefer std + explicit FFI bindings

Current state: scaffolding only. Wire this to the Zig runner in `../zig-infer`
and expose a C ABI or `pyo3` facade for `noxpy` interop once the runner is ready.

# Legacy Python runtime (`noxpy`)

- Version pinned at `0.1.39`; treat this tree as read-only except for critical fixes.  
- Run via `cd noxpy && python main.py ...` (no installer/bootstrap expected).  
- Runtime prefers a local process runner (`bin/noxlocal` or `$NOX_LOCAL_RUNNER`) and falls back to HTTP only when no runner is found.  
- Models: only `assets/models/nox.gguf` is supported here; keep the repo clean of other weights.  
- Future work lives in `../experiments/engine` (Rust orchestrator) and `../experiments/zig-infer` (Zig inference). Add HTTP bindings only as a thin opt-in wrapper.  
- To refresh the Go runner binary, build it into `../bin/noxlocal` using `scripts/build_localrunner.sh`.  

This folder preserves compatibility for existing Python users while the process-first Rust/Zig stack matures under `../experiments/`.

//! Optional binary entrypoint for the Rust orchestrator.

use nox_engine::{spawn_inference, EngineConfig};

fn main() {
    let cfg = EngineConfig::default();
    let _ = spawn_inference("ping", &cfg);
    println!("nox-engine scaffold (process-based, no HTTP)");
}

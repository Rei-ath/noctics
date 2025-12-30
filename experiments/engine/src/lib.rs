//! Process-first orchestrator for Nox.
//!
//! This crate is intended to manage inference processes (Zig runner by default),
//! handle framing over stdin/stdout, and surface a safe API/FFI boundary for
//! callers in Python or other hosts. Keep dependencies minimal and avoid any
//! background servers—everything should be a short-lived process pipeline.

use std::path::PathBuf;

/// Basic configuration passed to a runner invocation.
#[derive(Debug, Clone)]
pub struct EngineConfig {
    pub model: PathBuf,
    pub runner_bin: PathBuf,
    pub max_tokens: usize,
    pub ctx: usize,
    pub threads: Option<usize>,
}

impl Default for EngineConfig {
    fn default() -> Self {
        Self {
            model: PathBuf::from("assets/models/nox.gguf"),
            runner_bin: PathBuf::from("bin/noxinf"),
            max_tokens: 256,
            ctx: 1024,
            threads: None,
        }
    }
}

/// Placeholder API for spawning a process-based inference run.
pub fn spawn_inference(_prompt: &str, _cfg: &EngineConfig) -> std::io::Result<()> {
    // TODO: implement stdin/stdout framing and streaming token callbacks once the
    // Zig runner is ready. Keep this function synchronous and cheap to start.
    Ok(())
}

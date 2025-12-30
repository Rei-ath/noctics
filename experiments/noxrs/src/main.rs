//! Minimal process-based Nox runner that spawns a local inference binary
//! (stdin/stdout only, no HTTP). It forwards the prompt to the runner and
//! streams stdout back immediately.

use std::collections::HashSet;
use std::env;
use std::fs;
use std::io::{self, Read, Write};
use std::path::{Path, PathBuf};
use std::process::{Command, Stdio};
use std::thread;
use std::time::Duration;

mod neuroute;
mod routing_weights;

const DEFAULT_CTX: u32 = 1024;
const DEFAULT_BATCH: u32 = 1;
const DEFAULT_MAX_TOKENS: u32 = 128;
const DEFAULT_TEMP: f32 = 0.0;
const DEFAULT_TOP_P: f32 = 1.0;
const DEFAULT_TOP_K: u32 = 1;
const DEFAULT_TTFT_MS: u64 = 150;
const DEFAULT_TPS: f32 = 80.0;

fn main() -> io::Result<()> {
    let cfg = Config::from_env();
    if cfg.persist {
        return run_persistent(&cfg);
    }
    let mut prompt = read_prompt()?;
    if prompt.trim().is_empty() {
        eprintln!("nox: empty prompt");
        return Ok(());
    }
    if cfg.route_enabled {
        if let Some(routed) = route_prompt(&cfg, &prompt) {
            prompt = routed;
        }
    }
    if cfg.emulate_a1000 {
        return simulate_stream(&cfg, &prompt);
    }

    let runner = cfg
        .resolve_runner()
        .ok_or_else(|| io::Error::new(io::ErrorKind::NotFound, "no runner binary found"))?;

    let mut cmd = Command::new(&runner);
    cmd.stdout(Stdio::piped()).stderr(Stdio::inherit());

    match cfg.runner_style {
        RunnerStyle::NoxLocal => {
            if cfg.raw {
                cmd.arg("-raw");
            }
            if cfg.prepack {
                cmd.arg("-prepack");
            }
            cmd.args(["-ctx", &cfg.ctx.to_string()]);
            cmd.args(["-max-tokens", &cfg.max_tokens.to_string()]);
            cmd.args(["-batch", &cfg.batch.to_string()]);
            cmd.args(["-temp", &cfg.temp.to_string()]);
            cmd.args(["-top-p", &cfg.top_p.to_string()]);
            cmd.args(["-top-k", &cfg.top_k.to_string()]);
            if let Some(model) = cfg.model_path() {
                cmd.args(["-model", &model]);
            }
            if let Some(threads) = cfg.threads {
                cmd.env("NOX_NUM_THREADS", threads.to_string());
            }
            if cfg.fast {
                cmd.arg("-fast");
            }
            if let Some(state_load) = &cfg.state_load {
                cmd.arg("-state-load");
                cmd.arg(state_load);
            }
            if let Some(state_save) = &cfg.state_save {
                cmd.arg("-state-save");
                cmd.arg(state_save);
            }
            cmd.arg(prompt);
        }
        RunnerStyle::LlamaCompletion => {
            cmd.arg("--simple-io");
            cmd.arg("--no-display-prompt");
            if cfg.no_warmup {
                cmd.arg("--no-warmup");
            }
            if let Some(model) = cfg.model_path() {
                cmd.args(["-m", &model]);
            }
            if let Some(device) = &cfg.device {
                cmd.args(["--device", device]);
            }
            if let Some(ngl) = cfg.gpu_layers {
                cmd.args(["-ngl", &ngl.to_string()]);
            }
            cmd.args(["-c", &cfg.ctx.to_string()]);
            cmd.args(["-n", &cfg.max_tokens.to_string()]);
            cmd.args(["-b", &cfg.batch.to_string()]);
            cmd.args(["--temp", &cfg.temp.to_string()]);
            cmd.args(["--top-p", &cfg.top_p.to_string()]);
            cmd.args(["--top-k", &cfg.top_k.to_string()]);
            if let Some(threads) = cfg.threads {
                cmd.args(["-t", &threads.to_string()]);
            }
            cmd.args(["-p", &prompt]);
        }
        RunnerStyle::LlamaSimple => {
            if let Some(model) = cfg.model_path() {
                cmd.args(["-m", &model]);
            }
            cmd.args(["-n", &cfg.max_tokens.to_string()]);
            if let Some(ngl) = cfg.gpu_layers {
                cmd.args(["-ngl", &ngl.to_string()]);
            }
            cmd.arg(prompt);
        }
    }

    let mut child = cmd.spawn()?;
    let mut stdout = child
        .stdout
        .take()
        .ok_or_else(|| io::Error::new(io::ErrorKind::Other, "failed to open child stdout"))?;

    let mut buf = [0u8; 4096];
    let mut out = io::stdout();
    loop {
        let n = stdout.read(&mut buf)?;
        if n == 0 {
            break;
        }
        out.write_all(&buf[..n])?;
        out.flush()?;
    }

    let status = child.wait()?;
    if !status.success() {
        return Err(io::Error::new(
            io::ErrorKind::Other,
            format!("runner exited with status {status}"),
        ));
    }
    Ok(())
}

#[derive(Debug, Clone)]
struct Config {
    runner_override: Option<PathBuf>,
    model_override: Option<PathBuf>,
    runner_style: RunnerStyle,
    device: Option<String>,
    gpu_layers: Option<i32>,
    ctx: u32,
    max_tokens: u32,
    batch: u32,
    temp: f32,
    top_p: f32,
    top_k: u32,
    threads: Option<u32>,
    raw: bool,
    fast: bool,
    no_warmup: bool,
    emulate_a1000: bool,
    sim_ttft_ms: u64,
    sim_tps: f32,
    sim_text: Option<String>,
    prepack: bool,
    route_enabled: bool,
    route_query: Option<String>,
    route_delim: String,
    route_keep: usize,
    route_debug: bool,
    persist: bool,
    persist_rs: bool,
    keep_cache: bool,
    append_only: bool,
    input_only: bool,
    state_save: Option<PathBuf>,
    state_load: Option<PathBuf>,
}

impl Config {
    fn from_env() -> Self {
        let chip_emu = env_bool("NOX_CHIP_EMU")
            .or_else(|| env_bool("NOX_EMULATE_CHIP"))
            .unwrap_or(false);
        let runner_style = if chip_emu {
            RunnerStyle::NoxLocal
        } else {
            RunnerStyle::from_env()
        };
        let warmup = env_bool("NOX_WARMUP");
        let no_warmup = env_bool("NOX_NO_WARMUP");
        let route_query = env::var("NOX_ROUTE_QUERY")
            .ok()
            .and_then(|v| if v.trim().is_empty() { None } else { Some(v) });
        let route_enabled = env_bool("NOX_ROUTE").unwrap_or(false) || route_query.is_some();

        Self {
            runner_override: env::var_os("NOX_LOCAL_RUNNER").map(PathBuf::from),
            model_override: env::var_os("NOX_MODEL_PATH").map(PathBuf::from),
            runner_style,
            device: env::var("NOX_DEVICE")
                .ok()
                .and_then(|v| {
                    let v = v.trim();
                    if v.is_empty() || v.eq_ignore_ascii_case("auto") {
                        None
                    } else {
                        Some(v.to_string())
                    }
                }),
            gpu_layers: env_i32("NOX_GPU_LAYERS").or_else(|| env_i32("NOX_N_GPU_LAYERS")),
            ctx: if chip_emu {
                DEFAULT_CTX
            } else {
                env_u32("NOX_CTX")
                    .or_else(|| env_u32("NOX_NUM_CTX"))
                    .unwrap_or(DEFAULT_CTX)
            },
            max_tokens: if chip_emu {
                DEFAULT_MAX_TOKENS
            } else {
                env_u32("NOX_MAX_TOKENS").unwrap_or(DEFAULT_MAX_TOKENS)
            },
            batch: if chip_emu {
                DEFAULT_BATCH
            } else {
                env_u32("NOX_BATCH").unwrap_or(DEFAULT_BATCH)
            },
            temp: if chip_emu {
                DEFAULT_TEMP
            } else {
                env_f32("NOX_TEMP").unwrap_or(DEFAULT_TEMP)
            },
            top_p: if chip_emu {
                DEFAULT_TOP_P
            } else {
                env_f32("NOX_TOP_P").unwrap_or(DEFAULT_TOP_P)
            },
            top_k: if chip_emu {
                DEFAULT_TOP_K
            } else {
                env_u32("NOX_TOP_K").unwrap_or(DEFAULT_TOP_K)
            },
            threads: env_u32("NOX_NUM_THREADS"),
            raw: env::var("NOX_RAW").map(|v| v == "1" || v.eq_ignore_ascii_case("true")).unwrap_or(false),
            fast: env_bool("NOX_FAST").unwrap_or(false),
            no_warmup: no_warmup.unwrap_or_else(|| {
                if let Some(true) = warmup {
                    false
                } else {
                    matches!(runner_style, RunnerStyle::LlamaCompletion)
                }
            }),
            emulate_a1000: if chip_emu {
                false
            } else {
                env_bool("NOX_EMULATE_A1000")
                    .or_else(|| env_bool("NOX_SIMULATE"))
                    .or_else(|| env_bool("NOX_SIM_MODE"))
                    .unwrap_or(false)
            },
            sim_ttft_ms: env_u64("NOX_SIM_TTFT_MS")
                .or_else(|| env_u64("NOX_SIM_TTFT"))
                .unwrap_or(DEFAULT_TTFT_MS),
            sim_tps: env_f32("NOX_SIM_TOKENS_PER_SEC")
                .or_else(|| env_f32("NOX_SIM_TPS"))
                .unwrap_or(DEFAULT_TPS),
            sim_text: env::var("NOX_SIM_TEXT")
                .ok()
                .and_then(|v| if v.trim().is_empty() { None } else { Some(v) }),
            prepack: env_bool("NOX_PREPACK")
                .or_else(|| env_bool("NOX_MLOCK"))
                .unwrap_or(false),
            route_enabled,
            route_query,
            route_delim: env::var("NOX_ROUTE_DELIM").unwrap_or_else(|_| "---".to_string()),
            route_keep: env_u32("NOX_ROUTE_KEEP").unwrap_or(4) as usize,
            route_debug: env_bool("NOX_ROUTE_DEBUG").unwrap_or(false),
            persist: env_bool("NOX_PERSIST")
                .or_else(|| env_bool("NOX_DAEMON"))
                .or_else(|| env_bool("NOX_REPL"))
                .unwrap_or(false),
            persist_rs: env_bool("NOX_PERSIST_RS").unwrap_or(false),
            keep_cache: env_bool("NOX_KEEP_CACHE").unwrap_or(false),
            append_only: env_bool("NOX_APPEND").unwrap_or(false),
            input_only: env_bool("NOX_INPUT_ONLY").unwrap_or(false),
            state_save: env_path("NOX_STATE_SAVE"),
            state_load: env_path("NOX_STATE_LOAD"),
        }
    }

    fn resolve_runner(&self) -> Option<PathBuf> {
        if let Some(p) = &self.runner_override {
            if is_executable(p) {
                return Some(p.clone());
            }
        }
        let candidates: &[PathBuf] = match self.runner_style {
            RunnerStyle::NoxLocal => &[
                PathBuf::from("bin/noxlocal"),
                PathBuf::from("noxpy/localrunner/noxlocal"),
                PathBuf::from("../noxpy/localrunner/noxlocal"),
            ],
            RunnerStyle::LlamaCompletion => &[
                PathBuf::from("bin/llama-completion"),
                PathBuf::from("temp/llama.cpp/build/bin/llama-completion"),
                PathBuf::from("../temp/llama.cpp/build/bin/llama-completion"),
            ],
            RunnerStyle::LlamaSimple => &[
                PathBuf::from("bin/llama-simple"),
                PathBuf::from("temp/llama.cpp/build/bin/llama-simple"),
                PathBuf::from("../temp/llama.cpp/build/bin/llama-simple"),
            ],
        };
        for candidate in candidates {
            if is_executable(candidate) {
                return Some(candidate.clone());
            }
        }
        None
    }

    fn model_path(&self) -> Option<String> {
        if let Some(p) = &self.model_override {
            if p.exists() {
                return Some(p.to_string_lossy().into_owned());
            }
        }
        for candidate in [
            "assets/models/mistral-7b-q4.gguf",
            "assets/models/nox.gguf",
            "../assets/models/mistral-7b-q4.gguf",
            "../assets/models/nox.gguf",
        ] {
            let p = Path::new(candidate);
            if p.exists() {
                return Some(p.to_string_lossy().into_owned());
            }
        }
        None
    }
}

#[derive(Debug, Clone, Copy)]
enum RunnerStyle {
    NoxLocal,
    LlamaCompletion,
    LlamaSimple,
}

impl RunnerStyle {
    fn from_env() -> Self {
        let style = env::var("NOX_RUNNER_STYLE").unwrap_or_else(|_| "noxlocal".to_string());
        let value = style.trim().to_ascii_lowercase();
        if value.contains("simple") {
            RunnerStyle::LlamaSimple
        } else if value.starts_with("llama") || value == "completion" {
            RunnerStyle::LlamaCompletion
        } else {
            RunnerStyle::NoxLocal
        }
    }
}

fn read_prompt() -> io::Result<String> {
    let args: Vec<String> = env::args().skip(1).collect();
    if !args.is_empty() {
        return Ok(args.join(" "));
    }
    let stdin = io::stdin();
    let mut lock = stdin.lock();
    let mut buf = String::new();
    lock.read_to_string(&mut buf)?;
    Ok(buf)
}

fn env_u32(key: &str) -> Option<u32> {
    env::var(key).ok().and_then(|v| v.parse::<u32>().ok())
}

fn env_i32(key: &str) -> Option<i32> {
    env::var(key).ok().and_then(|v| v.parse::<i32>().ok())
}

fn env_f32(key: &str) -> Option<f32> {
    env::var(key).ok().and_then(|v| v.parse::<f32>().ok())
}

fn env_u64(key: &str) -> Option<u64> {
    env::var(key).ok().and_then(|v| v.parse::<u64>().ok())
}

fn env_bool(key: &str) -> Option<bool> {
    env::var(key).ok().map(|v| {
        let v = v.trim();
        v == "1" || v.eq_ignore_ascii_case("true") || v.eq_ignore_ascii_case("yes")
    })
}

fn env_path(key: &str) -> Option<PathBuf> {
    env::var(key).ok().and_then(|v| {
        let v = v.trim();
        if v.is_empty() {
            None
        } else {
            Some(PathBuf::from(v))
        }
    })
}

fn is_executable(path: &Path) -> bool {
    if !path.exists() {
        return false;
    }
    fs::metadata(path)
        .map(|m| m.is_file() && (cfg!(windows) || m.mode_bits_executable()))
        .unwrap_or(false)
}

fn run_persistent(cfg: &Config) -> io::Result<()> {
    if !matches!(cfg.runner_style, RunnerStyle::NoxLocal) {
        return Err(io::Error::new(
            io::ErrorKind::InvalidInput,
            "persistent mode requires NOX_RUNNER_STYLE=noxlocal",
        ));
    }
    let runner = cfg
        .resolve_runner()
        .ok_or_else(|| io::Error::new(io::ErrorKind::NotFound, "no runner binary found"))?;

    let mut cmd = Command::new(&runner);
    cmd.stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::inherit());

    cmd.arg("-serve");
    if cfg.persist_rs {
        cmd.arg("-serve-rs");
    }
    if cfg.keep_cache {
        cmd.arg("-keep-cache");
    }
    if cfg.append_only {
        cmd.arg("-append");
    }
    if cfg.input_only {
        cmd.arg("-input-only");
    }
    if cfg.raw {
        cmd.arg("-raw");
    }
    if cfg.fast {
        cmd.arg("-fast");
    }
    if cfg.prepack {
        cmd.arg("-prepack");
    }
    if let Some(state_load) = &cfg.state_load {
        cmd.arg("-state-load");
        cmd.arg(state_load);
    }
    if let Some(state_save) = &cfg.state_save {
        cmd.arg("-state-save");
        cmd.arg(state_save);
    }
    cmd.args(["-ctx", &cfg.ctx.to_string()]);
    cmd.args(["-max-tokens", &cfg.max_tokens.to_string()]);
    cmd.args(["-batch", &cfg.batch.to_string()]);
    cmd.args(["-temp", &cfg.temp.to_string()]);
    cmd.args(["-top-p", &cfg.top_p.to_string()]);
    cmd.args(["-top-k", &cfg.top_k.to_string()]);
    if let Some(model) = cfg.model_path() {
        cmd.args(["-model", &model]);
    }
    if let Some(threads) = cfg.threads {
        cmd.env("NOX_NUM_THREADS", threads.to_string());
    }

    let mut child = cmd.spawn()?;
    let mut child_stdin = child
        .stdin
        .take()
        .ok_or_else(|| io::Error::new(io::ErrorKind::Other, "failed to open child stdin"))?;
    let mut child_stdout = child
        .stdout
        .take()
        .ok_or_else(|| io::Error::new(io::ErrorKind::Other, "failed to open child stdout"))?;

    let stdin_thread = thread::spawn(move || {
        let stdin = io::stdin();
        let _ = io::copy(&mut stdin.lock(), &mut child_stdin);
    });

    let mut stdout = io::stdout();
    let _ = io::copy(&mut child_stdout, &mut stdout);
    let _ = stdin_thread.join();

    let status = child.wait()?;
    if !status.success() {
        return Err(io::Error::new(
            io::ErrorKind::Other,
            format!("runner exited with status {status}"),
        ));
    }
    Ok(())
}

fn route_prompt(cfg: &Config, prompt: &str) -> Option<String> {
    let delim = cfg.route_delim.trim();
    if delim.is_empty() {
        return None;
    }
    let mut chunks: Vec<String> = prompt
        .split(delim)
        .map(|s| s.trim())
        .filter(|s| !s.is_empty())
        .map(|s| s.to_string())
        .collect();

    if chunks.len() < 2 {
        return None;
    }

    let (query, candidates) = if let Some(query) = &cfg.route_query {
        (query.trim().to_string(), chunks)
    } else {
        let query = chunks.remove(0);
        (query, chunks)
    };

    if candidates.is_empty() {
        return None;
    }

    let scores: Vec<f32> = candidates
        .iter()
        .map(|chunk| overlap_score(&query, chunk))
        .collect();

    let mut selected = if scores.iter().all(|s| *s <= 0.0) {
        top_k_indices(&scores, cfg.route_keep.max(1))
    } else {
        let route = neuroute::route_values(&scores);
        let mut idxs: Vec<usize> = route
            .mask
            .iter()
            .enumerate()
            .filter_map(|(i, keep)| if *keep { Some(i) } else { None })
            .collect();
        if idxs.is_empty() || idxs.len() == scores.len() {
            idxs = top_k_indices(&scores, cfg.route_keep.max(1));
        }
        idxs
    };

    if cfg.route_keep > 0 && selected.len() > cfg.route_keep {
        selected = top_k_indices(&scores, cfg.route_keep);
    }
    selected.sort_unstable();

    let joiner = format!("\n{delim}\n");
    let context = selected
        .iter()
        .map(|idx| candidates[*idx].clone())
        .collect::<Vec<_>>()
        .join(&joiner);

    if cfg.route_debug {
        eprintln!(
            "nox: routed {} -> {} chunks",
            candidates.len(),
            selected.len()
        );
    }

    if context.is_empty() {
        return Some(query);
    }
    Some(format!("{query}{joiner}{context}"))
}

fn overlap_score(query: &str, chunk: &str) -> f32 {
    let q = token_set(query);
    let c = token_set(chunk);
    if q.is_empty() || c.is_empty() {
        return 0.0;
    }
    let mut common = 0usize;
    for tok in q.iter() {
        if c.contains(tok) {
            common += 1;
        }
    }
    common as f32 / q.len() as f32
}

fn token_set(text: &str) -> HashSet<String> {
    let mut set = HashSet::new();
    let mut buf = String::new();
    for ch in text.chars() {
        if ch.is_ascii_alphanumeric() {
            for lower in ch.to_lowercase() {
                buf.push(lower);
            }
        } else if !buf.is_empty() {
            set.insert(buf.clone());
            buf.clear();
        }
    }
    if !buf.is_empty() {
        set.insert(buf);
    }
    set
}

fn top_k_indices(scores: &[f32], k: usize) -> Vec<usize> {
    if scores.is_empty() {
        return Vec::new();
    }
    if k == 0 || k >= scores.len() {
        return (0..scores.len()).collect();
    }
    let mut idx: Vec<usize> = (0..scores.len()).collect();
    idx.sort_by(|&a, &b| {
        scores[b]
            .partial_cmp(&scores[a])
            .unwrap_or(std::cmp::Ordering::Equal)
            .then_with(|| a.cmp(&b))
    });
    idx.truncate(k);
    idx
}

trait MetadataExt {
    fn mode_bits_executable(&self) -> bool;
}

#[cfg(unix)]
impl MetadataExt for fs::Metadata {
    fn mode_bits_executable(&self) -> bool {
        use std::os::unix::fs::MetadataExt;
        self.mode() & 0o111 != 0
    }
}

#[cfg(not(unix))]
impl MetadataExt for fs::Metadata {
    fn mode_bits_executable(&self) -> bool {
        true
    }
}

fn simulate_stream(cfg: &Config, prompt: &str) -> io::Result<()> {
    let mut out = io::stdout();
    if !cfg.raw {
        writeln!(out, "nox:")?;
        out.flush()?;
    }

    let text = cfg
        .sim_text
        .clone()
        .unwrap_or_else(|| default_sim_text(prompt));
    let chunks = split_chunks(&text);

    if !chunks.is_empty() && cfg.sim_ttft_ms > 0 {
        thread::sleep(Duration::from_millis(cfg.sim_ttft_ms));
    }
    let delay = if cfg.sim_tps > 0.0 {
        Duration::from_secs_f32(1.0 / cfg.sim_tps)
    } else {
        Duration::from_secs(0)
    };

    for (idx, chunk) in chunks.iter().enumerate() {
        out.write_all(chunk.as_bytes())?;
        out.flush()?;
        if idx + 1 < chunks.len() && delay.as_nanos() > 0 {
            thread::sleep(delay);
        }
    }

    if !cfg.raw {
        out.write_all(b"\n")?;
        out.flush()?;
    }
    Ok(())
}

fn default_sim_text(prompt: &str) -> String {
    let prompt = prompt.trim();
    if prompt.is_empty() {
        "simulated A1000 mode. streaming output to validate the pipeline. ".to_string()
    } else {
        format!(
            "simulated A1000 mode. prompt: {}. streaming output to validate the pipeline. ",
            prompt
        )
    }
}

fn split_chunks(text: &str) -> Vec<String> {
    let mut chunks = Vec::new();
    for (idx, word) in text.split_whitespace().enumerate() {
        if idx == 0 {
            chunks.push(word.to_string());
        } else {
            chunks.push(format!(" {}", word));
        }
    }
    if chunks.is_empty() && !text.is_empty() {
        chunks.push(text.to_string());
    }
    chunks
}

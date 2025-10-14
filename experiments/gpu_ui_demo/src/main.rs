use eframe::egui;
use parking_lot::Mutex;
use serde::{Deserialize, Serialize};
use std::collections::VecDeque;
use std::io::{BufRead, BufReader, Write};
use std::net::TcpStream;
use std::sync::mpsc::{self, Receiver, Sender};
use std::sync::Arc;
use std::thread;
use std::time::Duration;

const BRIDGE_ADDR: &str = "127.0.0.1:4510";

type EventRx = Receiver<BackendEvent>;
type JobTx = Sender<BackendJob>;

type LogLine = String;

fn main() -> eframe::Result<()> {
    let native_options = eframe::NativeOptions {
        viewport: egui::ViewportBuilder::default()
            .with_inner_size([960.0, 600.0])
            .with_min_inner_size([640.0, 480.0])
            .with_title("Noctics GPU Console"),
        ..Default::default()
    };

    eframe::run_native(
        "Noctics GPU Console",
        native_options,
        Box::new(|_cc| Box::new(DemoApp::default())),
    )
}

struct DemoApp {
    log: VecDeque<LogLine>,
    input: String,
    outbound: JobTx,
    inbound: EventRx,
    status_line: String,
    auto_scroll: bool,
    streaming_buffer: String,
    streaming_active: bool,
}

impl Default for DemoApp {
    fn default() -> Self {
        let (job_tx, job_rx) = mpsc::channel::<BackendJob>();
        let (event_tx, event_rx) = mpsc::channel::<BackendEvent>();
        Backend::spawn(job_rx, event_tx.clone());
        let _ = event_tx.send(BackendEvent::Status(format!(
            "Connecting to Noctics bridge at {}…",
            BRIDGE_ADDR
        )));
        Self {
            log: VecDeque::with_capacity(512),
            input: String::new(),
            outbound: job_tx,
            inbound: event_rx,
            status_line: String::from("Starting up…"),
            auto_scroll: true,
            streaming_buffer: String::new(),
            streaming_active: false,
        }
    }
}

impl DemoApp {
    fn poll_incoming(&mut self, ctx: &egui::Context) {
        let mut any = false;
        while let Ok(event) = self.inbound.try_recv() {
            any = true;
            match event {
                BackendEvent::Log(line) => self.push_line(line),
                BackendEvent::Status(msg) => self.status_line = msg,
                BackendEvent::Delta(chunk) => {
                    self.streaming_active = true;
                    self.streaming_buffer.push_str(&chunk);
                }
                BackendEvent::Done(full) => {
                    if !full.trim().is_empty() {
                        self.push_line(format!("Nox> {}", full));
                    }
                    self.streaming_active = false;
                    self.streaming_buffer.clear();
                }
                BackendEvent::Error(msg) => {
                    self.status_line = format!("Error: {}", msg);
                    self.push_line(format!("! {}", msg));
                    self.streaming_active = false;
                    self.streaming_buffer.clear();
                }
            }
        }
        if any {
            ctx.request_repaint();
        }
    }

    fn push_line(&mut self, line: impl Into<LogLine>) {
        const MAX_LOG: usize = 800;
        self.log.push_back(line.into());
        while self.log.len() > MAX_LOG {
            self.log.pop_front();
        }
    }

    fn submit_prompt(&mut self) {
        let prompt = self.input.trim();
        if prompt.is_empty() {
            return;
        }
        let prompt_owned = prompt.to_owned();
        self.push_line(format!("You> {}", prompt_owned));
        self.input.clear();
        if let Err(err) = self.outbound.send(BackendJob::Prompt {
            text: prompt_owned,
        }) {
            self.status_line = format!("Backend unavailable: {}", err);
        }
    }
}

impl eframe::App for DemoApp {
    fn update(&mut self, ctx: &egui::Context, _frame: &mut eframe::Frame) {
        self.poll_incoming(ctx);

        egui::TopBottomPanel::top("status_panel").show(ctx, |ui| {
            ui.horizontal(|ui| {
                ui.label(egui::RichText::new("Status:").strong());
                ui.label(&self.status_line);
            });
            if self.streaming_active {
                ui.label(egui::RichText::new("Streaming…").italics());
            }
        });

        egui::SidePanel::right("controls_panel").resizable(true).show(ctx, |ui| {
            ui.heading("Options");
            ui.separator();
            ui.toggle_value(&mut self.auto_scroll, "Auto-scroll");
            ui.separator();
            ui.label("Run bridge: python experiments/gpu_ui_demo/bridge_server.py");
            ui.small("Prompts are forwarded to the real Noctics ChatClient over TCP.");
        });

        egui::CentralPanel::default().show(ctx, |ui| {
            ui.heading("Session Stream");
            ui.separator();
            egui::ScrollArea::vertical()
                .auto_shrink([false; 2])
                .stick_to_bottom(self.auto_scroll)
                .show(ui, |ui| {
                    for line in &self.log {
                        let color = if line.starts_with("You>") {
                            egui::Color32::from_rgb(160, 220, 255)
                        } else if line.starts_with("Nox>") {
                            egui::Color32::from_rgb(180, 255, 180)
                        } else {
                            egui::Color32::LIGHT_GRAY
                        };
                        ui.colored_label(color, line);
                    }
                    if self.streaming_active && !self.streaming_buffer.is_empty() {
                        ui.separator();
                        ui.colored_label(
                            egui::Color32::from_rgb(200, 255, 200),
                            format!("Nox (streaming)> {}", self.streaming_buffer),
                        );
                    }
                });
        });

        egui::TopBottomPanel::bottom("input_panel").show(ctx, |ui| {
            ui.separator();
            let input_field = ui.text_edit_singleline(&mut self.input);
            if input_field.has_focus() && ui.input(|i| i.key_pressed(egui::Key::Enter)) {
                self.submit_prompt();
            }
            ui.horizontal(|ui| {
                if ui.button("Send").clicked() {
                    self.submit_prompt();
                }
            });
            if !input_field.has_focus() {
                input_field.request_focus();
            }
        });
    }
}

#[derive(Serialize)]
struct PromptPayload<'a> {
    #[serde(rename = "type")]
    kind: &'a str,
    text: &'a str,
}

#[derive(Deserialize)]
struct BridgeMessage {
    #[serde(rename = "type")]
    kind: String,
    text: Option<String>,
    message: Option<String>,
}

enum BackendEvent {
    Log(String),
    Status(String),
    Delta(String),
    Done(String),
    Error(String),
}

enum BackendJob {
    Prompt { text: String },
}

struct Backend;

impl Backend {
    fn spawn(rx: Receiver<BackendJob>, tx: Sender<BackendEvent>) {
        thread::spawn(move || {
            match RemoteBackend::connect(BRIDGE_ADDR, tx.clone()) {
                Ok(backend) => backend.run(rx, tx),
                Err(err) => {
                    let _ = tx.send(BackendEvent::Error(format!(
                        "Bridge unavailable: {}. Falling back to simulated echo.",
                        err
                    )));
                    Self::run_simulated(rx, tx);
                }
            }
        });
    }

    fn run_simulated(rx: Receiver<BackendJob>, tx: Sender<BackendEvent>) {
        while let Ok(job) = rx.recv() {
            match job {
                BackendJob::Prompt { text } => {
                    thread::sleep(Duration::from_millis(200));
                    let _ = tx.send(BackendEvent::Done(format!("(simulated) {}", text)));
                }
            }
        }
    }
}

struct RemoteBackend {
    writer: Arc<Mutex<TcpStream>>,
}

impl RemoteBackend {
    fn connect(addr: &str, tx: Sender<BackendEvent>) -> Result<Self, String> {
        let stream = TcpStream::connect(addr).map_err(|err| err.to_string())?;
        stream
            .set_nodelay(true)
            .map_err(|err| err.to_string())?;
        let reader_stream = stream
            .try_clone()
            .map_err(|err| err.to_string())?;
        Self::spawn_reader(reader_stream, tx.clone());
        let _ = tx.send(BackendEvent::Status(format!(
            "Connected to Noctics bridge at {}",
            addr
        )));
        Ok(Self {
            writer: Arc::new(Mutex::new(stream)),
        })
    }

    fn spawn_reader(stream: TcpStream, tx: Sender<BackendEvent>) {
        thread::spawn(move || {
            let mut reader = BufReader::new(stream);
            loop {
                let mut line = String::new();
                match reader.read_line(&mut line) {
                    Ok(0) => {
                        let _ = tx.send(BackendEvent::Error(
                            "Bridge connection closed.".to_string(),
                        ));
                        break;
                    }
                    Ok(_) => {
                        let trimmed = line.trim();
                        if trimmed.is_empty() {
                            continue;
                        }
                        match serde_json::from_str::<BridgeMessage>(trimmed) {
                            Ok(msg) => match msg.kind.as_str() {
                                "hello" => {
                                    if let Some(message) = msg.message {
                                        let _ = tx.send(BackendEvent::Status(message));
                                    }
                                }
                                "delta" => {
                                    if let Some(text) = msg.text {
                                        let _ = tx.send(BackendEvent::Delta(text));
                                    }
                                }
                                "done" => {
                                    let text = msg.text.unwrap_or_default();
                                    let _ = tx.send(BackendEvent::Done(text));
                                }
                                "log" => {
                                    if let Some(text) = msg.text {
                                        let _ = tx.send(BackendEvent::Log(text));
                                    }
                                }
                                "error" => {
                                    let text = msg
                                        .message
                                        .or(msg.text)
                                        .unwrap_or_else(|| "Unknown bridge error".into());
                                    let _ = tx.send(BackendEvent::Error(text));
                                }
                                other => {
                                    let _ = tx.send(BackendEvent::Log(format!(
                                        "Bridge> {}",
                                        other
                                    )));
                                }
                            },
                            Err(err) => {
                                let _ = tx.send(BackendEvent::Log(format!(
                                    "Bridge parse error: {} :: {}",
                                    err, trimmed
                                )));
                            }
                        }
                    }
                    Err(err) => {
                        let _ = tx.send(BackendEvent::Error(format!(
                            "Bridge read failed: {}",
                            err
                        )));
                        break;
                    }
                }
            }
        });
    }

    fn run(self, rx: Receiver<BackendJob>, tx: Sender<BackendEvent>) {
        while let Ok(job) = rx.recv() {
            match job {
                BackendJob::Prompt { text } => {
                    if let Err(err) = self.send_prompt(&text) {
                        let _ = tx.send(BackendEvent::Error(format!(
                            "Bridge send failed: {}",
                            err
                        )));
                        let _ = tx.send(BackendEvent::Status(
                            "Bridge connection lost. Using simulated echo.".into(),
                        ));
                        Backend::run_simulated(rx, tx);
                        return;
                    }
                }
            }
        }
    }

    fn send_prompt(&self, text: &str) -> Result<(), String> {
        let payload = PromptPayload {
            kind: "prompt",
            text,
        };
        let line = serde_json::to_string(&payload)
            .map_err(|err| err.to_string())? + "\n";
        let mut guard = self.writer.lock();
        guard.write_all(line.as_bytes()).map_err(|err| err.to_string())?;
        guard.flush().map_err(|err| err.to_string())
    }
}

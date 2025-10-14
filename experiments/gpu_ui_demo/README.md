# Noctics GPU Console Demo

GPU-accelerated desktop console for Noctics using Rust + `eframe/egui`. Supports streaming from the real `ChatClient` via a lightweight TCP bridge.

## Prerequisites

- Rust toolchain (`cargo`, `rustc`). `rustup` 1.70+ recommended.
- Graphics drivers compatible with `wgpu` (Vulkan/Metal/DirectX).
- For the live bridge, a running Noctics environment (local model endpoint reachable by the usual CLI).

## Run the Bridge

1. In one terminal, start the Python bridge (loads the real `ChatClient`):
   ```bash
   cd experiments/gpu_ui_demo
   python bridge_server.py
   ```
   It listens on `127.0.0.1:4510` and streams deltas/done messages to any client.

2. Confirm the standard CLI still works against your model (`python main.py --stream`). The bridge uses the same environment variables and system prompt as the CLI.

## Launch the GPU UI

In another terminal/tab:
```bash
cd experiments/gpu_ui_demo
cargo run --release
```

The window shows:
- Log panel with `You>` and `Nox>` turns.
- Live streaming line while tokens arrive.
- Status banner reporting bridge connectivity.
- Input field forwarding prompts to the bridge.

If the bridge is unavailable the UI falls back to a simple simulated echo so you can sanity-check the rendering.

## Wiring Notes

- Communication protocol: newline-delimited JSON. `prompt` → `delta`/`done` responses; `reset` resets the session.
- Update `Backend::spawn` / `RemoteBackend::send_prompt` (`src/main.rs`) if you change port, protocol, or add richer commands.
- The Python bridge (`bridge_server.py`) instantiates `central.core.ChatClient(stream=True)` and relays deltas via the TCP connection. Extend it to multiplex multiple sessions or feed helper results as needed.

Once satisfied with the desktop experience, port the same protocol/renderer into an Android `NativeActivity` for the mobile GPU demo.

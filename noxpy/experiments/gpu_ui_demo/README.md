# GPU Console Playground

Nox wanted a shiny front-end, so here’s the Rust + `eframe/egui` experiment that
streams straight from the real `ChatClient`. Think of it as a desktop cockpit for Noctics.

## Bring your toys
- Rust toolchain (`cargo`, `rustc`) via `rustup`
- Graphics drivers that can deal with `wgpu`
- A running Noctics backend (`python main.py --stream` works as a smoke test)

## Fire up the bridge
```bash
cd experiments/gpu_ui_demo
python bridge_server.py
```
Listens on `127.0.0.1:4510`, speaks newline-delimited JSON, relays every delta the core emits.

## Launch the UI
```bash
cargo run --release
```
You get:
- Log view with `You>` / `Nox>` tags
- Live streaming line while tokens roll in
- Status banner telling you if the bridge is awake
- Input box that forwards prompts across the wire

Bridge down? The UI flips to a fake echo so you can still poke the renderer.

## Wire protocol notes
- Messages are JSON objects ended with `\n`
- Client sends `{"type":"prompt","text":"..."}`; bridge replies with `delta` and `done`
- Tweak port/format inside `src/main.rs` (`RemoteBackend`) and `bridge_server.py`
- Bridge spins up `central.core.ChatClient(stream=True)`—extend it if you want instrument results, multiple sessions, whatever makes you grin

Next stop: wrap the same protocol into an Android `NativeActivity` for the mobile GPU teaser.

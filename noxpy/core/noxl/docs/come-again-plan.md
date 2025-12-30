# Come-Again Implementation Plan

Living outline for two upcoming initiatives: the LayMA runtime shim and the mobile (React Native) wrapper that embeds Noxics via that shim. Update this doc whenever priorities shift.

---

## 1. LayMA Runtime Shim

Goal: provide a uniform local endpoint (`http://127.0.0.1:<port>/api/chat`) that proxies either a local LayMA model or a remote/cloud LLM. Nox only talks to this shim; the shim handles routing, payload translation, and credential management.

### Requirements
- Support selecting a local `.gguf`/LayMA model file **and/or** a remote provider (OpenAI, Anthropic, etc.).
- Expose a local HTTP API compatible with the current `NOX_LLM_URL` contract.
- Translate payloads/responses on the fly (streaming + non-stream).
- Persist per-alias routing so requests for `nox` hit the chosen backend.

### Architecture Sketch
1. **Launcher CLI/UI**
   - `layma setup` prompts for model path or cloud endpoint + API key.
   - Writes config (`~/.config/layma/runtime.json`) with alias mappings.
2. **Runtime Service**
   - Spins up local HTTP server.
   - For local models: loads LayMA runtime (llama.cpp or Ollama) with the selected weights.
   - For cloud backends: forwards requests to provider, inserts auth headers, handles streaming.
   - Maintains a worker pool so multiple concurrent chats share the same runtime.
3. **Adapter Layer**
   - Normalizes prompts/responses, ensures token counts + finish reasons remain consistent.
   - Logs telemetry so Nox can self-score regardless of backend.

### Implementation TODO
- [x] Create `central.runtime` package with config loader + CLI for the shim (initial HTTP bridge).
- [x] Implement HTTP server scaffolding (ThreadingHTTPServer; upgrade later if we need FastAPI).
- [ ] Add local-engine adapter (start with LayMA reference binary).
- [ ] Add cloud adapters (OpenAI first; Anthropic/others behind interface).
- [ ] Integrate with `scripts/nox.run` so it launches the shim if needed.
- [ ] Provide health endpoint + status CLI (`layma status`).

---

## 2. Mobile Wrapper (React Native)

Goal: ship a lightweight mobile shell (Android/iOS) that controls the runtime shim and renders the Nox chat UI. The app does **not** host the model; it starts/communicates with the local LayMA runtime running on-device.

### Requirements
- Cross-platform UI (React Native/Expo) with minimal dependencies.
- Start/stop the LayMA runtime (either bundled binary or downloaded).
- Provide a simple chat screen that mirrors the desktop CLI (history, streaming text).
- Allow selecting the active model/backend via in-app settings.

### Architecture Sketch
1. **Bridge Layer**
   - Native module or background service that launches the LayMA runtime binary with the selected model.
   - Exposes status updates (running, port, logs) to JS via event emitter.
2. **Networking**
   - React Native app communicates with `http://127.0.0.1:<port>/api/chat`.
   - Streams responses (Server-Sent Events or chunked fetch) to update the UI.
3. **UI Flow**
   - Onboarding: pick model/backend, accept license warning.
   - Home screen: chat history, message composer, `/slash` command shortcuts.
   - Settings: model selection, cloud credentials, log export.

### Implementation TODO
- [x] Scaffold React Native app (`apps/mobile`).
- [ ] Implement native runtime controller (Android Service / iOS background task).
- [x] Port minimal chat UI (reuse design tokens from CLI where possible).
- [ ] Add storage for sessions (SQLite on-device).
- [ ] Hook up `/list-models`, `/config`, `/reset` actions to runtime shim.

### Pyodide prototype plan (everything on-device)

```
┌────────────────────────────┐
│ React Native / Expo (UI)   │
│  • chat screen + settings  │
└────────────┬───────────────┘
             │ postMessage bridge
┌────────────▼───────────────┐
│ Pyodide Worker (Wasm CPython)
│  • imports central.runtime │
└────────────┬───────────────┘
             │ direct ChatClient calls
┌────────────▼───────────────┐
│ central.core.ChatClient &  │
│ persona/memory logging     │
└────────────────────────────┘
```

```
User taps Send
      │
      ▼
React Native hook → runtimeBridge.send(payload)
      │
      ▼ (postMessage)
Pyodide worker → central.runtime.handle_chat()
      │
      ▼
Reply {message, meta} → RN UI updates bubbles + HUD
```

1. **Bundle Pyodide + core** – ship the Pyodide runtime (Wasm + JS loader) and copy the existing `central/` Python modules into its virtual filesystem during app start.
2. **Launch a dedicated worker** – when the app boots, start a JS worker that loads Pyodide, imports `central.runtime`, and exposes a `postMessage` handler.
3. **Bridge API** – the RN hook posts payloads (`{model, messages, ...}`) to that worker; inside Pyodide we call `central.runtime.handle_chat` and send `{message, meta}` back.
4. **Mount storage** – map Pyodide's `~/.local/share/noctics` paths to the platform data directory (Android `/data/.../files`, iOS `Application Support`) so session logs + persona overrides remain fully local.
5. **Local models** – download or prebundle `scale*-nox` weights into the app's OBB/Application Support folder, then expose them to the Python transport (either by mounting the directory or by bridging to a native/wasm inference engine).
6. **Installer UX** – first-run flow checks storage, fetches models, and initializes Pyodide (think “game install” progress screen). After that, the existing chat UI just calls the internal endpoint instead of a remote URL.

---

## 3. Next Steps & Coordination

- [ ] Finalize runtime API schema so both CLI and mobile wrapper consume the same contract.
- [ ] Decide how to package LayMA binaries per platform (download-on-demand vs bundling).
- [ ] Align licensing: ensure model downloads surface upstream terms before pulling.
- [ ] Once runtime prototype is ready, build mobile MVP focused on Android (APK) before iOS.

Update this plan before large changes. When a milestone lands, note the commit/tag for traceability.

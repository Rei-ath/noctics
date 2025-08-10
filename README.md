# Noctics

**Noctics** is a lightweight, extensible AI orchestration framework.  
It acts as a **prefrontal cortex** for your AI assistants — managing context, reasoning over information, and integrating multiple LLMs (local or API-based) into a single continuous conversation.

---

## 🚀 Key Features
- **Hierarchical Reasoning Core (HRM)** — A central reasoning module that stores, processes, and synthesizes knowledge from multiple AI models.
- **Multi-LLM Support** — Connect to GPT, Claude, Mistral, Grok, or your own local models via API or socket.
- **Stateless & Stateful Modes** — Stateless for isolated queries, stateful for continuous conversations.
- **Lightweight by Design** — No heavy default models; you choose your backends.
- **Overlay & Mobile-Ready** — Planned UI overlay for quick AI access anywhere.
- **Incognito Mode** — Conversations without storing permanent memory.

---

## 🧠 How It Works
1. **User Input** → Sent to **Noctics Middleware**.
2. **HRM** processes the query, decides which LLM(s) to call.
3. **LLMs Respond** → Outputs stored in HRM working memory.
4. **HRM Synthesizes** → Merges, validates, and enhances responses.
5. **User Output** → Clean, reasoned, and context-aware answer.

---

### Example Flow

User: "Design a solar-powered water pump." HRM: Breaks down tasks → Calls GPT for parts list, Claude for calculations. HRM: Merges answers, checks consistency. Output: Unified plan with specifications, costs, and optional diagram.

---

## 🛠 Tech Stack
- **Core Language:** Python (FastAPI for API layer)
- **Frontend:** React / Next.js (planned)
- **Memory:** SQLite / Redis
- **Model Connectors:** OpenAI API, Anthropic API, Local LLM (via Oobabooga or llama.cpp)
- **Architecture:** Modular, plug-and-play

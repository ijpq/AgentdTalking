# AgentdTalking

A multi-agent discussion platform where AI personas debate, brainstorm, and discuss topics in real time — and you can join the conversation.

## Features

- **Three conversation modes** — Discussion (casual), Debate (adversarial), Brainstorm (fast-paced ideation)
- **AI roster generation** — Given a topic, an LLM designs 3-5 distinct personas with the right backgrounds and perspectives for a meaningful conversation
- **Live streaming** — Responses stream token-by-token over WebSocket, with typing indicators
- **Web search** — Optional Tavily integration gives each agent current internet knowledge before the discussion starts
- **User participation** — Jump into the conversation at any time; agents will respond to your messages naturally
- **Consensus detection** — The discussion ends automatically when every agent explicitly agrees on a conclusion
- **Multi-provider** — Supports any OpenAI-compatible API (OpenAI, local Ollama, third-party proxies) and Anthropic natively

## Quick Start

```bash
pip install fastapi 'uvicorn[standard]' openai anthropic httpx
uvicorn app:app --reload
```

Open http://localhost:8000.

## Usage

### 1. Configure a Global LLM

Expand **全局 LLM 配置** in the sidebar and fill in your provider, base URL, API key, and model. This config is used for AI roster generation and pre-fills new agent cards.

### 2. Generate or Add Agents

- Click **✦ AI 生成** to auto-generate personas tailored to your topic and mode.
- Or click **+ 添加** to create agents manually.

Each agent card can be individually configured with a different provider, model, or persona if needed.

### 3. (Optional) Enable Web Search

Toggle **搜索增强（Tavily）** and enter your [Tavily API key](https://tavily.com). Each agent will search the topic once before the discussion begins.

### 4. Start the Discussion

Enter a topic, pick a mode, and click **开始讨论**. Agents take turns speaking in rounds. You can type in the input bar at the bottom to join the conversation at any point.

The discussion ends when:
- All agents express consensus, or
- The maximum number of rounds is reached, or
- You click **停止讨论**.

## Architecture

```
Browser (vanilla JS)
  │
  ├─ WebSocket /ws ──► FastAPI ──► LLMAgent.stream_response()
  │                       │            ├─ Anthropic SDK (anthropic provider)
  │                       │            └─ httpx SSE streaming (openai provider)
  │                       │
  │                       ├─ Discussion loop (rounds × agents)
  │                       └─ User message queue (injected between turns)
  │
  ├─ POST /api/generate-roster ──► single LLM call → JSON personas
  ├─ POST /api/test-agent ──► lightweight connectivity check
  └─ GET / ──► static SPA
```

- **No OpenAI SDK at runtime** for the openai-compatible path — requests go through raw `httpx` to avoid WAF blocks from SDK-specific headers.
- **Streaming** uses Server-Sent Events (SSE) parsed manually from the `httpx` response stream.
- **User messages** are queued via `asyncio.Queue` and drained before each agent's turn.

## Project Structure

```
app.py                  Backend (FastAPI + WebSocket + LLM orchestration)
static/
  index.html            Single-page UI
  app.js                Frontend logic (agent cards, WebSocket, chat rendering)
  style.css             Styles
config.example.yaml     Example YAML config (agents can also be configured in the UI)
requirements.txt        Python dependencies
```

## Configuration

All configuration is done through the web UI. See `config.example.yaml` for an example of the data model.

| Field | Description |
|---|---|
| `provider` | `openai` (any OpenAI-compatible API) or `anthropic` |
| `base_url` | API endpoint (leave empty for official APIs; set to e.g. `http://localhost:11434/v1` for Ollama) |
| `api_key` | Your API key |
| `model` | Model identifier (e.g. `gpt-4o`, `claude-sonnet-4-6`, `llama3`) |

## License

MIT

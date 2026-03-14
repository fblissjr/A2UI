# A2UI Local Agent

Multi-backend A2UI agent with pluggable LLM providers. Generates A2UI v0.8 JSON from any backend, validates it, and renders natively via the Lit renderer.

## Architecture

```
Browser (Lit Shell)
  |  fetch / SSE
  v
FastAPI Agent (server.py)
  |  1. Build A2UI system prompt
  |  2. Dispatch to provider
  |  3. Parse <a2ui-json> blocks
  |  4. Fix + validate
  |  5. Return validated messages
  |
  +--> heylookitsanllm (local, /v1/messages)
  +--> Gemini (google-genai SDK)
  v
A2UI JSON --> Lit Renderer (native components)
```

## Quick Start

### Python backend

```bash
cd samples/agent/local_llm
uv sync

# Local provider (requires heylookitsanllm running)
A2UI_PROVIDER=local uv run server.py

# Gemini provider
GEMINI_API_KEY=... A2UI_PROVIDER=gemini uv run server.py
```

### Client

```bash
cd samples/agent/local_llm/client
bun install
bun dev
```

Open http://localhost:5173

## API

| Route | Method | Purpose |
|-------|--------|---------|
| `/api/chat` | POST | Send message, get A2UI response |
| `/api/chat/stream` | POST | SSE streaming variant |
| `/api/action` | POST | Send UI action, get updated response |
| `/api/config` | GET | Current provider/model |
| `/api/config` | POST | Switch provider/model at runtime |

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `A2UI_PROVIDER` | `local` | `local` or `gemini` |
| `HEYLOOK_URL` | `http://localhost:8080` | heylookitsanllm base URL |
| `HEYLOOK_MODEL` | `google_gemma-3-27b-it-mlx-bf16` | Local model ID |
| `HEYLOOK_TIMEOUT` | `120` | Request timeout in seconds |
| `GEMINI_API_KEY` | - | Gemini API key |
| `GEMINI_MODEL` | `gemini-2.5-flash` | Gemini model ID |
| `GOOGLE_GENAI_USE_VERTEXAI` | - | Set to `TRUE` for Vertex AI |
| `GOOGLE_CLOUD_PROJECT` | - | GCP project (Vertex AI) |
| `CORS_ORIGINS` | `*` | Comma-separated allowed origins |

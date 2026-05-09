# Giraffe — Production-Grade AI Runtime Framework

DAG Engine | Multi-Agent Swarm | Full-Stack Observability | 4-Tier Memory | Fault Recovery | Dual Authentication

## Overview

Giraffe is a production-grade AI runtime framework. It manages the entire lifecycle of LLM API calls — from user input, through routing and execution, to result delivery — with built-in reliability, context persistence, and observability.

**Core capabilities:**

- **Dual Authentication**: Supports both Google Cloud ADC (keyless Vertex AI) and standard OpenAI-compatible API Key authentication. The system detects which mode to use based on your configuration.
- **4-Tier Memory**: Short-term (in-memory LRU), factual (JSON), long-term (SQLite), and semantic (ChromaDB vector store). Context is preserved across sessions and retrieved via keyword or semantic similarity search.
- **DAG Execution**: Complex tasks are decomposed into a directed acyclic graph of steps. Each node is checkpointed to SQLite, enabling resume-from-failure and rollback.
- **Multi-Agent Swarm**: High-complexity tasks trigger a multi-agent workflow with Architect, Coder, and Reviewer roles iterating until consensus.
- **Fault Recovery**: Automatic handling of timeouts, rate limits, model unavailability, and context overflow via retry, model fallback, and context compression strategies.
- **Observability**: OpenTelemetry tracing on all critical paths. EventBus pushes internal state changes via SSE and WebSocket in real time.

## Installation

```bash
# Basic
pip install .

# With vector retrieval
pip install ".[vector]"

# With MCP protocol support
pip install ".[mcp]"

# All dependencies
pip install ".[all]"
```

Or run from source:

```bash
pip install opentelemetry-api opentelemetry-sdk opentelemetry-exporter-otlp
pip install fastapi uvicorn python-multipart

# Optional (graceful degradation when missing)
pip install chromadb sentence-transformers   # Vector retrieval
pip install mcp                              # MCP protocol

python giraffe.py
```

## Quick Start

### 1. Initialize

```bash
giraffe --init
```

Creates default config files at `~/.giraffe/`.

### 2. Configure Authentication

**Option A — Google Cloud ADC (recommended for Vertex AI):**

```json
{
  "router": {
    "primary_model": {
      "provider": "vertex_ai",
      "project": "YOUR_PROJECT_ID",
      "location": "us-central1"
    }
  }
}
```

Run `gcloud auth application-default login` before starting. No API key needed.

**Option B — OpenAI-compatible API Key:**

```json
{
  "router": {
    "primary_model": {
      "provider": "openai",
      "base_url": "https://api.openai.com/v1",
      "api_key": "sk-your-key-here"
    }
  }
}
```

When `api_key` is present, the system uses standard HTTP requests to the specified endpoint.

Config lookup order: `--config flag` > `./config.json` > `~/.giraffe/config.json` > built-in defaults.

### 3. Run

```bash
# Interactive CLI
giraffe

# Web server (REST / WebSocket / SSE)
giraffe --serve

# Test routing without API calls
giraffe --test-route "Design a system architecture"

# Health check
giraffe --health
```

## Architecture

```
User Input / HTTP / WebSocket
        ↓
┌──────────────────────────────────────────────┐
│  Observability (OpenTelemetry + OTLP)        │
│  EventBus → SSE / WebSocket                  │
└──────────────────┬───────────────────────────┘
                   ↓
① Core          Config / AppState / CreditMonitor
                   ↓
② Router        Keyword (<1ms) + LLM (~200ms)
                5-tier admission × model matrix
                   ↓
         ┌────────┴─────────┐
         ↓                  ↓
③-A Pipeline           ③-B Swarm
    DAG Engine              Architect → Coder → Reviewer
    Checkpoint              Multi-round iteration
         └────────┬─────────┘
                  ↓
④ Memory        Short-term / Factual / Long-term / Semantic
                  ↓
⑤ SelfHeal      Retry / Fallback / Compress / Degrade
                  ↓
⑥ Security      3-tier approval + guardrails + token budget
                  ↓
⑦ Integration   Gateway / MCP / Web Server / Multimodal
                  ↓
⑧ Executor      Circuit Breaker / Cache / Decomposer / Parallel
```

## CLI Commands

| Command | Description |
|---------|-------------|
| `/health` | System diagnostics (memory, router, pipeline, token budget) |
| `/memory` | 4-tier memory status summary |
| `/route <msg>` | Test routing decision without calling an API |
| `/stats` | Pipeline statistics (calls, success rate, cache hits) |
| `/evolve` | Trigger fault recovery rule optimization |
| `/help` | List all commands |

## API Endpoints (`--serve` mode)

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/chat` | POST | Send message, returns SSE stream. Supports multipart image upload |
| `/api/events` | GET | Subscribe to real-time event stream |
| `/ws/chat` | WS | Full-duplex WebSocket with token-level streaming |
| `/api/health` | GET | System health status JSON |

## Testing

```bash
# Run all 429 tests
python -m pytest tests/ -v
```

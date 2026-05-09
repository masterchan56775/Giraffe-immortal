# Giraffe — Production-Grade AI Runtime Framework

DAG Execution Engine | Multi-Agent Swarm | Full-Stack Telemetry | 4-Tier Memory | Self-Healing Immunity | Semantic Retrieval

---

## Overview

Giraffe is a production-grade AI runtime framework designed to solve common issues when directly calling large language model APIs: unrecoverable call failures, loss of context across sessions, inability to decompose and collaborate on complex tasks, and lack of observability of system behavior.

Giraffe is not a chatbot; it is a **complete AI scheduling and operations foundation**. It takes over the entire pipeline from user input to model invocation and result delivery, embedding engineering capabilities at every step:

- **Reliable Invocation**: When an API fails, the self-healing system automatically matches antibody rules to execute retries, model degradation, or parameter correction without manual intervention.
- **Persistent Context**: A 4-tier memory system (Memory → JSON → SQLite → Vector Store) ensures key information persists across sessions, recalling historical knowledge based on semantic relevance.
- **Task Decomposition**: Complex instructions are decomposed by the DAG engine into multi-node directed graphs, supporting conditional branching, failure fallback, and resuming from breakpoints.
- **Collaborative Orchestration**: High-complexity tasks trigger the Multi-Agent Swarm, where multiple specialized roles take turns speaking until consensus is reached.
- **Full Observability**: OpenTelemetry tracks the duration of each node, and the EventBus pushes internal states to the frontend in real-time.

**Use Cases**: AI backend services requiring stability, observability, and self-healing capabilities, such as intelligent customer service, code generation platforms, automated operations assistants, and multi-step workflow engines.

---

## Installation

### Method 1: pip install (Recommended)

```bash
# Basic installation
pip install .

# With vector retrieval
pip install ".[vector]"

# With MCP protocol
pip install ".[mcp]"

# All features
pip install ".[all]"
```

After installation, simply type `giraffe` in the terminal.

### Method 2: Run from source

```bash
# Install dependencies
pip install opentelemetry-api opentelemetry-sdk opentelemetry-exporter-otlp
pip install fastapi uvicorn python-multipart

# Optional (auto-degrades if missing)
pip install chromadb sentence-transformers   # Vector semantic retrieval
pip install mcp                              # MCP protocol

# Run directly
python giraffe.py
```

---

## Quick Start

### 1. Initialize Configuration

On first use, run `--init` to copy default configurations to your user directory `~/.giraffe/`:

```bash
giraffe --init
```

### 2. Configure Authentication (Dual Engine Architecture)

Edit `~/.giraffe/config.json` to configure your settings. The system supports a dual-engine authentication mechanism:

**Option A — Google Cloud ADC (Recommended for Vertex AI):**

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

Before use, ensure you have completed local ADC authentication via the gcloud CLI: `gcloud auth application-default login`. The system automatically acquires ADC credentials; no API key is required.

**Option B — OpenAI-Compatible API Key Authentication:**

```json
{
  "router": {
    "primary_model": {
      "provider": "openai",
      "base_url": "https://api.openai.com/v1",
      "api_key": "sk-your-key"
    }
  }
}
```
When the system detects a valid `api_key` in the configuration, it automatically falls back to standard HTTP REST calls via urllib.

### 3. Startup

```bash
# Interactive mode
giraffe

# Web server mode (REST / WebSocket / SSE)
giraffe --serve

# Route testing (does not trigger API calls)
giraffe --test-route "Design a system architecture"

# System health check
giraffe --health

# Trigger evolution engine
giraffe --evolve
```

---

## Subsystem Details

### DAG Execution Engine (`graph/`)

Traditional pipelines execute a fixed 8-step sequence. Giraffe refactors this into a Directed Acyclic Graph (DAG), where each stage is a `Node` subclass. The `GraphEngine` manages state transitions according to registered edges, supporting conditional branches and loop protection.

**Resuming from Breakpoints**: After each node executes, the `CheckpointStore` (SQLite) automatically saves a `(trace_id, node_name, step_index, state_json)` snapshot. If the process crashes, calling `GraphEngine.resume(trace_id)` resumes execution from the last completed node.

### Multi-Agent Swarm (`swarm/`)

When the routing engine determines a task's complexity is `high` (e.g., large-scale code generation), the system routes the request to the `SwarmOrchestrator` for multi-role collaboration.

**Built-in Roles**:
- **Architect**: Analyzes requirements, designs architectures, and decomposes tasks (Temperature 0.3).
- **Coder**: Writes code based on the design (Temperature 0.2).
- **Reviewer**: Checks quality and security, outputting APPROVED or feedback (Temperature 0.1).

### 4-Tier Memory System (`memory/`)

| Tier | Medium | Lifecycle | Purpose |
|------|--------|-----------|---------|
| Short-term | Memory LRU | Current session | Maintains conversation continuity |
| Factual | JSON File | Persistent | Auto-extracted structured knowledge |
| Long-term | SQLite | Persistent | Full history, supports keyword search |
| Semantic | ChromaDB | Persistent | Vector similarity recall |

**Hybrid Retrieval**: `MemorySystem.semantic_search()` retrieves top_k candidates from the vector database, merges them with keyword search results, and ranks them by a composite score.

### Self-Healing Immunity System (`self_heal/`)

Giraffe treats API call failures as "infections" and automatically repairs them using a mechanism akin to a biological immune system.

**8 Built-in Antibodies**:
- **Network Timeout**: Exponential backoff retry
- **Rate Limit**: Wait and retry
- **Model Unavailable**: Switch to backup model
- **Insufficient Quota**: Switch to free model
- **Context Overflow**: Trigger deep compression and retry
- **JSON Parsing Error**: Add formatting constraints and retry
- **Permission Denied**: Downgrade to lower-permission model
- **Service Unavailable**: Wait + retry

### Routing Engine (`router/`)

The system uses a dual-path routing strategy:
1. **Fast Path (<1ms)**: Keyword and regex-based intent classifier.
2. **Slow Path (~200ms)**: LLM-based classification when the fast path lacks confidence.

**5-Tier Admission Control**: Allocates resources based on task complexity (nano, low, medium, high, xhigh).

### Observability (`observability/`)

All critical paths create Spans via OpenTelemetry.
- `@traced` decorator: Add tracing to any function with one line.
- **EventBus**: Real-time pushing of states (SSE/WebSocket) for `stage_start`, `stage_end`, `token_chunk`, `self_heal_attempt`, `swarm_turn`.

---

## Extension Development

### Custom Skills
Create a `skill_*.py` file in the `skills/` directory:
```python
SKILL_NAME = "Weather Query"
def execute(city: str) -> str:
    return f"{city}: Sunny, 25°C"
```

### Adding MCP Tool Servers
Register a new MCP Server in `config.json`:
```json
{
  "mcp": {
    "servers": {
      "filesystem": { "command": "npx", "args": ["mcp-server-filesystem", "./"] }
    }
  }
}
```

### Lifecycle Hooks
The `HookSystem` provides 7 lifecycle events for logging or custom logic injection.

### Custom Antibody Rules
Dynamically add antibodies for specific business scenarios via the `AntibodyLibrary`.

---

## Testing

```bash
# Run all 429 test cases
python -m pytest tests/ -v
```

# Giraffe — Production-Grade AI Runtime Framework

Giraffe is a high-reliability, production-grade AI application runtime framework.

**Core Features:**
* **Reliable Execution**: Exponential backoff, circuit breaking, and self-healing immunity system to automatically resolve API failures.
* **Persistent Context**: Multi-layer memory system (RAM/JSON/SQLite/Vector) with automatic project specification injection via CLAUDE.md.
* **Smart Routing**: Intent classification and tier determination to elastically route requests to the optimal model (Grok / Claude / Gemini).
* **Orchestration**: Built-in DAG execution engine supporting Coordinator-Worker collaboration for complex tasks.
* **Full Observability**: OpenTelemetry tracing integration and automatic usage telemetry.

---

## Installation

```bash
# Basic
pip install .

# Full features (includes vector retrieval & MCP)
pip install ".[all]"

# Run from source
pip install opentelemetry-api opentelemetry-sdk fastapi uvicorn
python giraffe.py
```

---

## Quick Start

### 1. Initialize & Configure
```bash
giraffe --init
```
This generates a default config at `~/.giraffe/config.json`. Edit it to fill in your API keys or routing preferences.

**Vertex AI Passwordless Authentication (Recommended):**
```bash
gcloud auth application-default login
```

**Minimal `config.json` Example:**
```json
{
  "router": {
    "primary_model": {
      "provider": "vertex_ai",
      "model": "gemini-3.5-flash",
      "project": "YOUR_GCP_PROJECT"
    }
  }
}
```

### 2. Launch
```bash
giraffe          # Interactive CLI mode
giraffe --serve  # REST API & WebSocket server
giraffe --quiet  # Quiet mode, showing WARNING+ logs only
giraffe --debug  # Debug mode, showing all detailed logs
```

---

## Common CLI Commands

In the interactive CLI, you can control the framework with the following slash commands:

| Command | Description |
|---------|-------------|
| `/model <name>` | Force lock a model (e.g., `/model sonnet`, or `/model auto` to restore routing) |
| `/tier <tier>` | Force lock a computation tier (nano/low/medium/high/xhigh) |
| `/skills` | List all available skills |
| `/<skill_name>` | Trigger a specific skill (e.g., `/analyze_repo` to analyze current codebase) |
| `/usagestats` | View model usage and cost statistics for the current session |
| `/loglevel [level]` | View or dynamically adjust the logging level (e.g., `/loglevel debug`) |
| `/health` | Run system health checks |
| `/q` or `/quit` | Exit the interactive CLI |

---

## Context & Skills Extension

* **Project Memory Injection**: Create a `GIRAFFE.md` or `CLAUDE.md` in the project root. The system automatically loads and injects these rules into the System Prompt.
* **Custom Skills**: Put custom markdown skill files (with optional YAML frontmatter for specifying models/aliases) into the `~/.giraffe/skills/` directory. Trigger them via `/<skill_name>`.

---

## Development & Packaging

```bash
# Run all unit tests
python -m pytest tests/ -v

# Pack into a standalone executable (Windows)
python build_exe.py
```

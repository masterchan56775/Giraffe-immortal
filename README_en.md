# Giraffe — Production-Grade AI Runtime Framework

DAG Execution Engine | Multi-Agent Swarm | Full-Stack Telemetry | Layered Memory | Self-Healing | Coordinator-Worker | Skills System

---

## Overview

Giraffe is a production-grade AI application runtime that 

**Core Capabilities**

- **Reliable Calls**: Exponential backoff retry, circuit breaker, self-healing immunity system
- **Persistent Context**: Multi-layer memory (RAM → JSON → SQLite → Vector) + CLAUDE.md project instruction injection
- **Task Decomposition**: DAG engine breaks complex tasks into resumable multi-step workflows
- **Orchestration**: xhigh tier triggers Coordinator-Worker (Grok plans, Claude Workers execute in parallel)
- **Full Observability**: OpenTelemetry tracing + structured color logs + usage statistics

---

## Installation

```bash
# Basic
pip install .

# Full features (vector search + MCP)
pip install ".[all]"

# From source
pip install opentelemetry-api opentelemetry-sdk fastapi uvicorn
python giraffe.py
```

---

## Quick Start

### 1. Initialize

```bash
giraffe --init
```

Creates `~/.giraffe/config.json`. Fill in your API credentials.

### 2. Authentication

**Option A — Vertex AI ADC (Recommended, no key needed)**

```bash
gcloud auth application-default login
```

```json
{
  "router": {
    "primary_model": {
      "provider": "vertex_ai",
      "model": "gemini-3-flash-preview",
      "project": "YOUR_GCP_PROJECT_ID",
      "location": "global"
    }
  }
}
```

**Option B — API Key (OpenAI-compatible)**

```bash
# .env
GIRAFFE_API_KEY=sk-your-key
ANTHROPIC_API_KEY=sk-ant-...
```

### 3. Launch

```bash
giraffe                          # Interactive mode
giraffe --serve                  # Web server (REST + WebSocket + SSE)
giraffe --debug                  # Verbose logging
giraffe --quiet                  # WARNING+ only
giraffe --log-file giraffe.log   # Write logs to file (rotating, 10MB×5)
giraffe --no-color               # Disable ANSI color
giraffe --test-route "design a system architecture"  # Test routing (no API call)
```

---

## Routing Strategy

### Three-Layer Pipeline

```
User Input
   ↓
① Intent Classification (<1ms keyword / ~200ms LLM fallback)
   ↓
② Tier Determination (task type × complexity)
   ↓
③ Model Selection (primary → fallback → emergency)
```

### Intent Classification (priority order)

| Priority | Trigger | Type | Primary Model |
|----------|---------|------|--------------|
| 0 | Image input | `VISION` | Gemini Pro |
| Special | "Can you X?" / "Do you support X?" | `CHAT` | Gemini Flash |
| 1 | automation / batch / agentic | `AGENT_TASK` | **Grok** |
| 2 | analyze repo / entire codebase | `REPO_ANALYSIS` | **Grok** |
| 3 | refactor / architecture / system design | `CODE_LARGE` | **Claude** |
| 4 | deep analysis / math proof / reasoning | `REASONING` | **Claude** |
| 5 | write code / implement / develop | `CODE_MEDIUM` | Gemini Pro |
| 6 | explain / compare / analyze | `REASONING_LIGHT` | Gemini Pro |
| 7 | search / trending / latest news | `SEARCH` | **Grok** |
| 8 | one-liner fix / add comment | `CODE_SMALL` | Gemini Pro |
| 9 | small talk / hello | `CHAT` | Gemini Flash |

### Tier System

| Tier | Share | Auto-exec | Cost Cap | Special |
|------|-------|-----------|---------|---------|
| **nano** | 40% | ✅ | $0.01 | — |
| **low** | 40% | ✅ | $0.05 | — |
| **medium** | 15% | ❌ | $1.00 | — |
| **high** | 4% | ❌ | $5.00 | — |
| **xhigh** | 1% | ❌ | $10.00 | Triggers Coordinator-Worker |

Complexity bumps: `COMPLEX` → +1 tier, `EXTREME` → +2 tiers (capped at xhigh)

### Model Matrix

```
Grok Layer (xai/grok-4.20-reasoning)
  agent_task    → grok-4.20    → claude-sonnet-4-6 → gemini-3.1-pro
  repo_analysis → grok-4.20    → claude-sonnet-4-6 → gemini-3.1-pro
  search        → grok-4.20    → gemini-3.1-pro    → gemini-flash

Claude Layer (claude-sonnet-4-6)
  code_large    → claude-sonnet → gemini-3.1-pro   → gemini-flash
  reasoning     → claude-sonnet → gemini-3.1-pro   → gemini-flash

Gemini Layer (everything else)
  chat          → gemini-3.1-pro → gemini-flash   → flash-lite
  code_medium   → gemini-3.1-pro → gemini-flash   → flash-lite
```

---

## Model Alias System

Short aliases resolve to the latest model version automatically:

| Alias | Resolves To | Supports [1m] |
|-------|------------|--------------|
| `sonnet` | `claude-sonnet-4-6` | ✅ `sonnet[1m]` |
| `opus` | `claude-opus-4-6` | ✅ `opus[1m]` |
| `haiku` | `claude-haiku-4-5` | — |
| `grok` | `xai/grok-4.20-reasoning` | — |
| `flash` | `gemini-3-flash-preview` | — |
| `gemini` | `gemini-3.1-pro-preview` | — |
| `lite` | `gemini-3.1-flash-lite` | — |

Priority: `ANTHROPIC_MODEL` env var > alias > raw model name

---

## Logging System

Managed centrally via `observability/logging_config.py`.

### Format

Terminal (ANSI color):
```
20:15:30 INFO     router  : [Router] routing decision: reasoning → claude-sonnet-4-6
20:15:31 INFO     pipeline: [Pipeline] call succeeded in 1243ms
20:15:31 WARNING  compact : [Compactor] context at 72%, triggering micro-compact
```

File (`--log-file`, rotating):
```
2026-05-17 20:15:30 [INFO    ] executor.pipeline: [Pipeline] call succeeded
```

### CLI Flags

| Flag | Description |
|------|-------------|
| `--debug` | DEBUG level, all details visible |
| `--quiet` | WARNING+ only, for production |
| `--log-file PATH` | Also write to rotating file |
| `--no-color` | Disable ANSI color (CI/redirect) |

### Runtime Adjustment (no restart needed)

```
/loglevel debug    → switch to DEBUG
/loglevel info     → back to INFO
/loglevel warning  → warnings only
/loglevel          → show current level
```

---

## CLI Commands

### Model / Tier Switching

| Command | Description |
|---------|-------------|
| `/model <name>` | Lock model (supports aliases) |
| `/model auto` | Clear lock, restore auto-routing |
| `/tier <tier>` | Lock tier (nano/low/medium/high/xhigh) |
| `/auto` | Clear all locks |
| `/grok` `/claude` `/sonnet` `/opus` `/haiku` `/flash` | Quick switch |
| `/models` | List all aliases |

### Skills System

| Command | Description |
|---------|-------------|
| `/skills` | List all available skills |
| `/analyze_repo` | Deep repository architecture analysis |
| `/review [file]` | Code review |
| `/debug [issue]` | Systematic debugging analysis |
| `/test [file]` | Generate test code |
| `/doc [file]` | Generate documentation |

Custom skills: place `.md` files in `~/.giraffe/skills/` (YAML frontmatter + Markdown body).

### System Commands

| Command | Description |
|---------|-------------|
| `/health` | System health check |
| `/memory` | Memory system summary |
| `/usagestats` | Usage stats (sessions/days/model costs) |
| `/loglevel [level]` | View/set log level |
| `/stats` | Pipeline execution statistics |
| `/token` | Token budget tracking |
| `/route <msg>` | Test routing decision |
| `/evolve` | Trigger evolution engine |
| `/antibody` | Antibody library status |
| `/fusion` | AutoFusion engine status |
| `/quit` `/q` | Exit |

---

## Skills System

### Markdown Skill Format

```markdown
---
name: analyze_repo
description: Deep code repository architecture analysis
model: grok
aliases: [ar, repo]
---

# Repository Analysis

Systematically analyze the current codebase:
1. Overall architecture and module layout
2. Core data flows
3. Key improvement recommendations
```

### Load Priority

1. `~/.giraffe/skills/` — user global skills
2. `./.giraffe/skills/` — project-level skills
3. Built-in skills (`analyze_repo`/`review`/`debug`/`test`/`doc`)

---

## Project Memory (CLAUDE.md / GIRAFFE.md)

Create `GIRAFFE.md` in your project root:

```markdown
# Project Standards

- Use Python 3.12+
- All functions must have type annotations
- Logging: `logging.getLogger(__name__)`
- Test coverage: 80%+
```

Automatically injected into every conversation's system prompt.

Search path (decreasing priority):
1. `~/.giraffe/GIRAFFE.md` — global user preferences
2. `./GIRAFFE.md` or `./CLAUDE.md` — project root
3. `./.giraffe/GIRAFFE.md` — project config directory

---

## Architecture

```
User Input / HTTP / WebSocket
        ↓
① Observability   Color logs + OpenTelemetry + Usage stats
        ↓
② Router          Intent (<1ms) → Tier → Model matrix
                  Complex tasks → Coordinator-Worker (xhigh)
        ↓
③ Memory          CLAUDE.md inject + Multi-layer + Context compression
        ↓
④ Pipeline        DAG → Circuit breaker → Retry → Tool result store
        ↓
⑤ Tools           BashTool (whitelist) / GrepTool / WorktreeTool
                  shell_validator (30+ git + 50+ external commands)
        ↓
⑥ SelfHeal        8 built-in antibodies → ErrorProcessor → EvolutionEngine
        ↓
⑦ Security        P0/P1/P2 approval + Token budget tracking
        ↓
⑧ Integration     FastAPI / MCPRegistry / HermesBridge / EventBus
```

---

## Environment Variables

| Variable | Description |
|----------|-------------|
| `ANTHROPIC_API_KEY` | Anthropic API key |
| `ANTHROPIC_MODEL` | Override all routing (force specific model) |
| `ANTHROPIC_DEFAULT_SONNET_MODEL` | Custom Sonnet version |
| `ANTHROPIC_DEFAULT_OPUS_MODEL` | Custom Opus version |
| `ANTHROPIC_SMALL_FAST_MODEL` | Model for side_query operations |
| `GIRAFFE_API_KEY` | Generic API key (referenced as `${GIRAFFE_API_KEY}`) |
| `GIRAFFE_USE_VERTEX` | Enable Vertex AI provider |
| `GIRAFFE_USE_BEDROCK` | Enable AWS Bedrock provider |
| `GIRAFFE_AVAILABLE_MODELS` | Comma-separated model allowlist |
| `ANTHROPIC_CUSTOM_MODEL_OPTION` | Custom model (skip validation) |

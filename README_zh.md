# Giraffe — 生产级 AI 运行时框架

DAG 执行引擎 | 多智能体 Swarm | 全链路 Telemetry | 多层记忆 | 自愈免疫 | Coordinator-Worker | Skills 系统

---

## 框架介绍

Giraffe 是一个面向生产环境的 AI 应用运行时框架，

**核心能力**

- **调用可靠**：指数退避重试、熔断器、自愈免疫系统，API 故障自动修复
- **上下文持续**：多层记忆（内存 → JSON → SQLite → 向量库）+ CLAUDE.md 项目级指令注入
- **任务可拆**：DAG 引擎拆解复杂指令，支持条件分支、断点续跑、回滚
- **协作可编排**：xhigh 档自动触发 Coordinator-Worker 模式，Grok 规划 + Claude 并行执行
- **全程可观测**：OpenTelemetry 追踪 + 彩色结构化日志 + 使用统计

---

## 安装

```bash
# 基础安装
pip install .

# 全部功能（向量检索 + MCP）
pip install ".[all]"

# 源码运行
pip install opentelemetry-api opentelemetry-sdk fastapi uvicorn
python giraffe.py
```

---

## 快速开始

### 1. 初始化

```bash
giraffe --init
```

生成 `~/.giraffe/config.json`，填入 API Key 后即可使用。

### 2. 认证配置

**方式 A — Vertex AI ADC（推荐，无需密钥）**

```bash
gcloud auth application-default login
```

在 `config.json` 填入 GCP 项目 ID：

```json
{
  "router": {
    "primary_model": {
      "provider": "vertex_ai",
      "model": "gemini-3-flash-preview",
      "project": "你的 GCP 项目 ID",
      "location": "global"
    }
  }
}
```

**方式 B — API Key（OpenAI 兼容接口）**

```bash
# .env
GIRAFFE_API_KEY=sk-你的密钥
ANTHROPIC_API_KEY=sk-ant-...
```

### 3. 启动

```bash
# 交互模式
giraffe

# Web 服务（REST + WebSocket + SSE）
giraffe --serve

# 调试模式（详细日志）
giraffe --debug

# 静默模式（只显示 WARNING+）
giraffe --quiet

# 日志写入文件（自动轮转，10MB×5）
giraffe --log-file giraffe.log

# 禁用彩色日志
giraffe --no-color

# 路由测试（不调用 API）
giraffe --test-route "帮我设计一个系统架构"
```

---

## 路由策略

### 三层路由流水线

```
用户输入
   ↓
① 意图分类（<1ms 关键词 / ~200ms LLM 精分）
   ↓
② 档位判定（任务类型 × 复杂度）
   ↓
③ 模型选择（主力 → fallback → emergency）
```

### 意图分类规则（优先级顺序）

| 优先级 | 触发场景 | 类型 | 主力模型 |
|--------|---------|------|---------|
| 0 | 图片输入 | `VISION` | Gemini Pro |
| 特殊 | "你会X吗" / "能不能X" | `CHAT` | Gemini Flash |
| 1 | 自动化任务 / 批量处理 / agentic | `AGENT_TASK` | **Grok** |
| 2 | 分析仓库 / 整个代码库 | `REPO_ANALYSIS` | **Grok** |
| 3 | 重构 / 架构设计 / 系统设计 | `CODE_LARGE` | **Claude** |
| 4 | 深度分析 / 数学证明 / 推理 | `REASONING` | **Claude** |
| 5 | 帮我写 / 写代码 / 实现 | `CODE_MEDIUM` | Gemini Pro |
| 6 | 分析 / 解释 / 对比 | `REASONING_LIGHT` | Gemini Pro |
| 7 | 搜索 / 热点 / 最新消息 | `SEARCH` | **Grok** |
| 8 | 小改动 / 加注释 | `CODE_SMALL` | Gemini Pro |
| 9 | 闲聊 / 你好 | `CHAT` | Gemini Flash |

### 档位判定

| 档位 | 比例 | 自动执行 | 成本上限 | 特殊行为 |
|------|------|---------|---------|---------|
| **nano** | 40% | ✅ | $0.01 | — |
| **low** | 40% | ✅ | $0.05 | — |
| **medium** | 15% | ❌ 需确认 | $1.00 | — |
| **high** | 4% | ❌ 需确认 | $5.00 | — |
| **xhigh** | 1% | ❌ 需确认 | $10.00 | 触发 Coordinator-Worker |

复杂度加成：`COMPLEX` → +1 档，`EXTREME` → +2 档（最高 xhigh）

### 模型矩阵（主力 / fallback / emergency）

```
Grok 层（xai/grok-4.20-reasoning）
  agent_task    → grok-4.20    → claude-sonnet-4-6 → gemini-3.1-pro
  repo_analysis → grok-4.20    → claude-sonnet-4-6 → gemini-3.1-pro
  search        → grok-4.20    → gemini-3.1-pro    → gemini-flash

Claude 层（claude-sonnet-4-6）
  code_large    → claude-sonnet → gemini-3.1-pro   → gemini-flash
  reasoning     → claude-sonnet → gemini-3.1-pro   → gemini-flash

Gemini 层（其他所有任务）
  chat          → gemini-3.1-pro → gemini-flash   → flash-lite
  code_medium   → gemini-3.1-pro → gemini-flash   → flash-lite
  vision        → gemini-3.1-pro → gemini-flash   → flash-lite
```

---

## 模型别名系统

支持简短别名直接使用，自动解析到当前最新版本：

| 别名 | 解析结果 | 支持 [1m] |
|------|---------|---------|
| `sonnet` | `claude-sonnet-4-6` | ✅ `sonnet[1m]` |
| `opus` | `claude-opus-4-6` | ✅ `opus[1m]` |
| `haiku` | `claude-haiku-4-5` | — |
| `grok` | `xai/grok-4.20-reasoning` | — |
| `flash` | `gemini-3-flash-preview` | — |
| `gemini` | `gemini-3.1-pro-preview` | — |
| `lite` | `gemini-3.1-flash-lite` | — |
| `best` | 同 `opus` | — |

优先级：`ANTHROPIC_MODEL` 环境变量 > 别名解析 > 原始模型名

---

## 日志系统

日志通过 `observability/logging_config.py` 统一管理。

### 格式

终端输出（ANSI 彩色）：
```
20:15:30 INFO     router  : [Router] 路由决策: reasoning → claude-sonnet-4-6
20:15:31 INFO     pipeline: [Pipeline] 调用成功，耗时 1243ms
20:15:31 WARNING  compact : [Compactor] 上下文已达 72%，触发 micro-compact
```

文件输出（`--log-file`，含完整路径，自动轮转）：
```
2026-05-17 20:15:30 [INFO    ] executor.pipeline: [Pipeline] 调用成功
```

### 启动参数

| 参数 | 说明 |
|------|------|
| `--debug` | DEBUG 级别，显示所有内部细节 |
| `--quiet` | WARNING+ 级别，适合生产环境 |
| `--log-file PATH` | 同时写入文件（10MB × 5 轮转） |
| `--no-color` | 禁用 ANSI 彩色（CI/重定向场景） |

### 运行时调整

```
/loglevel debug    → 切换到 DEBUG（无需重启）
/loglevel info     → 切回 INFO
/loglevel warning  → 只看警告
/loglevel          → 查看当前级别
```

---

## CLI 命令

### 模型 / 档位切换

| 命令 | 说明 |
|------|------|
| `/model <name>` | 锁定模型（支持别名，如 `/model sonnet`） |
| `/model auto` | 清除锁定，恢复自动路由 |
| `/tier <tier>` | 锁定档位（nano/low/medium/high/xhigh） |
| `/auto` | 清除所有锁定 |
| `/grok` `/claude` `/gemini` `/flash` `/opus` `/haiku` `/sonnet` | 快速切换 |
| `/models` | 列出所有可用别名 |

### Skills 系统

| 命令 | 说明 |
|------|------|
| `/skills` | 列出所有可用技能 |
| `/analyze_repo` | 深入分析当前代码仓库 |
| `/review [file]` | 代码审查 |
| `/debug [问题]` | 系统性调试分析 |
| `/test [file]` | 生成测试代码 |
| `/doc [file]` | 生成文档 |

自定义技能：在 `~/.giraffe/skills/` 目录放置 `.md` 文件即可（YAML frontmatter + Markdown 正文）。

### 系统命令

| 命令 | 说明 |
|------|------|
| `/health` | 系统健康检查 |
| `/memory` | 记忆系统摘要 |
| `/usagestats` | 使用统计（会话数/天数/模型用量） |
| `/loglevel [level]` | 查看/调整日志级别 |
| `/stats` | 流水线执行统计 |
| `/token` | Token 预算统计 |
| `/route <消息>` | 测试路由决策 |
| `/evolve` | 触发进化引擎 |
| `/antibody` | 抗体库状态 |
| `/fusion` | AutoFusion 引擎状态 |
| `/credit` | 信用监控状态 |
| `/topup` | 切回三方 API |
| `/quit` `/q` | 退出 |

---

## Skills 系统

### Markdown 技能格式

```markdown
---
name: analyze_repo
description: 深入分析代码仓库架构
model: grok          # 可选，指定模型别名
aliases: [ar, repo]  # 可选，快捷命令
---

# 仓库分析

请系统分析当前代码仓库：
1. 整体架构和模块划分
2. 核心数据流
3. 主要改进建议
```

### 技能加载优先级

1. `~/.giraffe/skills/` — 用户全局技能
2. `./.giraffe/skills/` — 项目级技能  
3. 内置技能（`analyze_repo`/`review`/`debug`/`test`/`doc`）

---

## 项目记忆（CLAUDE.md / GIRAFFE.md）

在项目根目录创建 `GIRAFFE.md`（或 `CLAUDE.md`）：

```markdown
# 项目规范

- 使用 Python 3.12+
- 所有函数必须有类型注解
- 日志使用 logging.getLogger(__name__)
- 测试覆盖率要求 80%+
```

系统启动时自动注入到每次对话的 system prompt，无需手动告知 AI 项目规范。

搜索路径（优先级递减）：
1. `~/.giraffe/GIRAFFE.md` — 全局用户偏好
2. `./GIRAFFE.md` 或 `./CLAUDE.md` — 当前项目根目录
3. `./.giraffe/GIRAFFE.md` — 项目级配置目录

---

## 系统架构

```
用户输入 / HTTP / WebSocket
        ↓
① Observability   彩色结构化日志 + OpenTelemetry Span + 使用统计
        ↓
② Router          意图分类（<1ms）→ 档位判定 → 模型矩阵选择
                  复杂任务 → Coordinator-Worker（xhigh）
        ↓
③ Memory          CLAUDE.md 注入 + 多层记忆 + 上下文压缩（三级阈值）
        ↓
④ Pipeline        DAG 执行 → 熔断器 → 指数退避重试 → 工具结果持久化
        ↓
⑤ Tools           BashTool（白名单验证）/ GrepTool / WorktreeTool
                  shell_validator（30+ git 子命令 + 50+ 外部命令）
        ↓
⑥ SelfHeal        8 内置抗体 → ErrorProcessor → EvolutionEngine
        ↓
⑦ Security        P0/P1/P2 三级审批 + Token 预算追踪
        ↓
⑧ Integration     FastAPI / MCPRegistry / HermesBridge / EventBus
```

---

## API 端点（`--serve` 模式）

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/chat` | POST | 发送消息（SSE 流 / JSON） |
| `/api/events` | GET | SSE 实时事件（流水线阶段、自愈进度） |
| `/ws/chat` | WS | 全双工 WebSocket |
| `/api/health` | GET | 健康状态 JSON |

```bash
curl -X POST http://localhost:8000/api/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "帮我重构这段代码"}'
```

---

## 完整配置参考

```json
{
  "router": {
    "primary_model": {
      "provider": "vertex_ai",
      "model": "gemini-3-flash-preview",
      "project": "YOUR_PROJECT_ID",
      "location": "global"
    },
    "model_matrix": {
      "agent_task":    {"primary": "xai/grok-4.20-reasoning", "fallback": "claude-sonnet-4-6"},
      "repo_analysis": {"primary": "xai/grok-4.20-reasoning", "fallback": "claude-sonnet-4-6"},
      "code_large":    {"primary": "claude-sonnet-4-6",       "fallback": "gemini-3.1-pro-preview"},
      "reasoning":     {"primary": "claude-sonnet-4-6",       "fallback": "gemini-3.1-pro-preview"}
    },
    "tiers": {
      "xhigh": {"model": "claude-sonnet-4-6", "auto_execute": false}
    }
  },
  "observability": {
    "enabled": true,
    "exporter": "otlp",
    "endpoint": "localhost:4317"
  },
  "memory": {
    "vector_store": {"enabled": true, "top_k": 5}
  },
  "mcp": {
    "servers": {
      "filesystem": {"command": "npx", "args": ["mcp-server-filesystem", "./"]}
    }
  },
  "security": {
    "max_budget_daily": 3.3
  }
}
```

---

## 测试

```bash
python -m pytest tests/ -v                        # 全部测试
python -m pytest tests/test_router.py -v          # 路由引擎
python -m pytest tests/test_executor.py -v        # 执行管道
python -m pytest tests/test_memory.py -v          # 记忆系统
python -m pytest tests/test_security.py -v        # 安全防护
```

---

## 环境变量速查

| 变量 | 说明 |
|------|------|
| `ANTHROPIC_API_KEY` | Anthropic API Key |
| `ANTHROPIC_MODEL` | 覆盖所有路由，强制使用指定模型 |
| `ANTHROPIC_DEFAULT_SONNET_MODEL` | 自定义 Sonnet 版本 |
| `ANTHROPIC_DEFAULT_OPUS_MODEL` | 自定义 Opus 版本 |
| `ANTHROPIC_SMALL_FAST_MODEL` | side_query 使用的小模型 |
| `GIRAFFE_API_KEY` | 通用 API Key（config.json `${GIRAFFE_API_KEY}` 引用） |
| `GIRAFFE_USE_VERTEX` | 启用 Vertex AI Provider |
| `GIRAFFE_USE_BEDROCK` | 启用 AWS Bedrock Provider |
| `GIRAFFE_AVAILABLE_MODELS` | 逗号分隔的模型白名单 |
| `ANTHROPIC_CUSTOM_MODEL_OPTION` | 自定义模型（跳过验证） |

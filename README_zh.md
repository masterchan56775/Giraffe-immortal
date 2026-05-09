# Giraffe — 生产级 AI 运行时框架

DAG 执行引擎 | 多智能体 Swarm | 全链路 Telemetry | 多层记忆 | 自愈免疫 | 语义检索

---

## 框架介绍

Giraffe 是一个面向生产环境的 AI 应用运行时框架，用于解决直接调用大模型 API 时普遍存在的问题：调用失败无法自动恢复、对话上下文随会话丢失、复杂任务缺乏分解和协作能力、系统行为不可观测。

Giraffe 不是一个聊天机器人，而是一个**完整的 AI 调度和运维底座**。它接管了从用户输入到模型调用再到结果返回的全链路，并在每个环节植入了工程化能力：

- **调用可靠**：API 失败时，自愈系统自动匹配抗体规则，执行重试、模型降级或参数修正，无需人工干预
- **上下文持续**：多层记忆（内存 → JSON → SQLite → 向量库）确保关键信息跨会话留存，语义检索按相关度召回历史知识
- **任务可拆**：复杂指令经 DAG 引擎拆解为多节点有向图执行，支持条件分支、失败回退和断点续跑
- **协作可编排**：高复杂度任务自动触发多智能体 Swarm，多个专业角色轮流发言直到达成共识
- **全程可观测**：OpenTelemetry 追踪每个节点耗时，EventBus 将内部状态实时推送到前端

**适用场景**：需要稳定、可观测、具备自愈能力的 AI 后端服务，例如：智能客服、代码生成平台、自动化运维助手、多步骤工作流引擎。

**与开源 Agent 框架的关系**：Giraffe 可作为 [Open Claw](https://github.com/openclaw)、[Hermes](https://github.com/hermes) 等开源 Agent 框架的**可用性增强层**。这些框架在核心推理和工具调用上表现优秀，但在生产环境中普遍面临调用稳定性差、缺乏故障自愈、上下文管理粗糙、运行状态不可观测等问题。Giraffe 通过以下方式改善其可用性：

- **自愈兜底**：为 Agent 的 API 调用链路挂载抗体库，网络波动、限流、模型下线等故障自动修复，避免任务中断
- **记忆增强**：多层记忆 + 语义检索为 Agent 提供跨会话的持久化上下文，解决长任务中信息丢失的问题
- **流程编排**：DAG 引擎将 Agent 的单步调用升级为可断点续跑的多步骤工作流，CheckpointStore 确保长任务不因进程崩溃而丢失进度
- **运维可观测**：OpenTelemetry 追踪 + EventBus 实时推送，使 Agent 内部的每一步决策和工具调用对运维人员完全透明
- **协议桥接**：通过 MCPRegistry 和 HermesBridge，Giraffe 可直接对接这些框架暴露的 MCP Server，复用其工具能力的同时补齐稳定性短板

---

## 安装

### 方式一：pip 安装（推荐）

```bash
# 基础安装
pip install .

# 带向量检索
pip install ".[vector]"

# 带 MCP 协议
pip install ".[mcp]"

# 全部功能
pip install ".[all]"
```

安装完成后，终端直接输入 `giraffe` 即可使用。

### 方式二：源码运行

```bash
# 安装依赖
pip install opentelemetry-api opentelemetry-sdk opentelemetry-exporter-otlp
pip install fastapi uvicorn python-multipart

# 可选（缺失时自动降级）
pip install chromadb sentence-transformers   # 向量语义检索
pip install mcp                              # MCP 协议

# 直接运行
python giraffe.py
```

---

## 快速开始

### 1. 初始化配置

首次使用时，运行 `--init` 将默认配置复制到用户目录 `~/.giraffe/`：

```bash
giraffe --init
```

输出：

```
正在初始化 Giraffe 用户配置...

  ✅ 配置文件 → ~/.giraffe/config.json
  ✅ 能力注册表 → ~/.giraffe/feature_registry.json

初始化完成。请编辑 ~/.giraffe/config.json 填入 API Key。
```

### 2. 配置 API Key

编辑 `~/.giraffe/config.json`，填入模型 API 密钥。支持 `${ENV_VAR}` 引用环境变量：

```json
{
  "router": {
    "primary_model": {
      "api_key": "${MIMO_API_KEY}",
      "base_url": "https://token-plan-cn.xiaomimimo.com/v1"
    }
  }
}
```

或在项目根目录（或 `~/.giraffe/`）创建 `.env` 文件，直接写入密钥，无需修改 config.json：

```bash
# .env
MIMO_API_KEY=sk-xxxxxxxxxxxxxxxxxxxxxxxx
```

系统启动时自动加载 `.env`，config.json 中的 `${MIMO_API_KEY}` 会被替换为实际值。

配置文件查找优先级：`--config 显式指定` > `当前目录 config.json` > `~/.giraffe/config.json` > 包内默认。

### 3. 启动

```bash
# 交互模式 — 终端对话，输入 /help 查看所有命令
giraffe

# Web 服务模式 — 启动 FastAPI，提供 REST / WebSocket / SSE 接口
giraffe --serve

# 路由测试 — 查看系统如何为一条消息选择模型，不产生 API 调用
giraffe --test-route "帮我设计一个系统架构"

# 系统健康检查
giraffe --health

# 触发进化引擎
giraffe --evolve

# 查看版本
giraffe --version
```

源码运行时将 `giraffe` 替换为 `python giraffe.py` 即可。

---

## 系统架构

```
用户输入 / HTTP / WebSocket
        ↓
┌─────────────────────────────────────────────────────────────┐
│  Observability  全链路 Telemetry (OpenTelemetry + OTLP)      │
│  EventBus       进程内事件总线 → SSE / WebSocket 实时推送    │
└───────────────────────┬─────────────────────────────────────┘
                        ↓
① Core 配置中心     GiraffeConfig / AppState / TaskManager
                    CreditMonitor / SkillReviewer
                        ↓
② Router 路由引擎   关键词(<1ms) + LLM 慢路径(~200ms)
                    五档准入 × 9×3 模型矩阵
                    → 复杂任务触发 Swarm 路径
                        ↓
              ┌─────────┴──────────┐
              ↓                    ↓
    ③-A 单模型 Pipeline         ③-B Swarm 多智能体
    DAG GraphEngine              SwarmOrchestrator
    8节点有向图执行              Architect→Coder→Reviewer
    CheckpointStore              EventBus 实时广播各角色发言
    断点续跑 / 回滚
              └─────────┬──────────┘
                        ↓
④ Memory 多层记忆   短期(内存) / 事实(JSON) / 长期(SQLite) / 结构化
                    VectorStore 语义检索 (ChromaDB, 优雅降级)
                        ↓
⑤ SelfHeal 自愈    8 内置抗体 → 10步排查 → EvolutionEngine
                   AntibodyLibrary 磁盘持久化 + 动态进化
                        ↓
⑥ Security 安全    P0/P1/P2 三级审批 + 3护栏 + Token追踪
                        ↓
⑦ Integration      GatewayAPI / MCPRegistry / HermesBridge
                   WebServer(FastAPI) / EventStream(SSE+WS)
                   Multimodal(图像 Base64 透传)
                        ↓
⑧ Executor 执行管道 CircuitBreaker / ResponseCache / TaskDecomposer
                    MicroCompact / DeepCompact / ParallelExecutor
                    ProgressiveSkillLoader / DeferredToolLoader
                        ↓
⑨ Skills/Workflow   SkillLoader(动态加载) / SkillReviewer(评分/查重/截断)
                    WorkflowEngine(暂停/恢复/CheckpointJSON)
                        ↓
⑩ Adapt + Sandbox   HermesAdapter(自动修复配置差异) / SandboxExecutor
```

---

## 子系统详解

### DAG 执行引擎（graph/）

传统流水线是固定的 8 步顺序执行。Giraffe 将其重构为有向图（DAG），每个阶段对应一个 `Node` 子类。`GraphEngine` 按照注册的边进行状态流转，支持条件分支和反循环保护。

**执行流程**：

```
DecomposeNode → ApprovalNode → MicroCompactNode → CreditCheckNode
                                                        ↓
                                               APICallNode ←──┐
                                                   ↓          │
                                              [成功?]         │
                                              ↓     ↓         │
                                            是    否(错误)     │
                                            ↓       ↓         │
                                     DeepCompactNode SelfHealNode
                                            ↓       ↓
                                       CacheNode  [重试次数<3?]
                                                   是 → 回到 APICallNode
                                                   否 → 返回降级结果
```

**断点续跑**：每个节点执行后，`CheckpointStore`（SQLite）自动保存 `(trace_id, node_name, step_index, state_json)` 快照。进程意外终止后，调用 `GraphEngine.resume(trace_id)` 即可从最后完成的节点继续执行。`rollback(trace_id, step_index)` 支持回滚到任意历史步骤。

---

### 多智能体 Swarm（swarm/）

当路由引擎判断任务复杂度达到 `high` 级别（如大型代码生成、系统架构设计），系统自动将请求分流到 `SwarmOrchestrator` 进行多角色协作。

**内置角色**：

| 角色 | 模型偏好 | Temperature | 职责 |
|------|---------|-------------|------|
| Architect | 高推理模型 | 0.3 | 分析需求、设计方案、拆解任务 |
| Coder | 编码模型 | 0.2 | 根据方案编写代码 |
| Reviewer | 审查模型 | 0.1 | 检查质量、安全漏洞，输出 APPROVED 或修改意见 |
| Tester | 默认模型 | 0.3 | 设计测试用例、执行测试 |

**协作流程**：Architect 先输出方案 → Coder 根据方案编写代码 → Reviewer 审查。若 Reviewer 未输出 `APPROVED`，则携带审查意见回到 Coder 重修。最大 5 轮（可配置）。每轮发言通过 `EventBus` 实时广播，前端可通过 SSE/WebSocket 展示各角色的思考过程。

---

### 多层记忆系统（memory/）

| 层级 | 存储介质 | 生命周期 | 用途 |
|------|---------|---------|------|
| 短期记忆 | 内存 LRU | 当前会话 | 保持对话上下文连贯 |
| 事实记忆 | JSON 文件 | 持久化 | 自动提取的结构化知识（如"用户偏好 Python"） |
| 长期记忆 | SQLite | 持久化 | 全量对话历史，支持关键词检索 |
| 语义记忆 | ChromaDB | 持久化 | 基于 Embedding 的向量相似度召回 |

**混合检索**：`MemorySystem.semantic_search()` 先从向量库召回 top_k 候选，再与关键词检索结果合并去重，按综合分数排序。检索结果自动注入到系统提示词中，为模型提供精准的历史上下文。

**自动事实提取**：`AutoExtract` 模块通过正则规则从每轮对话中提取事实（如姓名、偏好、技术栈），写入事实记忆和向量库。

**优雅降级**：若 ChromaDB 未安装，系统自动退化为纯关键词检索，不影响基础功能。

---

### 自愈免疫系统（self_heal/）

Giraffe 将 API 调用失败视为「感染」，通过类似生物免疫系统的机制自动修复。

**10 步排查流程**：

1. 捕获异常 → 2. 分类错误类型 → 3. 查找匹配抗体 → 4. 执行修复动作（重试/降级/切换模型）→ 5. 验证修复结果 → 6. 记录成功的修复模式 → 7. 更新抗体优先级 → 8. 清理过期抗体 → 9. 通过 EventBus 广播自愈事件 → 10. 返回修复后的结果或最终降级响应

**8 种内置抗体**：

| 抗体 | 匹配模式 | 修复动作 |
|------|---------|---------|
| 网络超时 | `timeout`, `connect` | 指数退避重试 |
| 速率限制 | `429`, `rate_limit` | 等待后重试 |
| 模型不可用 | `model_not_found` | 切换到备用模型 |
| 余额不足 | `insufficient_quota` | 切换到免费模型 |
| 上下文溢出 | `context_length` | 触发深度压缩后重试 |
| JSON 解析 | `json`, `parse` | 添加格式约束后重试 |
| 权限拒绝 | `permission`, `403` | 降级到低权限模型 |
| 服务不可用 | `503`, `502` | 等待 + 重试 |

**进化引擎**：`EvolutionEngine` 定期分析历史错误日志，自动生成新抗体规则并淘汰长期无效的旧规则。调用 `/evolve` 命令可手动触发。

---

### 路由引擎（router/）

系统使用双路径路由策略确定每条消息的处理方式：

1. **快路径**（<1ms）：基于关键词和正则的意图分类器，处理明确意图的请求
2. **慢路径**（~200ms）：当快路径置信度不足时，调用 LLM 进行精确分类

路由结果包含：任务类型（chat/code/reasoning/vision）、复杂度（low/medium/high）、模型选择、是否触发 Swarm。

**五档准入控制**：

| 档位 | 比例 | 自动执行 | 成本上限 | 典型任务 |
|------|------|---------|---------|---------|
| nano | 40% | ✅ | $0.01 | 闲聊/搜索 |
| low | 40% | ✅ | $0.05 | 代码/视觉 |
| medium | 15% | ❌  | $1.00 | 大型代码/重构 |
| high | 4% | ❌  | $5.00 | 复杂推理 |
| xhigh | 1% | ❌  | $10.00 | 多模型协作 |

---

### 可观测性（observability/）

所有关键路径（流水线 8 阶段、路由决策、自愈重试、Swarm 发言）均通过 OpenTelemetry 创建 Span。

- `@traced` 装饰器：一行代码即可为任意函数添加追踪
- EventBus 事件类型：`stage_start`, `stage_end`, `token_chunk`, `self_heal_attempt`, `swarm_turn`
- 生产环境可对接 Jaeger / Zipkin 等后端查看完整 Trace 链

---

## 扩展开发

### 添加自定义技能

在 `skills/` 目录创建 `skill_` 前缀的 Python 文件，系统启动时自动加载：

```python
# skills/skill_weather.py

SKILL_NAME = "天气查询"

def execute(city: str) -> str:
    """查询指定城市的天气。"""
    # 实际实现：调用天气 API
    return f"{city}：晴，25°C"
```

`SkillReviewer` 会自动为新技能评分（基于内容长度、是否包含示例、使用频次）。评分低于阈值且超过 30 天未使用的技能会被自动清理。

### 添加 MCP 工具服务

在 `config.json` 的 `mcp.servers` 段注册新的 MCP Server：

```json
{
  "mcp": {
    "servers": {
      "filesystem": {
        "command": "npx",
        "args": ["mcp-server-filesystem", "./"]
      },
      "github": {
        "command": "npx",
        "args": ["mcp-server-github"]
      }
    }
  }
}
```

系统启动时通过 `MCPRegistry` 自动连接所有配置的 Server，将其工具集注入到模型调用的 `tools` 参数中。模型可自主决定是否调用外部工具。

### 注册生命周期钩子

`HookSystem` 提供 7 个生命周期事件，可用于日志、监控或自定义逻辑注入：

```python
from integration.hooks import HookSystem

hooks = HookSystem()
hooks.register("on_before_api_call", lambda ctx: print(f"即将调用 {ctx['model']}"))
hooks.register("on_after_api_call",  lambda ctx: print(f"耗时 {ctx['duration_ms']}ms"))
hooks.register("on_error",           lambda ctx: print(f"错误: {ctx['error']}"))
```

### 自定义抗体规则

在代码中动态添加针对特定业务场景的抗体：

```python
from self_heal.antibody import AntibodyLibrary, Antibody

lib = AntibodyLibrary()
lib.add(Antibody(
    name="custom_db_error",
    pattern=r"database.*connection.*refused",
    action="retry",
    description="数据库连接被拒绝时自动重试",
    priority=8,
))
lib.save()  # 持久化到磁盘
```

---

## CLI 命令

| 命令 | 说明 |
|------|------|
| `/health` | 系统健康诊断（内存/路由/流水线/抗体库/Token预算） |
| `/memory` | 多层记忆摘要（短期/事实/长期/结构化/向量库） |
| `/credit` | 信用监控状态（API是否欠费/是否处于兜底模式） |
| `/topup` | 确认已充值，切回三方API |
| `/evolve` | 触发进化引擎（分析历史错误，优化抗体库） |
| `/route <消息>` | 测试路由决策，不实际调用API |
| `/antibody` | 抗体库统计（8内置 + 自动生成数量） |
| `/token` | Token预算追踪（日/月用量与限额） |
| `/stats` | 执行流水线统计（总调用/成功率/缓存命中） |
| `/fusion` | AutoFusion 引擎状态 |
| `/help` | 显示完整命令列表 |
| `/quit` | 退出 |

---

## API 端点（`--serve` 模式）

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/chat` | POST | 发送消息，返回 SSE 流。支持 `multipart/form-data` 上传图片 |
| `/api/events` | GET | SSE 订阅实时事件流（流水线阶段、Swarm 发言、自愈进度） |
| `/ws/chat` | WS | 全双工 WebSocket，token 级流式响应 |
| `/api/health` | GET | 系统健康状态 JSON |

**调用示例**：

```bash
# 发送文本消息
curl -X POST http://localhost:8000/api/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "写一个快速排序"}'

# 发送图片（多模态）
curl -X POST http://localhost:8000/api/chat \
  -F "message=描述这张图片" \
  -F "images=@photo.jpg"

# 监听实时事件
curl -N http://localhost:8000/api/events
```

---

## 完整配置参考

```json
{
  "router": {
    "primary_model": {
      "api_key": "${MIMO_API_KEY}",
      "base_url": "https://token-plan-cn.xiaomimimo.com/v1"
    }
  },
  "observability": {
    "enabled": true,
    "exporter": "otlp",
    "endpoint": "localhost:4317",
    "service_name": "giraffe"
  },
  "memory": {
    "vector_store": {
      "enabled": true,
      "embedding_model": "all-MiniLM-L6-v2",
      "top_k": 5
    }
  },
  "mcp": {
    "servers": {
      "filesystem": { "command": "npx", "args": ["mcp-server-filesystem", "./"] }
    }
  },
  "swarm": {
    "enabled": true,
    "max_rounds": 5,
    "roles": ["architect", "coder", "reviewer"],
    "trigger_complexity": "high"
  },
  "security": {
    "max_budget_daily": 3.3
  },
  "credit_monitor": {
    "enabled": true
  }
}
```

---

## 测试

```bash
# 运行全部 429 个测试用例
python -m pytest tests/ -v

# 单模块测试
python -m pytest tests/test_executor.py -v         # 执行管道基础
python -m pytest tests/test_graph.py -v            # DAG 引擎 (35)
python -m pytest tests/test_swarm.py -v            # Swarm (21)
python -m pytest tests/test_memory.py -v           # 记忆系统基础
python -m pytest tests/test_memory_robust.py -v    # 记忆系统健壮性 (58)
python -m pytest tests/test_selfheal_robust.py -v  # 自愈 + EventBus 健壮性 (70)
python -m pytest tests/test_skills.py -v           # Skill 全模块 (74)
python -m pytest tests/test_observability.py -v    # Telemetry
python -m pytest tests/test_phase2.py -v           # VectorStore / MCP
python -m pytest tests/test_router.py -v           # 路由引擎
python -m pytest tests/test_security.py -v         # 安全防护
python -m pytest tests/test_integration.py -v      # 集成与工作流
```

---

## 文件结构

```
giraffe/
├── giraffe.py                  # 主入口 (CLI + --serve 网关)
├── config.json                 # 全局配置（支持环境变量）
├── auto_fusion.py              # 自动融合引擎
├── feature_registry.json       # 能力注册表
│
├── observability/              # 全链路可观测性
│   └── tracer.py               #   OpenTelemetry Tracer + @traced 装饰器
│
├── core/                       # 配置与状态中心
│   ├── config.py               #   GiraffeConfig（环境变量 / config.json 解析）
│   ├── state.py                #   AppState 全局单例
│   ├── task_manager.py         #   任务管理
│   ├── credit_monitor.py       #   API 信用监控与兜底切换
│   └── skill_reviewer.py       #   技能评分 / Jaccard 查重 / 过期截断
│
├── router/                     # 路由引擎
│   ├── engine.py               #   RouterEngine（双路径 + Swarm 触发）
│   ├── intent_classifier.py    #   关键词意图分类
│   ├── llm_classifier.py       #   LLM 慢路径分类
│   ├── model_registry.py       #   9×3 模型矩阵
│   ├── query_complexity.py     #   复杂度评估
│   ├── gatekeeper.py           #   五档准入控制
│   └── subagent_router.py      #   子 Agent 路由
│
├── executor/                   # 执行管道
│   ├── pipeline.py             #   ExecutorPipeline（DAG GraphEngine 驱动）
│   ├── circuit_breaker.py      #   熔断器（CLOSED → OPEN → HALF_OPEN）
│   ├── response_cache.py       #   响应缓存（LRU + TTL + 磁盘持久化）
│   ├── task_decomposer.py      #   多步骤任务分解
│   ├── micro_compact.py        #   微压缩（>500 字截断）
│   ├── deep_compact.py         #   深度压缩（>20 条滑动窗口）
│   ├── parallel_executor.py    #   并行子 Agent 执行
│   ├── skill_loader.py         #   技能动态加载（skill_*.py）
│   ├── progressive_loader.py   #   渐进式技能缓存（优先级提升）
│   └── deferred_tool_loader.py #   延迟工具加载（18 内置工具）
│
├── graph/                      # DAG 执行引擎
│   ├── state.py                #   GraphState 不可变状态
│   ├── node.py                 #   Node 抽象 + 8 个节点子类
│   ├── engine.py               #   GraphEngine（条件边 / checkpoint）
│   ├── checkpoint.py           #   CheckpointStore（SQLite 断点续跑）
│   └── nodes/
│       └── swarm_node.py       #   SwarmNode（DAG 内嵌 Swarm）
│
├── swarm/                      # 多智能体集群
│   ├── agent.py                #   AgentProfile + Agent.think()
│   ├── profiles.py             #   ARCHITECT / CODER / REVIEWER / TESTER
│   └── orchestrator.py         #   SwarmOrchestrator 多轮编排
│
├── memory/                     # 多层记忆
│   ├── memory_system.py        #   MemorySystem 门面
│   ├── structured_memory.py    #   结构化事实（JSON）
│   ├── auto_extract.py         #   自动事实提取
│   ├── memory_refiner.py       #   记忆精炼（去重 / 置信度）
│   ├── vector_store.py         #   VectorStore（ChromaDB）
│   └── diary.py                #   会话日记
│
├── self_heal/                  # 自愈免疫
│   ├── antibody.py             #   AntibodyLibrary（8 内置 + 持久化）
│   ├── error_processor.py      #   ErrorProcessor 10 步排查
│   ├── evolution.py            #   EvolutionEngine 抗体进化
│   ├── fault_playbook.py       #   FaultPlaybook 分类手册
│   └── skill_crystallizer.py   #   技能结晶化
│
├── security/                   # 安全防护
│   ├── approval.py             #   P0/P1/P2 三级审批
│   ├── guardrail_middleware.py #   3 护栏
│   ├── token_tracker.py        #   Token 预算追踪
│   └── permission_system.py    #   权限系统
│
├── integration/                # 集成与网关
│   ├── web_server.py           #   FastAPI（REST / WS / SSE）
│   ├── event_stream.py         #   EventBus 事件总线
│   ├── gateway_api.py          #   GatewayAPI 单例
│   ├── mcp_client.py           #   MCPClient
│   ├── mcp_registry.py         #   MCPRegistry 连接池
│   ├── multimodal.py           #   多模态 Base64 / Vision
│   ├── hermes_bridge.py        #   HermesBridge → MCPRegistry
│   ├── hooks.py                #   HookSystem 7 生命周期钩子
│   ├── cron_sync.py            #   定时同步
│   └── startup.py              #   启动管理器
│
├── adapt/                      # 自动适配
│   ├── adapter.py              #   HermesAdapter
│   ├── scanner.py              #   HermesScanner
│   └── compat_report.py        #   兼容性报告
│
├── sandbox/                    # 沙箱执行
│   ├── manager.py              #   SandboxManager
│   └── executor.py             #   SandboxExecutor
│
├── workflow/                   # 工作流引擎
│   ├── engine.py               #   WorkflowEngine（暂停 / 恢复）
│   └── step.py                 #   WorkflowStep 状态机
│
├── skills/                     # 动态技能目录
│   └── skill_example.py        #   示例：文本转大写
│
├── plugins/                    # 插件配置
├── data/                       # 运行时数据（自动创建）
```

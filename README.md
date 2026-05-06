# Giraffe — 生产级 AI 运行时框架

DAG 执行引擎 | 多智能体 Swarm | 全链路 Telemetry | 四层记忆 | 自愈免疫 | 语义检索

---

## 快速启动

```bash
# 交互模式（默认）
python giraffe.py

# 生产网关模式（FastAPI + WebSocket）
python giraffe.py --serve

# 路由决策测试（不调用 API）
python giraffe.py --test-route "帮我设计一个系统架构"

# 系统健康检查
python giraffe.py --health

# 触发进化引擎
python giraffe.py --evolve
```

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
④ Memory 四层记忆   短期(内存) / 事实(JSON) / 长期(SQLite) / 结构化
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

## CLI 命令

| 命令 | 说明 |
|------|------|
| `/health` | 系统健康诊断（内存/路由/流水线/抗体库/Token预算） |
| `/memory` | 四层记忆摘要（短期/事实/长期/结构化/向量库） |
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
| `/api/chat` | POST | 发送消息，返回 SSE 流（支持 multipart 图片上传） |
| `/api/events` | GET | SSE 订阅实时事件流 |
| `/ws/chat` | WS | 全双工 WebSocket，token 级流式响应 |
| `/api/health` | GET | 系统健康状态 JSON |

---

## 配置文件 config.json

```json
{
  "router.primary_model.api_key": "${MIMO_API_KEY}",
  "router.primary_model.base_url": "https://...",
  "observability": {
    "enabled": true,
    "endpoint": "localhost:4317",
    "service_name": "giraffe"
  },
  "memory": {
    "vector_store": { "enabled": true, "top_k": 5 }
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
  }
}
```

支持 `${ENV_VAR}` 环境变量引用。

---

## 五档路由

| 档位 | 比例 | 自动执行 | 成本上限 | 典型任务 |
|------|------|---------|---------|---------|
| 日常 (daily) | 40% | ✅ | $0.01 | 闲聊/搜索 |
| 中等 (medium) | 40% | ✅ | $0.05 | 代码/视觉 |
| 深度 (deep) | 15% | ❌ 需确认 | $1.00 | 大型代码/重构 |
| 大神 (master) | 4% | ❌ 必须确认 | $5.00 | 复杂推理 |
| 真神 (divine) | 1% | ❌ 必须确认 | $10.00 | 多模型协作 |

---

## 测试

```bash
# 运行全部 429 个测试用例
python -m pytest tests/ -v

# 单模块测试
python -m pytest tests/test_memory_robust.py -v   # 记忆系统健壮性 (58)
python -m pytest tests/test_selfheal_robust.py -v # 自愈+EventBus (70)
python -m pytest tests/test_skills.py -v           # Skill全模块 (74)
python -m pytest tests/test_graph.py -v            # DAG引擎 (35)
python -m pytest tests/test_swarm.py -v            # Swarm (21)
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
│   └── tracer.py               # OpenTelemetry Tracer + @traced 装饰器
│
├── core/                       # 配置与状态中心
│   ├── config.py               # GiraffeConfig（环境变量/config.json 解析）
│   ├── state.py                # AppState 全局单例
│   ├── task_manager.py         # 任务管理
│   ├── credit_monitor.py       # API 信用监控
│   └── skill_reviewer.py       # 技能评分/查重/截断（Jaccard 相似度）
│
├── router/                     # 路由引擎
│   ├── engine.py               # RouterEngine（双路径路由 + Swarm 触发判断）
│   ├── intent_classifier.py    # 意图分类
│   ├── llm_classifier.py       # LLM 慢路径分类
│   ├── model_registry.py       # 9×3 模型矩阵
│   ├── query_complexity.py     # 复杂度评估
│   ├── gatekeeper.py           # 五档准入控制
│   └── subagent_router.py      # 子Agent路由
│
├── executor/                   # 执行管道
│   ├── pipeline.py             # ExecutorPipeline（DAG GraphEngine 驱动）
│   ├── circuit_breaker.py      # 熔断器（CLOSED→OPEN→HALF_OPEN 状态机）
│   ├── response_cache.py       # 响应缓存（LRU + TTL + 磁盘持久化）
│   ├── task_decomposer.py      # 多步骤任务分解
│   ├── micro_compact.py        # 微压缩（单条消息 >500字 截断）
│   ├── deep_compact.py         # 深度压缩（对话 >20条 滑动窗口）
│   ├── parallel_executor.py    # 并行子Agent执行（ThreadPoolExecutor）
│   ├── skill_loader.py         # 技能动态加载（skill_*.py 前缀）
│   ├── progressive_loader.py   # 渐进式技能缓存（优先级自动提升）
│   └── deferred_tool_loader.py # 延迟工具加载（18内置工具）
│
├── graph/                      # DAG 执行引擎
│   ├── state.py                # GraphState（不可变流转状态）
│   ├── node.py                 # Node 抽象 + 8个具体节点子类
│   ├── engine.py               # GraphEngine（条件边/反循环保护/checkpoint）
│   ├── checkpoint.py           # CheckpointStore（SQLite 断点续跑/回滚）
│   └── nodes/
│       └── swarm_node.py       # SwarmNode（DAG 内嵌 Swarm 讨论）
│
├── swarm/                      # 多智能体集群
│   ├── agent.py                # AgentProfile + Agent.think()
│   ├── profiles.py             # 预置角色：ARCHITECT/CODER/REVIEWER/TESTER
│   └── orchestrator.py         # SwarmOrchestrator（多轮讨论编排）
│
├── memory/                     # 四层记忆架构
│   ├── memory_system.py        # MemorySystem 门面（单例）
│   ├── structured_memory.py    # 结构化事实记忆（JSON持久化）
│   ├── auto_extract.py         # 自动事实提取（正则规则）
│   ├── memory_refiner.py       # 记忆精炼（去重/置信度保留）
│   ├── vector_store.py         # VectorStore（ChromaDB，优雅降级）
│   └── diary.py                # 会话日记
│
├── self_heal/                  # 自愈免疫系统
│   ├── antibody.py             # AntibodyLibrary（8内置抗体 + 磁盘持久化）
│   ├── error_processor.py      # ErrorProcessor（10步排查 + 模型降级链）
│   ├── evolution.py            # EvolutionEngine（自动优化/生成/淘汰抗体）
│   ├── fault_playbook.py       # FaultPlaybook（分类处置手册）
│   └── skill_crystallizer.py   # 技能结晶化
│
├── security/                   # 安全防护
│   ├── approval.py             # P0/P1/P2 三级审批
│   ├── guardrail_middleware.py # 3护栏（危险命令/密钥泄露/预算）
│   ├── token_tracker.py        # Token预算追踪
│   └── permission_system.py    # 权限系统
│
├── integration/                # 集成与网关
│   ├── web_server.py           # FastAPI 服务（/api/chat, /ws/chat, /api/events）
│   ├── event_stream.py         # EventBus（进程内事件总线 + SSE/WS 推送）
│   ├── gateway_api.py          # GatewayAPI 单例
│   ├── mcp_client.py           # MCPClient（MCP 协议客户端）
│   ├── mcp_registry.py         # MCPRegistry（多 Server 连接池）
│   ├── multimodal.py           # 多模态（图像 Base64 编码/Vision content 构建）
│   ├── hermes_bridge.py        # HermesBridge（委托 MCPRegistry）
│   ├── hooks.py                # HookSystem（7生命周期钩子）
│   ├── cron_sync.py            # 定时同步
│   └── startup.py              # 启动管理器
│
├── adapt/                      # 自动适配
│   ├── adapter.py              # HermesAdapter（自动修复配置差异）
│   ├── scanner.py              # HermesScanner
│   └── compat_report.py        # 兼容性报告
│
├── sandbox/                    # 沙箱执行
│   ├── manager.py              # SandboxManager（Docker/本地降级）
│   └── executor.py             # SandboxExecutor
│
├── workflow/                   # 工作流引擎
│   ├── engine.py               # WorkflowEngine（暂停/恢复/checkpoint）
│   └── step.py                 # WorkflowStep + StepStatus 状态机
│
├── skills/                     # 动态技能目录
│   └── skill_example.py        # 示例：文本转大写
│
├── plugins/                    # 插件配置目录
│   ├── giraffe-full/
│   ├── disk-cleanup/
│   ├── kanban/
│   └── observability/
│
├── data/                       # 运行时数据（自动创建）
│   └── memory.db               # SQLite 长期记忆 + checkpoint
│
└── tests/                      # 429 个测试用例
    ├── test_executor.py         # 执行管道基础测试
    ├── test_graph.py            # DAG引擎 (35)
    ├── test_swarm.py            # Swarm (21)
    ├── test_memory.py           # 记忆系统基础
    ├── test_memory_robust.py    # 记忆系统健壮性 (58)
    ├── test_observability.py    # Telemetry
    ├── test_phase2.py           # VectorStore/MCP
    ├── test_router.py           # 路由引擎
    ├── test_security.py         # 安全防护
    ├── test_self_heal.py        # 自愈系统基础
    ├── test_selfheal_robust.py  # 自愈+EventBus健壮性 (70)
    ├── test_skills.py           # Skill全模块 (74)
    └── test_integration.py      # 集成与工作流
```

---

## 依赖安装

```bash
# 核心依赖
pip install opentelemetry-api opentelemetry-sdk opentelemetry-exporter-otlp
pip install fastapi uvicorn python-multipart

# 可选：语义检索（无则降级为关键词检索）
pip install chromadb sentence-transformers

# 可选：MCP 工具协议
pip install mcp
```

---

## 设计原则

- **优雅降级**：ChromaDB / Ollama / MCP Server 缺失时静默禁用，基础 CLI 链路始终可用
- **单向数据流**：`GraphState` 不可变，每节点返回新状态
- **零停机自愈**：所有 API 调用挂载 `ErrorProcessor`，通过重试/降级/抗体修复实现自愈
- **实时可见**：Swarm 协作、流水线阶段切换、自愈尝试均通过 `EventBus` 实时广播

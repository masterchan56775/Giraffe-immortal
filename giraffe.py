"""
Giraffe — 主入口

启动系统并进入交互循环。
"""
from __future__ import annotations

import os
# 在任何第三方库导入前设置，彻底静默 HuggingFace Hub 相关噪声日志
# 项目不直接使用 HF Hub，警告来自 sentence-transformers 的副作用
os.environ.setdefault("HF_HUB_VERBOSITY", "error")     # 压制 huggingface_hub 的 WARNING 及以下
os.environ.setdefault("TOKENIZERS_PARALLELISM", "false") # 禁止 tokenizers fork 警告
os.environ.setdefault("TRANSFORMERS_NO_ADVISORY_WARNINGS", "1")  # 禁止 transformers 建议性警告


import argparse
import logging
from pathlib import Path

# 项目根目录
BASE_DIR = Path(__file__).parent

# ─── 日志配置（集中管理，详见 observability/logging_config.py）────────────────
# 注意：logging.basicConfig 已移除，统一使用 setup_logging()
# 此处仅获取 logger，实际配置在 main() 中完成
logger = logging.getLogger("giraffe")

# ─── 导入各模块 ───────────────────────────────────────────────────────────────
from core.config import GiraffeConfig
from core.state import AppState
from core.task_manager import TaskManager
from core.credit_monitor import CreditMonitor
from router.engine import RouterEngine
from router.model_registry import ModelRegistry
from executor.pipeline import ExecutorPipeline, ExecutionContext
from executor.circuit_breaker import CircuitBreakerRegistry
from memory.memory_system import MemorySystem
from self_heal.antibody import AntibodyLibrary
from self_heal.error_processor import ErrorProcessor
from self_heal.evolution import EvolutionEngine
from security.approval import ApprovalSystem
from security.guardrail_middleware import GuardrailMiddleware
from security.token_tracker import TokenTracker
from integration.gateway_api import GatewayAPI
from integration.hooks import HookSystem
from integration.startup import StartupManager
from integration.event_stream import EventBus
from observability.tracer import get_tracer, init_tracer
from auto_fusion import AutoFusionEngine

# ─── Giraffe 系统类 ────────────────────────────────────────────────────────────
class Giraffe:
    """
    Giraffe主控类。
    协调所有模块的初始化和交互循环。
    """

    BANNER = """
╔═══════════════════════════════════════════════════════════╗
║   Giraffe  v1.9.5                                         ║
║   DAG · Swarm · Telemetry · Memory · SelfHeal             ║
╚═══════════════════════════════════════════════════════════╝
"""

    def __init__(self, config_path: Path | str | None = None) -> None:
        self._config_path = Path(config_path) if config_path else BASE_DIR / "config.json"
        self._initialized = False

        # 核心组件（在 initialize() 中初始化）
        self.config: GiraffeConfig | None = None
        self.state: AppState | None = None
        self.task_manager: TaskManager | None = None
        self.credit_monitor: CreditMonitor | None = None
        self.router: RouterEngine | None = None
        self.pipeline: ExecutorPipeline | None = None
        self.memory: MemorySystem | None = None
        self.antibody_lib: AntibodyLibrary | None = None
        self.error_processor: ErrorProcessor | None = None
        self.evolution_engine: EvolutionEngine | None = None
        self.approval: ApprovalSystem | None = None
        self.guardrails: GuardrailMiddleware | None = None
        self.token_tracker: TokenTracker | None = None
        self.gateway: GatewayAPI | None = None
        self.hooks: HookSystem | None = None
        self.auto_fusion: AutoFusionEngine | None = None
        self.mcp_registry = None
        self.swarm_orchestrator = None  # Swarm 群组讨论编排器

    # ─── 初始化 ───────────────────────────────────────────────────────────────
    def initialize(self) -> None:
        """启动系统，按顺序初始化所有模块。"""
        print(self.BANNER)

        startup = StartupManager()

        # 注册启动任务（有序执行）
        startup.register("可观测性",     self._init_observability, order=5)
        startup.register("配置中心",     self._init_core,          order=10)
        startup.register("路由引擎",     self._init_router,        order=20)
        startup.register("执行管道",     self._init_executor,      order=30)
        startup.register("记忆系统",     self._init_memory,        order=40)
        startup.register("自愈系统",     self._init_self_heal,     order=50)
        startup.register("安全防护",     self._init_security,      order=60)
        startup.register("网关集成",     self._init_gateway,       order=70)
        startup.register("自动融合引擎", self._init_auto_fusion,   order=80)
        startup.register("统计追踪",     self._init_stats,         order=85)

        results = startup.run_all()

        failed = [k for k, v in results.items() if v.startswith("error")]
        if failed:
            logger.warning(f"⚠️  以下模块初始化失败: {', '.join(failed)}")
        else:
            logger.info("✅ 所有模块初始化成功")

        self._initialized = True
        session_id = self.state.initialize()
        logger.info(f"🚀 会话启动: {session_id}")
        # Stats 会话开始
        try:
            from observability.stats import get_tracker
            get_tracker().start_session(session_id)
        except Exception:
            pass

    def _init_observability(self) -> None:
        """读取配置并初始化链路追踪。必须最先执行，其他模块可以立即使用tracer。"""
        # 此阶段 self.config 尚未初始化，直接读取配置文件
        import json
        try:
            cfg_path = self._config_path
            with open(cfg_path, "r", encoding="utf-8") as f:
                raw = json.load(f)
            obs_cfg = raw.get("observability", {})
        except Exception:
            obs_cfg = {}

        if obs_cfg.get("enabled", False):
            init_tracer(
                service_name=obs_cfg.get("service_name", "giraffe"),
                endpoint=obs_cfg.get("endpoint", ""),
                console_export=obs_cfg.get("console_export", False),
            )
        else:
            logger.debug("[Observability] 链路追踪未启用（enabled=false）")

    def _init_core(self) -> None:
        self.config = GiraffeConfig.get(self._config_path)
        self.state = AppState.get()
        self.task_manager = TaskManager.get()

        # 信用监控
        self.credit_monitor = CreditMonitor.get(self.config.credit_monitor)
        primary_model_cfg = self.config.primary_model
        self.credit_monitor.set_primary_model_config(primary_model_cfg)

    def _init_router(self) -> None:
        registry = ModelRegistry.get()
        self.router = RouterEngine(config=self.config.router, model_registry=registry)

    def _init_executor(self) -> None:
        data_dir = BASE_DIR / "data"
        self.pipeline = ExecutorPipeline(
            config={"compression": self.config.compression,
                    "executor": self.config.executor,
                    "router": self.config.router},
            data_dir=data_dir,
        )
        self.pipeline.set_credit_monitor(self.credit_monitor)

        # 熔断器配置
        cb_cfg = self.config.router.get("circuit_breaker", {})
        CircuitBreakerRegistry.get().configure(cb_cfg)

    def _init_memory(self) -> None:
        data_dir = BASE_DIR / "data"
        self.memory = MemorySystem.get(data_dir=data_dir, config=self.config.memory_cfg)

    def _init_self_heal(self) -> None:
        data_dir = BASE_DIR / "data"
        antibody_path = data_dir / "antibodies.json"
        self.antibody_lib = AntibodyLibrary.get()
        self.antibody_lib._persist_path = antibody_path

        self.error_processor = ErrorProcessor(
            antibody_lib=self.antibody_lib,
            circuit_breaker_registry=CircuitBreakerRegistry.get(),
        )
        self.evolution_engine = EvolutionEngine(antibody_lib=self.antibody_lib)

    def _init_security(self) -> None:
        self.approval = ApprovalSystem(
            approval_mode=self.config.security.get("approval_mode", "confirm")
        )
        self.guardrails = GuardrailMiddleware(config=self.config.security)
        self.token_tracker = TokenTracker.get()
        # 读取预算配置，防御无效值
        _daily = self.config.security.get("max_budget_daily", 3.3)
        _monthly = self.config.security.get("max_budget_monthly", 100.0)
        if not isinstance(_daily, (int, float)) or _daily <= 0:
            logger.warning(
                f"[Security] max_budget_daily 配置无效 ({_daily!r})，使用默认值 3.3"
            )
            _daily = 3.3
        if not isinstance(_monthly, (int, float)) or _monthly <= 0 or _monthly < _daily:
            logger.warning(
                f"[Security] max_budget_monthly 配置无效 ({_monthly!r})，使用默认值 100.0"
            )
            _monthly = max(100.0, _daily * 30)
        self.token_tracker.configure(daily_limit=_daily, monthly_limit=_monthly)
        # 注入审批系统到执行管道
        if self.pipeline:
            self.pipeline.set_approval_system(self.approval)

    def _init_gateway(self) -> None:
        self.gateway = GatewayAPI.get()
        self.gateway.initialize(router=self.router, executor=self.pipeline)
        self.gateway.register_platform("cli", {"type": "cli"})
        self.hooks = HookSystem.get()

        # 初始化 MCP 注册表
        from integration.mcp_registry import MCPRegistry
        self.mcp_registry = MCPRegistry.get()
        mcp_cfg = self.config.raw.get("mcp", {})
        servers_cfg = mcp_cfg.get("servers", {})
        if servers_cfg:
            self.mcp_registry.load_from_config(servers_cfg)
            results = self.mcp_registry.connect_all_sync()
            connected = sum(1 for v in results.values() if v)
            logger.info(f"[MCP] 已连接 {connected}/{len(results)} 个 Server")
        else:
            self.mcp_registry = None

        # 初始化 Swarm 群组编排器
        swarm_cfg = self.config.raw.get("swarm", {})
        if swarm_cfg.get("enabled", False):
            try:
                from swarm.agent import Agent
                from swarm.profiles import get_profile
                from swarm.orchestrator import SwarmOrchestrator

                role_names = swarm_cfg.get("roles", ["architect", "coder", "reviewer"])
                max_rounds = swarm_cfg.get("max_rounds", 5)

                agents = []
                for role_name in role_names:
                    profile = get_profile(role_name)
                    if profile:
                        agents.append(Agent(profile=profile, pipeline=self.pipeline))

                if agents:
                    self.swarm_orchestrator = SwarmOrchestrator(
                        agents=agents, max_rounds=max_rounds
                    )
                    logger.info(f"[Swarm] 已初始化: roles={role_names}, max_rounds={max_rounds}")
            except Exception as e:
                logger.warning(f"[Swarm] 初始化失败: {e}")

    def _init_auto_fusion(self) -> None:
        af_cfg = self.config.auto_fusion
        self.auto_fusion = AutoFusionEngine(
            registry_path=BASE_DIR / "feature_registry.json",
            auto_fuse_priority=af_cfg.get("auto_fuse_priority", ["P0", "P1"]),
            require_confirm_for=af_cfg.get("require_confirm_for", ["P2"]),
        )
        if af_cfg.get("scan_on_startup", True):
            report = self.auto_fusion.run()
            if report.fused:
                logger.info(f"[AutoFusion] 新融合 {len(report.fused)} 个特性")

    def _init_stats(self) -> None:
        """初始化统计追踪器和工具结果持久化存储。"""
        try:
            from observability.stats import get_tracker
            self._stats_tracker = get_tracker()
        except Exception as e:
            logger.debug(f"[Stats] 初始化失败（可跳过）: {e}")
            self._stats_tracker = None
        try:
            from executor.tool_result_store import init_store
            data_dir = Path.home() / ".giraffe" / "sessions" / (
                self.state.session_id if self.state else "default"
            )
            init_store(data_dir)
        except Exception as e:
            logger.debug(f"[ToolResultStore] 初始化失败（可跳过）: {e}")

    # ─── 消息处理 ─────────────────────────────────────────────────────────────

    def chat(
        self,
        message: str,
        has_image: bool = False,
        images: list[str] | None = None,
        model_override: str | None = None,
        tier_override: str | None = None,
    ) -> str:
        """
        处理一条用户消息，返回响应字符串。
        完整经过 Router → Guardrails → Pipeline → Memory 流水线。

        Args:
            message: 用户输入的消息文本
            has_image: 是否包含图片
            images: Base64 编码的图片列表（data URI 格式）
        """
        tracer = get_tracer("giraffe")
        event_bus = EventBus.get()

        with tracer.start_as_current_span("giraffe.chat") as span:
            span.set_attribute("giraffe.message_length", len(message))
            span.set_attribute("giraffe.has_image", bool(has_image or images))

            if not self._initialized:
                self.initialize()

            self.state.set_running()
            event_bus.emit("chat_start", message=message[:100])

            # 护栏检查
            guardrail_results = self.guardrails.check(message)
            if self.guardrails.is_blocked(guardrail_results):
                blocked = [r for r in guardrail_results if r.should_block]
                self.state.set_idle()
                return f"🚫 [护栏拦截] {blocked[0].message}"

            # 路由决策
            try:
                decision = self.router.route(message, has_image=bool(has_image or images))
            except Exception as e:
                logger.error(f"路由失败: {e}")
                self.state.set_idle()
                return f"[路由错误] {e}"

            # ── 用户覆盖（/model 或 /tier 命令设置）────────────────────────
            _TIER_MODEL_MAP = {
                "nano":  "gemini-3.1-flash-lite",
                "low":   "gemini-3.1-pro-preview",
                "medium": "claude-sonnet-4-6",
                "high":  "claude-sonnet-4-6",
                "xhigh": "xai/grok-4.20-reasoning",
            }
            if model_override:
                logger.info(f"[Chat] 模型覆盖: {decision.primary_model} → {model_override}")
                decision.primary_model = model_override
                decision.fallback_model = ""
                decision.emergency_model = ""
            elif tier_override and tier_override in _TIER_MODEL_MAP:
                forced = _TIER_MODEL_MAP[tier_override]
                logger.info(f"[Chat] 档位覆盖 ({tier_override}): {decision.primary_model} → {forced}")
                decision.primary_model = forced
                decision.fallback_model = ""
                decision.emergency_model = ""

            # 记忆：获取系统提示词（语义检索注入）
            memory_prompt = self.memory.build_system_prompt()
            messages = self.memory.get_context_messages(max_messages=20)

            # 断点检测：若上次会话被工具执行中断，自动注入续接提示
            try:
                from memory.session_recovery import maybe_inject_continuation
                messages = maybe_inject_continuation(messages)
            except Exception as _e:
                logger.debug(f"[Chat] 断点检测跳过: {_e}")

            # CLAUDE.md / Project Memory 注入
            try:
                from memory.claude_md import build_context_from_claude_md
                claude_md_ctx = build_context_from_claude_md(str(BASE_DIR))
                if claude_md_ctx:
                    memory_prompt = claude_md_ctx + "\n\n" + memory_prompt if memory_prompt else claude_md_ctx
            except Exception as e:
                logger.debug(f"[CLAUDE.md] 加载失败（可跳过）: {e}")

            # MCP 工具列表注入
            mcp_tools = []
            if self.mcp_registry and hasattr(self.mcp_registry, 'get_all_tools_sync'):
                try:
                    mcp_tools = self.mcp_registry.get_all_tools_sync()
                except Exception as e:
                    logger.debug(f"[Chat] MCP工具获取失败（使用空列表）: {e}")

            # 按任务类型设置 max_tokens（重型任务用大值，闲聊/路由用小值）
            _MAX_TOKENS_BY_TASK = {
                "chat":            4096,
                "code_small":      4096,
                "code_medium":     8192,
                "code_large":     16384,
                "reasoning_light": 8192,
                "reasoning":      16384,
                "vision":          4096,
                "routing":         1024,
                "subtask":         4096,
            }
            _max_tokens = _MAX_TOKENS_BY_TASK.get(decision.task_type.value, 4096)

            # 动态查找当前模型的配置凭证
            configured_models = self.config.get_value("router.configured_models") or {}
            model_cfg = configured_models.get(decision.primary_model, self.config.primary_model)
            
            # 构建降级链（过滤空值和重复）
            _fallback_chain = [
                m for m in [decision.fallback_model, decision.emergency_model]
                if m and m != decision.primary_model
            ]
            ctx = ExecutionContext(
                message=message,
                model=decision.primary_model,
                api_key=model_cfg.get("api_key", ""),
                base_url=model_cfg.get("base_url", ""),
                task_type=decision.task_type.value,
                messages=messages,
                system_prompt=memory_prompt,
                images=images or [],
                mcp_tools=mcp_tools,
                max_tokens=_max_tokens,
                fallback_models=_fallback_chain,
                # agent_task/repo_analysis 以及 high/xhigh 档位自动启用工具调用
                use_tools=(
                    decision.task_type.value in ("agent_task", "repo_analysis")
                    or (tier_override or "") in ("high", "xhigh")
                ),
            )

            self.hooks.fire("pre_api_request", message=message, model=ctx.model)

            # 根据 路由决策 决定走单模型 Pipeline 还是 Swarm 群组讨论
            if decision.use_swarm and self.swarm_orchestrator:
                logger.info(f"[Chat] 启动 Swarm 群组讨论: {message[:50]}")
                swarm_result = self.swarm_orchestrator.run(message)
                response_text = swarm_result.final_output
                success = swarm_result.success
                error = None if success else "群组讨论失败"
                # 构造一个兼容的 result
                from executor.pipeline import ExecutionResult
                result = ExecutionResult(
                    success=success,
                    response=response_text,
                    model=decision.primary_model,
                    task_type=decision.task_type.value,
                    error=error,
                )
            else:
                # ── xhigh 档位： Coordinator 模式────────────────────────────
                _is_xhigh = (
                    (tier_override or "") == "xhigh"
                    or decision.task_type.value in ("agent_task", "repo_analysis")
                )
                if _is_xhigh:
                    result = self._run_coordinator_mode(message, decision, ctx)
                else:
                    result = self.pipeline.execute(ctx)

            self.hooks.fire("post_api_response", response=result.response, success=result.success)

            span.set_attribute("giraffe.model", decision.primary_model)
            span.set_attribute("giraffe.task_type", decision.task_type.value)
            span.set_attribute("giraffe.success", result.success)
            event_bus.emit("chat_end", model=decision.primary_model, success=result.success)

            # 记忆更新（先把 user和assistant回复写入短期记忆）
            self.memory.process_message("user", message)
            # 只有成功且未被截断的回复才写入记忆，避免截断内容污染后续上下文
            if result.response and not result.error and not getattr(result, 'truncated', False):
                self.memory.process_message("assistant", result.response)
            elif result.response and getattr(result, 'truncated', False):
                logger.warning("[Chat] 回复因 max_tokens 截断，跳过记忆写入")

            # Token追踪（估算）
            self.token_tracker.record(
                model=decision.primary_model,
                prompt_tokens=len(message) // 4,
                completion_tokens=len(result.response or "") // 4,
                session_id=self.state.session_id,
            )

            # 错误恢复
            if not result.success and result.error:
                # 从错误消息中提取 HTTP 状态码（格式如 "404 NOT_FOUND..." 或 "'code': 404"）
                import re as _re
                _http_code = 0
                _code_match = _re.search(r"(?:^|\s)([45]\d{2})\b|'code':\s*([45]\d{2})", str(result.error))
                if _code_match:
                    _http_code = int(_code_match.group(1) or _code_match.group(2))
                error_report = self.error_processor.process(
                    error=result.error,
                    http_code=_http_code,
                    model=decision.primary_model,
                    model_chain=[decision.primary_model, decision.fallback_model, decision.emergency_model],
                )
                self.evolution_engine.collect(error_report)
                self.hooks.fire("error_occurred", error=result.error, report=error_report)

            # 基于 token 增量 + 工具调用次数的双重阈值自动记录会话摘要
            _prompt_tokens = len(message) // 4
            _completion_tokens = len(result.response or "") // 4
            _tool_calls_this_turn = getattr(result, "tool_calls_made", 0)
            if self.memory.should_extract_summary(
                token_count=_prompt_tokens + _completion_tokens,
                tool_calls=_tool_calls_this_turn,
            ):
                self.memory.record_session(
                    session_id=self.state.session_id,
                    summary=(
                        f"会话 {self.state.session_id[:8]}: "
                        f"共 {len(self.memory.short_term)} 条消息，"
                        f"本次工具调用 {_tool_calls_this_turn} 次"
                    ),
                    tags=[decision.task_type.value],
                )

            self.state.set_idle()
            return result.response

    def _run_coordinator_mode(self, message: str, decision, ctx) -> "ExecutionResult":
        """
        xhigh 档位：Coordinator-Worker 模式。
        - Coordinator LLM 负责任务规划与结果合成
        - Worker LLM 负责具体子任务执行（带 AgenticLoop 工具调用）
        """
        from executor.pipeline import ExecutionResult
        from swarm.coordinator import run_coordinator_sync, get_coordinator_system_prompt
        from tools import build_tool_registry

        tools = build_tool_registry()
        print(f"\n🎯 [Coordinator] 启动 xhigh 模式，正在规划任务...\n")

        def _call_coordinator(messages: list, system: str) -> str:
            """协调器 LLM（Grok/Claude）：规划 + 合成。"""
            from executor.agentic_loop import run_agentic
            result = run_agentic(
                provider="grok" if "grok" in decision.primary_model.lower() else "claude",
                client=self._get_llm_client(decision.primary_model),
                model=decision.primary_model,
                tools={},   # Coordinator 本身不调用工具，由 Worker 执行
                user_message=messages[-1]["content"] if messages else message,
                system=system,
                history=messages[:-1] if messages else [],
                config={"max_tokens": ctx.max_tokens},
            )
            return result.final_text

        def _call_worker(messages: list, system: str) -> str:
            """Worker LLM（带工具）：执行具体子任务。"""
            from executor.agentic_loop import run_agentic
            # Worker 走 AgenticLoop（带工具）
            worker_msg = messages[-1]["content"] if messages else ""
            result = run_agentic(
                provider="claude",   # Worker 用 Claude（代码/研究最强）
                client=self._get_llm_client("claude-sonnet-4-6"),
                model="claude-sonnet-4-6",
                tools=tools,
                user_message=worker_msg,
                system=system,
                history=messages[:-1] if messages else [],
                config={"max_tokens": ctx.max_tokens},
                on_text=lambda t: print(f"  [Worker] {t}", end="", flush=True),
                on_tool_start=lambda n, a: print(f"\n  🔧 [Worker] 调用工具: {n}"),
                on_tool_done=lambda uid, r: print(
                    f"  {'✅' if not r.is_error else '❌'} [Worker] 工具完成"
                ),
            )
            return result.final_text

        def _on_coordinator_text(text: str) -> None:
            print(text, end="", flush=True)

        def _on_worker_spawn(task_id: str, desc: str) -> None:
            print(f"\n🚀 [Coordinator] 派生 Worker: {task_id} — {desc}")

        def _on_worker_done(task_id: str, result) -> None:
            icon = "✅" if result.status == "completed" else "❌"
            print(f"\n{icon} [Coordinator] Worker 完成: {task_id} ({result.status})")

        try:
            final_text = run_coordinator_sync(
                user_request=message,
                call_coordinator_llm=_call_coordinator,
                call_worker_llm=_call_worker,
                tools=tools,
                on_coordinator_text=_on_coordinator_text,
                on_worker_spawn=_on_worker_spawn,
                on_worker_done=_on_worker_done,
            )
            return ExecutionResult(
                success=True,
                response=final_text,
                model=decision.primary_model,
                task_type=decision.task_type.value,
            )
        except Exception as e:
            logger.error(f"[Coordinator] 执行失败: {e}")
            # 回退到普通 pipeline
            return self.pipeline.execute(ctx)

    def _get_llm_client(self, model: str):
        """根据模型名返回对应的 SDK client。"""
        from core.config import GiraffeConfig
        _cfg = GiraffeConfig.get()
        
        configured_models = _cfg.get_value("router.configured_models") or {}
        primary_cfg = configured_models.get(model, _cfg.get_value("router.primary_model") or {})
        
        api_key = primary_cfg.get("api_key", "")
        base_url = primary_cfg.get("base_url", "")
        project = primary_cfg.get("project") or None
        use_adc = not api_key or api_key.startswith("${")

        if model.startswith("claude-"):
            if use_adc:
                from anthropic import AnthropicVertex
                region = _cfg.get_value("router.claude_location") or "global"
                return AnthropicVertex(project_id=project, region=region)
            else:
                from anthropic import Anthropic
                if base_url:
                    return Anthropic(api_key=api_key, base_url=base_url)
                return Anthropic(api_key=api_key)

        elif "grok" in model.lower():
            from openai import OpenAI
            if use_adc:
                import google.auth
                import google.auth.transport.requests
                creds, proj = google.auth.default(
                    scopes=["https://www.googleapis.com/auth/cloud-platform"]
                )
                creds.refresh(google.auth.transport.requests.Request())
                return OpenAI(
                    base_url=f"https://aiplatform.googleapis.com/v1/projects/{proj}/locations/global/endpoints/openapi",
                    api_key=creds.token,
                )
            else:
                # Grok API Key
                if base_url:
                    return OpenAI(api_key=api_key, base_url=base_url)
                return OpenAI(api_key=api_key)
                
        elif model.startswith("gemini-"):
            from google import genai
            if use_adc:
                region = _cfg.get_value("router.primary_model.location") or "global"
                return genai.Client(vertexai=True, project=project, location=region)
            else:
                if base_url:
                    return genai.Client(api_key=api_key, http_options={"base_url": base_url})
                return genai.Client(api_key=api_key)
                
        else:
            # 兼容 OpenAI 的其他平台（OpenAI, DeepSeek, Mistral, Moonshot 等）
            from openai import OpenAI
            if base_url:
                return OpenAI(api_key=api_key, base_url=base_url)
            return OpenAI(api_key=api_key)

    # ─── 调试工具 ─────────────────────────────────────────────────────────────
    def test_route(self, message: str) -> dict:
        """测试路由决策（不调用API）。"""
        if not self._initialized:
            self.initialize()
        decision = self.router.route(message)
        return decision.to_dict()

    def health(self) -> dict:
        """系统健康检查。"""
        return {
            "initialized": self._initialized,
            "session_id": self.state.session_id if self.state else None,
            "gateway": self.gateway.health_check() if self.gateway else {},
            "memory": self.memory.stats() if self.memory else {},
            "antibody": self.antibody_lib.stats() if self.antibody_lib else {},
            "token_tracker": self.token_tracker.total_stats() if self.token_tracker else {},
            "router": self.router.stats() if self.router else {},
            "pipeline": self.pipeline.stats() if self.pipeline else {},
            "auto_fusion": self.auto_fusion.get_registry_stats() if self.auto_fusion else {},
        }

    def evolve(self) -> dict:
        """触发一次进化（分析历史错误，优化抗体库）。"""
        if self.evolution_engine:
            report = self.evolution_engine.evolve()
            return report.to_dict()
        return {"error": "进化引擎未初始化"}

    def memory_summary(self) -> str:
        """输出人类可读的记忆摘要。"""
        if self.memory:
            return self.memory.memory_summary()
        return "记忆系统未初始化"

    def confirm_topup(self) -> bool:
        """用户确认已充値，切回三方API。"""
        if self.credit_monitor:
            ok = self.credit_monitor.confirm_topup()
            if ok:
                logger.info("✅ 已切回三方API")
            return ok
        return False

    def fusion_stats(self) -> dict:
        """获取自动融合引擎状态。"""
        if self.auto_fusion:
            return self.auto_fusion.get_registry_stats()
        return {"error": "融合引擎未初始化"}

    def credit_status(self) -> dict:
        """信用监控状态。"""
        if self.credit_monitor:
            return self.credit_monitor.summary()
        return {"error": "信用监控未初始化"}

# ─── CLI 主循环 ───────────────────────────────────────────────────────────────
# 用户级配置目录（pip install 后使用）
USER_CONFIG_DIR = Path.home() / ".giraffe"

def _init_user_config() -> None:
    """将默认配置文件复制到 ~/.giraffe/，供 pip 安装后首次使用。"""
    import shutil

    USER_CONFIG_DIR.mkdir(parents=True, exist_ok=True)

    # 复制 config.json
    src_config = BASE_DIR / "config.json"
    dst_config = USER_CONFIG_DIR / "config.json"
    if src_config.exists() and not dst_config.exists():
        shutil.copy2(src_config, dst_config)
        print(f"  ✅ 配置文件 → {dst_config}")
    elif dst_config.exists():
        print(f"  ⏭️  配置文件已存在: {dst_config}")

    # 复制 feature_registry.json
    src_reg = BASE_DIR / "feature_registry.json"
    dst_reg = USER_CONFIG_DIR / "feature_registry.json"
    if src_reg.exists() and not dst_reg.exists():
        shutil.copy2(src_reg, dst_reg)
        print(f"  ✅ 能力注册表 → {dst_reg}")

    # 创建 data/ 子目录
    (USER_CONFIG_DIR / "data").mkdir(exist_ok=True)
    # 创建 skills/ 子目录
    (USER_CONFIG_DIR / "skills").mkdir(exist_ok=True)

    print(f"\n初始化完成。请编辑 {dst_config} 填入 API Key。")
    print(f"之后运行 giraffe 即可启动。\n")

def _resolve_config_path(explicit: str | None) -> Path:
    """
    配置文件查找优先级：
    1. --config 显式指定
    2. 当前目录的 config.json（开发模式）
    3. ~/.giraffe/config.json（pip 安装模式）
    4. 包内默认 config.json
    """
    if explicit:
        return Path(explicit)
    cwd_config = Path.cwd() / "config.json"
    if cwd_config.exists():
        return cwd_config
    user_config = USER_CONFIG_DIR / "config.json"
    if user_config.exists():
        return user_config
    return BASE_DIR / "config.json"

def main():
    parser = argparse.ArgumentParser(
        description="Giraffe — 生产级 AI 运行时框架",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""\
示例:
  giraffe                                  # 启动交互模式
  giraffe --serve                          # 启动 Web 服务
  giraffe --init                           # 初始化用户配置到 ~/.giraffe/
  giraffe --test-route "帮我写个Flask API"  # 测试路由
  giraffe --health                         # 系统健康检查
        """,
    )
    parser.add_argument("--config", default=None, help="配置文件路径")
    parser.add_argument("--init", action="store_true", help="初始化用户配置到 ~/.giraffe/")
    parser.add_argument("--version", action="store_true", help="显示版本号")
    parser.add_argument("--test-route", metavar="MSG", help="测试路由决策（不调用API）")
    parser.add_argument("--health", action="store_true", help="显示系统健康状态")
    parser.add_argument("--evolve", action="store_true", help="触发进化引擎")
    parser.add_argument("--debug", action="store_true", help="开启DEBUG日志")
    parser.add_argument("--log-file", metavar="PATH", default=None, help="日志写入文件路径（轮转，10MB×5）")
    parser.add_argument("--quiet", action="store_true", help="只显示 WARNING 及以上日志")
    parser.add_argument("--no-color", action="store_true", help="禁用 ANSI 彩色日志")
    parser.add_argument("--serve", action="store_true", help="启动 Web 服务模式（FastAPI）")
    parser.add_argument("--host", default="0.0.0.0", help="Web 服务监听地址")
    parser.add_argument("--port", type=int, default=8000, help="Web 服务监听端口")
    args = parser.parse_args()

    # ── 日志系统初始化（最早执行）──────────────────────────────────────────────
    from observability.logging_config import setup_logging
    _log_level = "DEBUG" if args.debug else ("WARNING" if args.quiet else "INFO")
    setup_logging(
        level=_log_level,
        log_file=args.log_file,
        color=not args.no_color,
    )

    # 压制 huggingface_hub 的 WARNING 日志（由 sentence-transformers 副作用触发）
    # HF_HUB_VERBOSITY 控制其内部 logger，但也需在 Python logging 层面过滤
    import logging as _logging
    for _hf_logger in ("huggingface_hub", "huggingface_hub.utils._http",
                        "huggingface_hub._commit_api", "filelock"):
        _logging.getLogger(_hf_logger).setLevel(_logging.ERROR)

    if args.version:
        print("giraffe-immortal 1.9.5")
        return

    if args.init:
        print("正在初始化 Giraffe 用户配置...\n")
        _init_user_config()
        return

    if args.debug:
        logging.getLogger().setLevel(logging.DEBUG)

    config_path = _resolve_config_path(args.config)
    giraffe = Giraffe(config_path=config_path)

    giraffe.initialize()

    # ── 特殊模式 ──────────────────────────────────────────────────────────────
    if args.serve:
        # 将 giraffe 实例挂载到 web_server 模块，供 get_giraffe() 访问
        import integration.web_server as _ws_module
        _ws_module._giraffe_instance = giraffe
        logger.info(f"[Giraffe] 启动 Web 服务模式: http://{args.host}:{args.port}")
        giraffe.gateway.start_web_server(host=args.host, port=args.port)
        return

    if args.test_route:
        import json as _json
        result = giraffe.test_route(args.test_route)
        print("\n📍 路由决策结果:")
        print(_json.dumps(result, ensure_ascii=False, indent=2))
        return

    if args.health:
        import json as _json
        health = giraffe.health()
        print("\n💊 系统健康状态:")
        print(_json.dumps(health, ensure_ascii=False, indent=2))
        return

    if args.evolve:
        import json as _json
        report = giraffe.evolve()
        print("\n🧬 进化报告:")
        print(_json.dumps(report, ensure_ascii=False, indent=2))
        return

    # ── 交互循环 ──────────────────────────────────────────────────────────────
    # 会话级模型/档位覆盖状态
    _model_override: str | None = None
    _tier_override:  str | None = None

    # 已知模型别名（可在命令中直接用简称），通过 model_aliases 动态解析
    from router.model_aliases import (
        parse_model_alias as _parse_alias,
        get_default_opus_model as _opus,
        get_default_sonnet_model as _sonnet,
        get_default_haiku_model as _haiku,
        _OTHER_MODELS,
    )

    _MODEL_ALIASES: dict[str, str] = {
        "grok":      "xai/grok-4.20-reasoning",
        "claude":    _sonnet(),
        "sonnet":    _sonnet(),
        "opus":      _opus(),
        "haiku":     _haiku(),
        "gemini":    "gemini-3.1-pro-preview",
        "flash":     "gemini-3-flash-preview",
        "lite":      "gemini-3.1-flash-lite",
        "best":      _opus(),
        "opusplan":  _sonnet(),
    }
    _MODEL_ALIASES.update(_OTHER_MODELS)

    _VALID_TIERS = ("nano", "low", "medium", "high", "xhigh")

    def _override_status() -> str:
        parts = []
        if _model_override:
            parts.append(f"model={_model_override}")
        if _tier_override:
            parts.append(f"tier={_tier_override}")
        return ("[" + " | ".join(parts) + "] ") if parts else ""

    print(f"\n💬 Giraffe已就绪。输入 /help 查看所有命令\n")

    while True:
        try:
            prompt = f"You{_override_status()}> "
            user_input = input(prompt).strip()
        except (EOFError, KeyboardInterrupt):
            print("\n👋 再见！")
            break

        if not user_input:
            continue

        # ── 内置命令 ─────────────────────────────────────────────────────────
        cmd = user_input.lower().strip()
        if cmd in ("/quit", "/exit", "/q"):
            print("👋 再见！")
            break

        # /add_model 添加新模型配置
        elif cmd == "/add_model":
            from integration.setup_wizard import SetupWizard
            print("\n⚙️ 正在启动模型配置向导...")
            SetupWizard().configure_additional_model()
            # 重新加载配置
            giraffe.config.reload()
            print("🔄 配置已重新加载。\n")
            continue

        # /model [name|alias|auto]
        elif cmd == "/model":
            if _model_override:
                print(f"🤖 当前模型覆盖: {_model_override}  （/model auto 可清除）")
            else:
                print("🤖 模型覆盖: 未设置（自动路由）")
            continue
        elif user_input.lower().startswith("/model "):
            arg = user_input[7:].strip()
            if arg in ("auto", "reset", "off", ""):
                _model_override = None
                print("✅ 模型覆盖已清除，恢复自动路由")
            else:
                resolved = _MODEL_ALIASES.get(arg.lower(), arg)
                _model_override = resolved
                _tier_override = None  # 互斥
                print(f"✅ 模型已锁定: {resolved}")
            continue

        # /tier [nano|low|medium|high|xhigh|auto]
        elif cmd == "/tier":
            if _tier_override:
                print(f"⚙️  当前档位覆盖: {_tier_override}  （/tier auto 可清除）")
            else:
                print("⚙️  档位覆盖: 未设置（自动路由）")
            continue
        elif user_input.lower().startswith("/tier "):
            arg = user_input[6:].strip().lower()
            if arg in ("auto", "reset", "off", ""):
                _tier_override = None
                print("✅ 档位覆盖已清除，恢复自动路由")
            elif arg in _VALID_TIERS:
                _tier_override = arg
                _model_override = None  # 互斥
                print(f"✅ 档位已锁定: {arg}")
            else:
                print(f"❌ 无效档位，可选: {', '.join(_VALID_TIERS)}")
            continue

        # 快捷别名：/grok /claude /gemini /flash 等
        elif cmd.lstrip("/") in _MODEL_ALIASES and cmd.startswith("/"):
            target = _MODEL_ALIASES[cmd.lstrip("/")]
            _model_override = target
            _tier_override = None
            print(f"✅ 模型已切换: {target}")
            continue


        # /auto — 清除所有覆盖
        elif cmd == "/auto":
            _model_override = None; _tier_override = None
            print("✅ 所有覆盖已清除，恢复全自动路由")
            continue

        # /models — 列出所有可用模型
        elif cmd == "/models":
            print("可用模型（可直接用别名）:")
            for alias, full in _MODEL_ALIASES.items():
                mark = " ◀ 当前" if full == _model_override else ""
                print(f"  /{alias:10} → {full}{mark}")
            print("\n完整模型名可直接用 /model <full-name> 设置")
            continue

        elif cmd == "/health":
            import json as _json
            print(_json.dumps(giraffe.health(), ensure_ascii=False, indent=2))
            continue
        elif cmd == "/evolve":
            import json as _json
            print(_json.dumps(giraffe.evolve(), ensure_ascii=False, indent=2))
            continue
        elif user_input.lower().startswith("/route "):
            import json as _json
            msg = user_input[7:]
            print(_json.dumps(giraffe.test_route(msg), ensure_ascii=False, indent=2))
            continue
        elif user_input.lower() == "/stats":
            import json as _json
            print(_json.dumps(giraffe.pipeline.stats() if giraffe.pipeline else {}, ensure_ascii=False, indent=2))
            continue

        elif user_input.lower() == "/memory":
            print(giraffe.memory_summary())
            continue
        elif user_input.lower() == "/credit":
            import json as _json
            print(_json.dumps(giraffe.credit_status(), ensure_ascii=False, indent=2))
            continue
        elif user_input.lower() == "/topup":
            ok = giraffe.confirm_topup()
            print("✅ 已切回三方API" if ok else "未处于兑底模式")
            continue
        elif user_input.lower() == "/fusion":
            import json as _json
            print(_json.dumps(giraffe.fusion_stats(), ensure_ascii=False, indent=2))
            continue
        elif user_input.lower() == "/antibody":
            import json as _json
            stats = giraffe.antibody_lib.stats() if giraffe.antibody_lib else {}
            print(_json.dumps(stats, ensure_ascii=False, indent=2))
            continue
        elif user_input.lower() == "/token":
            import json as _json
            stats = giraffe.token_tracker.total_stats() if giraffe.token_tracker else {}
            print(_json.dumps(stats, ensure_ascii=False, indent=2))
            continue

        # /loglevel — 运行时动态调整日志级别
        elif cmd == "/loglevel":
            from observability.logging_config import get_log_level
            print(f"📋 当前日志级别: {get_log_level()}  （可用: /loglevel debug/info/warning/error）")
            continue
        elif user_input.lower().startswith("/loglevel "):
            lvl_arg = user_input[10:].strip().upper()
            valid = ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL")
            if lvl_arg in valid:
                from observability.logging_config import set_log_level
                set_log_level(lvl_arg)  # type: ignore[arg-type]
                print(f"✅ 日志级别已调整为: {lvl_arg}")
            else:
                print(f"❌ 无效级别，可选: {', '.join(v.lower() for v in valid)}")
            continue

        # /skills — 列出所有可用技能
        elif cmd == "/skills":
            try:
                from skills.loader import list_skills
                skills = list_skills(cwd=str(BASE_DIR))
                print("\n📚 可用技能 (Skills):\n")
                for sk in skills:
                    src_tag = f"[{sk.source}]" if sk.source != "bundled" else ""
                    aliases = ", ".join(f"/{a}" for a in sk.aliases) if sk.aliases else ""
                    alias_str = f"  (并名: {aliases})" if aliases else ""
                    print(f"  /{sk.name:20} {sk.description}{alias_str} {src_tag}")
                print(f"\n共 {len(skills)} 个技能。在 ~/.giraffe/skills/ 下放置 .md 文件可自定义技能。")
            except Exception as e:
                print(f"[技能] 加载失败: {e}")
            continue

        # /skill <name> [args] — 执行指定技能
        elif user_input.lower().startswith("/skill ") or (
            user_input.startswith("/") and not user_input.lower().startswith("/model ")
            and not user_input.lower().startswith("/tier ")
            and not cmd.startswith("/")
        ):
            # 尝试匹配技能名
            raw = user_input.lstrip("/")
            parts_cmd = raw.split(" ", 1)
            skill_name = parts_cmd[0].lower()
            skill_args = parts_cmd[1] if len(parts_cmd) > 1 else ""
            try:
                from skills.loader import get_skill
                skill = get_skill(skill_name, cwd=str(BASE_DIR))
                if skill:
                    skill_prompt = skill.get_prompt(skill_args)
                    # 将技能提示词当作系统提示词 + 用户消息执行
                    print(f"\n📚 执行技能: /{skill_name}\n")
                    combined = f"[SKILL: {skill.name}]\n{skill_prompt}\n\n用户参数: {skill_args}" if skill_args else f"[SKILL: {skill.name}]\n{skill_prompt}"
                    response = giraffe.chat(
                        combined,
                        model_override=skill.model or _model_override,
                        tier_override=_tier_override,
                    )
                    print(f"\nGiraffe> {response}\n")
                    continue
            except Exception:
                pass
            # 未匹配到技能，继续走普通消息路径

        # /usagestats — 显示使用统计
        elif cmd == "/usagestats":
            try:
                from observability.stats import get_tracker
                from dataclasses import asdict
                import json as _json
                stats = get_tracker().compute_stats(days=30)
                print(f"""
📊 Giraffe 使用统计 (近30天)
  会话数:    {stats.total_sessions}
  消息数:    {stats.total_messages}
  工具调用:  {stats.total_tool_calls}
  活跃天数:  {stats.active_days}
  连续天数:  {stats.streaks.current_streak} 天 (最长: {stats.streaks.longest_streak} 天)
  最活跃时段: {stats.peak_activity_hour}:00
  首次使用:  {stats.first_session_date or 'N/A'}
  最近使用:  {stats.last_session_date or 'N/A'}
""")
                if stats.model_usage:
                    print("  模型用量:")
                    for model, usage in sorted(stats.model_usage.items()):
                        total_tok = usage.get('input', 0) + usage.get('output', 0)
                        print(f"    {model}: {total_tok:,} tokens (cost: ${usage.get('cost',0):.3f})")
            except Exception as e:
                print(f"[统计] 读取失败: {e}")
            continue

        elif cmd == "/help":

            print("""
┌─ 模型 / 档位切换 ─────────────────────────────────────────────────┐
│  /model <name>     锁定模型（后续所有请求强制使用）             │
│  /model auto       清除模型锁定，恢复自动路由                   │
│  /tier <tier>      锁定档位 (nano/low/medium/high/xhigh)        │
│  /auto             清除所有锁定，完全自动路由                   │
│  /grok /claude /gemini /flash  快速切换模型                     │
│  /add_model        动态配置/补充新模型                          │
│  /models           列出所有可用别名                             │
├─ 技能系统 (Skills) ────────────────────────────────────────────────┤
│  /skills           列出所有可用技能                             │
│  /<skill> [args]   执行指定技能（如 /analyze_repo /review ...） │
│  /analyze_repo     深入分析当前代码仓库架构                     │
│  /review [file]    代码审查                                     │
│  /debug [问题]     系统性调试分析                               │
│  /test [file]      生成测试代码                                 │
│  /doc [file]       生成文档                                     │
├─ 系统命令 ────────────────────────────────────────────────────────┤
│  /health           系统健康检查                                 │
│  /memory           记忆系统摘要                                 │
│  /usagestats       使用统计（会话数/天数/模型用量）             │
│  /credit           信用监控状态                                 │
│  /stats            流水线执行统计                               │
│  /token            Token 预算统计                               │
│  /evolve           触发进化引擎                                 │
│  /antibody         抗体库状态                                   │
│  /fusion           自动融合引擎状态                             │
│  /route <消息>     测试路由决策（不实际调用模型）               │
│  /topup            切回三方 API（信用兜底）                     │
│  /quit, /q         退出                                         │
└─────────────────────────────────────────────────────────────────┘
""")

            continue

        # 普通消息
        response = giraffe.chat(
            user_input,
            model_override=_model_override,
            tier_override=_tier_override,
        )
        print(f"\nGiraffe> {response}\n")

if __name__ == "__main__":
    main()

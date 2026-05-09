"""
Giraffe — 主入口

启动系统并进入交互循环。
"""
from __future__ import annotations

import argparse
import logging
from pathlib import Path

# 项目根目录
BASE_DIR = Path(__file__).parent

# ─── 日志配置 ─────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
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
║          Giraffe  v1.0.0                                  ║
║          DAG | Swarm | Telemetry | Memory | SelfHeal      ║
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

        results = startup.run_all()

        failed = [k for k, v in results.items() if v.startswith("error")]
        if failed:
            logger.warning(f"⚠️  以下模块初始化失败: {', '.join(failed)}")
        else:
            logger.info("✅ 所有模块初始化成功")

        self._initialized = True
        session_id = self.state.initialize()
        logger.info(f"🚀 会话启动: {session_id}")

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

    # ─── 消息处理 ─────────────────────────────────────────────────────────────
    def chat(self, message: str, has_image: bool = False, images: list[str] | None = None) -> str:
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

            # 记忆：获取系统提示词（语义检索注入）
            memory_prompt = self.memory.build_system_prompt()
            messages = self.memory.get_context_messages(max_messages=20)

            # MCP 工具列表注入
            mcp_tools = []
            if self.mcp_registry and hasattr(self.mcp_registry, 'get_all_tools_sync'):
                try:
                    mcp_tools = self.mcp_registry.get_all_tools_sync()
                except Exception:
                    pass

            # 执行
            primary_cfg = self.config.primary_model
            ctx = ExecutionContext(
                message=message,
                model=decision.primary_model,
                api_key=primary_cfg.get("api_key", ""),
                base_url=primary_cfg.get("base_url", ""),
                task_type=decision.task_type.value,
                messages=messages,
                system_prompt=memory_prompt,
                images=images or [],
                mcp_tools=mcp_tools,
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
                result = self.pipeline.execute(ctx)

            self.hooks.fire("post_api_response", response=result.response, success=result.success)

            span.set_attribute("giraffe.model", decision.primary_model)
            span.set_attribute("giraffe.task_type", decision.task_type.value)
            span.set_attribute("giraffe.success", result.success)
            event_bus.emit("chat_end", model=decision.primary_model, success=result.success)

            # 记忆更新（先把 user和assistant回复写入短期记忆）
            self.memory.process_message("user", message)
            self.memory.process_message("assistant", result.response)

            # Token追踪（估算）
            self.token_tracker.record(
                model=decision.primary_model,
                prompt_tokens=len(message) // 4,
                completion_tokens=len(result.response) // 4,
                session_id=self.state.session_id,
            )

            # 错误恢复
            if not result.success and result.error:
                error_report = self.error_processor.process(
                    error=result.error,
                    model=decision.primary_model,
                    model_chain=[decision.primary_model, decision.fallback_model, decision.emergency_model],
                )
                self.evolution_engine.collect(error_report)
                self.hooks.fire("error_occurred", error=result.error, report=error_report)

            # 会话日记（每10条消息自动记录一次）
            if len(self.memory.short_term) % 10 == 0:
                self.memory.record_session(
                    session_id=self.state.session_id,
                    summary=f"会话{self.state.session_id[:8]}: 共{len(self.memory.short_term)}条消息",
                    tags=[decision.task_type.value],
                )

            self.state.set_idle()
            return result.response

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
    parser.add_argument("--serve", action="store_true", help="启动 Web 服务模式（FastAPI）")
    parser.add_argument("--host", default="0.0.0.0", help="Web 服务监听地址")
    parser.add_argument("--port", type=int, default=8000, help="Web 服务监听端口")
    args = parser.parse_args()

    if args.version:
        print("giraffe-immortal 1.0.0")
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
    print(f"\n💬 Giraffe已就绪。输入消息开始对话，输入 /quit 退出，/health 查看状态，/evolve 触发进化\n")

    while True:
        try:
            user_input = input("You> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n👋 再见！")
            break

        if not user_input:
            continue

        # 内置命令
        if user_input.lower() in ("/quit", "/exit", "/q"):
            print("👋 再见！")
            break
        elif user_input.lower() == "/health":
            import json as _json
            print(_json.dumps(giraffe.health(), ensure_ascii=False, indent=2))
            continue
        elif user_input.lower() == "/evolve":
            import json as _json
            print(_json.dumps(giraffe.evolve(), ensure_ascii=False, indent=2))
            continue
        elif user_input.startswith("/route "):
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
        elif user_input.lower() == "/help":
            print("""
命令列表:
  /quit, /exit, /q  退出
  /health           系统健康检查
  /memory           记忆系统摘要
  /credit           信用监控状态
  /topup            确认充値（切回三方API）
  /evolve           触发进化引擎
  /route <消息>    测试路由决策
  /fusion           自动融合引擎状态
  /antibody         抗体库状态
  /token            Token预算追踪
  /stats            流水线执行统计
  /help             显示本帮助
""")
            continue

        # 普通消息
        response = giraffe.chat(user_input)
        print(f"\nGiraffe> {response}\n")


if __name__ == "__main__":
    main()

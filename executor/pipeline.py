"""
ExecutorPipeline — 执行管道主文件
8阶段流水线：TaskDecomposer → PreApprover → MicroCompact → CreditMonitor
            → API调用 → DeepCompact → ResponseCache → ParallelExecutor
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from pathlib import Path

from .deep_compact import DeepCompact
from .micro_compact import MicroCompact
from .parallel_executor import ParallelSubAgentExecutor
from .response_cache import ResponseCache
from .task_decomposer import TaskDecomposer

from observability.tracer import get_tracer
from integration.event_stream import EventBus
from executor.circuit_breaker import CircuitBreakerRegistry

logger = logging.getLogger(__name__)

@dataclass
class ExecutionContext:
    """单次执行的上下文数据，贯穿8个阶段。"""
    message: str
    model: str
    api_key: str = ""
    base_url: str = ""
    task_type: str = "chat"
    messages: list[dict] = field(default_factory=list)
    system_prompt: str = ""
    max_tokens: int = 2048
    temperature: float = 0.7
    use_cache: bool = True
    images: list[str] = field(default_factory=list)
    mcp_tools: list[dict] = field(default_factory=list)  # MCP工具描述列表
    use_tools: bool = False          # 是否启用 AgenticLoop（tool_use 循环）
    enabled_tools: list[str] | None = None  # None=全部；否则指定工具名

    # 执行过程中填充
    approved: bool = True
    approval_reason: str = ""
    cache_hit: bool = False
    response: str = ""
    error: str | None = None
    truncated: bool = False          # 回复是否因 max_tokens 被截断
    fallback_models: list[str] = field(default_factory=list)  # 降级模型链
    stage_times: dict[str, float] = field(default_factory=dict)
    # 内部传递字段（不对外暴露）
    _tool_calls_made: int = field(default=0, repr=False)

    def record_stage(self, stage: str, duration_ms: float) -> None:
        self.stage_times[stage] = round(duration_ms, 2)

    def __post_init__(self) -> None:
        """dataclass 初始化后验证关键字段。"""
        if self.message is None:
            raise ValueError(
                "[ExecutionContext] message 不能为 None。"
                "请确保传入有效的字符串消息。"
            )
        if not isinstance(self.message, str):
            raise TypeError(
                f"[ExecutionContext] message 必须是 str，得到 {type(self.message).__name__}。"
            )
        if not self.model or not isinstance(self.model, str):
            raise ValueError(
                f"[ExecutionContext] model 必须是非空字符串，得到 {self.model!r}。"
            )

@dataclass
class ExecutionResult:
    """执行管道最终结果。"""
    success: bool
    response: str
    model: str
    task_type: str
    cache_hit: bool = False
    total_ms: float = 0.0
    stage_times: dict[str, float] = field(default_factory=dict)
    error: str | None = None
    tokens_used: int = 0
    truncated: bool = False          # 是否被 max_tokens 截断
    tool_calls_made: int = 0         # 本次执行的工具调用次数

    def to_dict(self) -> dict:
        return {
            "success": self.success,
            "model": self.model,
            "task_type": self.task_type,
            "cache_hit": self.cache_hit,
            "total_ms": self.total_ms,
            "error": self.error,
        }

class ExecutorPipeline:
    """
    执行管道（8阶段流水线）。

    阶段顺序：
    1. TaskDecomposer  — 任务拆解
    2. PreApprover     — 预审批（P0/P1/P2）
    3. MicroCompact    — 微压缩（>500字符时压缩）
    4. CreditMonitor   — 信用检查（欠费切换兜底）
    5. API调用         — 实际模型调用
    6. DeepCompact     — 深度压缩（>20条时压缩历史）
    7. ResponseCache   — 响应缓存
    8. ParallelExecutor— 并行执行（多子任务时）
    """

    def __init__(self, config: dict | None = None, data_dir: Path | None = None) -> None:
        cfg = config or {}
        self._cfg = cfg
        self._data_dir = data_dir or Path(__file__).parent.parent / "data"

        # 初始化各组件
        comp_cfg = cfg.get("compression", {})
        self._micro = MicroCompact(threshold=comp_cfg.get("micro_threshold", 500))
        self._deep = DeepCompact(threshold=comp_cfg.get("deep_threshold", 20))
        self._decomposer = TaskDecomposer()

        cache_path = self._data_dir / "cache" / "response_cache.json"
        self._cache = ResponseCache(persist_path=cache_path)

        exec_cfg = cfg.get("executor", {})
        self._parallel = ParallelSubAgentExecutor(
            max_workers=exec_cfg.get("parallel_max_workers", 3),
            timeout=exec_cfg.get("task_timeout", 300),
        )
        self._breaker_registry = CircuitBreakerRegistry.get()
        if "circuit_breaker" in cfg.get("router", {}):
            self._breaker_registry.configure(cfg["router"]["circuit_breaker"])

        # 信用监控（延迟导入避免循环依赖）
        self._credit_monitor = None
        self._approval_system = None

        self._total_calls = 0
        self._failed_calls = 0

    def set_credit_monitor(self, credit_monitor) -> None:
        self._credit_monitor = credit_monitor

    def set_approval_system(self, approval_system) -> None:
        self._approval_system = approval_system

    # ─── 主入口 ───────────────────────────────────────────────────────────────
    def execute(self, ctx: ExecutionContext) -> ExecutionResult:
        """
        执行8阶段流水线，返回执行结果。

        内部将 8 个阶段封装为 GraphEngine 节点：
        decompose → pre_approve → micro_compact → credit_check
            → [parallel_execute | api_call ←→ self_heal(最多3次重试)]
            → deep_compact → cache_store

        外部接口保持不变：(ExecutionContext) → ExecutionResult
        """
        from graph.engine import GraphEngine
        from graph.node import (
            DecomposeNode, ApprovalNode, MicroCompactNode, CreditCheckNode,
            APICallNode, SelfHealNode, DeepCompactNode, CacheNode, ParallelExecuteNode,
        )
        from graph.state import GraphState

        tracer = get_tracer("giraffe.pipeline")
        event_bus = EventBus.get()
        t_total_start = time.perf_counter()
        self._total_calls += 1

        # 将 ExecutionContext 转为 GraphState
        initial_state: GraphState = {
            "message": ctx.message,
            "model": ctx.model,
            "api_key": ctx.api_key,
            "base_url": ctx.base_url,
            "task_type": ctx.task_type,
            "messages": list(ctx.messages),
            "system_prompt": ctx.system_prompt,
            "images": list(ctx.images),
            "mcp_tools": list(ctx.mcp_tools),
            "max_tokens": ctx.max_tokens,
            "temperature": ctx.temperature,
            "use_cache": ctx.use_cache,
            "fallback_models": list(ctx.fallback_models),
            "approved": True,
            "approval_reason": "",
            "cache_hit": False,
            "response": "",
            "error": None,
            "retry_count": 0,
            "stage_history": [],
            "stage_times": {},
        }

        with tracer.start_as_current_span("giraffe.pipeline.execute") as root_span:
            root_span.set_attribute("giraffe.model", ctx.model)
            root_span.set_attribute("giraffe.task_type", ctx.task_type)

            try:
                # ── 构建图 ────────────────────────────────────────────────────
                engine = GraphEngine()

                engine.add_node(DecomposeNode(self._decomposer))
                engine.add_node(ApprovalNode(self._approval_system))
                engine.add_node(MicroCompactNode(self._micro))
                engine.add_node(CreditCheckNode(self._credit_monitor))
                engine.add_node(APICallNode(self))
                engine.add_node(SelfHealNode(
                    error_processor=None,  # self_heal 通过 giraffe.py 层触发，节点内仅做重试标记
                    model_chain=[ctx.model],
                ))
                engine.add_node(DeepCompactNode(self._deep))
                engine.add_node(CacheNode(self._cache))
                engine.add_node(ParallelExecuteNode(self))

                # ── 设置边 ────────────────────────────────────────────────────
                engine.set_entry("decompose")

                engine.add_edge("decompose", "pre_approve")

                # pre_approve 后：被拒绝则直接结束，否则继续
                engine.add_conditional_edge(
                    "pre_approve",
                    lambda s: "rejected" if not s.get("approved", True) else "ok",
                    {"rejected": "__FINISH__", "ok": "micro_compact"},
                )

                engine.add_edge("micro_compact", "credit_check")

                # credit_check 后：复杂任务走并行，简单任务走 api_call
                engine.add_conditional_edge(
                    "credit_check",
                    lambda s: (
                        "parallel"
                        if s.get("decomposed") is not None
                        and getattr(s.get("decomposed"), "is_complex", False)
                        and len(getattr(s.get("decomposed"), "subtasks", [])) > 1
                        else "single"
                    ),
                    {"parallel": "parallel_execute", "single": "api_call"},
                )

                engine.add_edge("parallel_execute", "deep_compact")

                # api_call 后：有错误且重试次数 < 3 → self_heal，否则继续
                engine.add_conditional_edge(
                    "api_call",
                    lambda s: (
                        "heal"
                        if s.get("error") and s.get("retry_count", 0) < 3
                        else "ok"
                    ),
                    {"heal": "self_heal", "ok": "deep_compact"},
                )

                # self_heal 后：回到 api_call 重试
                engine.add_edge("self_heal", "api_call")

                engine.add_edge("deep_compact", "cache_store")
                engine.set_finish("cache_store")

                # ── 发布开始事件 ──────────────────────────────────────────────
                event_bus.emit("pipeline_start", model=ctx.model, task_type=ctx.task_type)

                # ── 执行图 ────────────────────────────────────────────────────
                final_state = engine.run(initial_state=initial_state)

                event_bus.emit("pipeline_end", success=final_state.get("error") is None)

                # 被审批拒绝的特殊情况
                if not final_state.get("approved", True):
                    return ExecutionResult(
                        success=False,
                        response=f"[拒绝] {final_state.get('approval_reason', '')}",
                        model=ctx.model,
                        task_type=ctx.task_type,
                    )

            except Exception as e:
                self._failed_calls += 1
                logger.error(f"[Pipeline] 执行失败: {e}", exc_info=True)
                root_span.record_exception(e)
                event_bus.emit("error", stage="pipeline", error=str(e))
                total_ms = (time.perf_counter() - t_total_start) * 1000
                return ExecutionResult(
                    success=False,
                    response="",
                    model=ctx.model,
                    task_type=ctx.task_type,
                    total_ms=round(total_ms, 2),
                    error=str(e),
                )

        error = final_state.get("error")
        if error:
            self._failed_calls += 1

        total_ms = (time.perf_counter() - t_total_start) * 1000
        return ExecutionResult(
            success=error is None,
            response=final_state.get("response", ""),
            model=final_state.get("model", ctx.model),
            task_type=ctx.task_type,
            cache_hit=final_state.get("cache_hit", False),
            total_ms=round(total_ms, 2),
            stage_times=final_state.get("stage_times", {}),
            error=error,
            truncated=final_state.get("truncated", False),
            tool_calls_made=ctx._tool_calls_made,
        )

    # ─── 各阶段实现 ────────────────────────────────────────────────────────────
    def _stage_decompose(self, ctx: ExecutionContext):
        """阶段1：任务分解。返回 (ctx, DecomposedTask|None)。"""
        t = time.perf_counter()
        result = self._decomposer.decompose(ctx.message, ctx.task_type)
        if result.is_complex:
            logger.info(f"[Stage1:Decompose] 拆解为 {len(result.subtasks)} 个子任务")
        ctx.record_stage("decompose", (time.perf_counter() - t) * 1000)
        return ctx, result if result.is_complex else None

    def _stage_pre_approve(self, ctx: ExecutionContext) -> ExecutionContext:
        t = time.perf_counter()
        if self._approval_system:
            approved, reason = self._approval_system.approve(ctx.task_type, ctx.message)
            ctx.approved = approved
            ctx.approval_reason = reason
        else:
            ctx.approved = True
            ctx.approval_reason = "auto_approved"
        ctx.record_stage("pre_approve", (time.perf_counter() - t) * 1000)
        return ctx

    def _stage_micro_compact(self, ctx: ExecutionContext) -> ExecutionContext:
        t = time.perf_counter()
        if ctx.messages:
            ctx.messages = self._micro.compact(ctx.messages)
        ctx.record_stage("micro_compact", (time.perf_counter() - t) * 1000)
        return ctx

    def _stage_credit_check(self, ctx: ExecutionContext) -> ExecutionContext:
        t = time.perf_counter()
        if self._credit_monitor and self._credit_monitor.should_fallback():
            fallback_cfg = self._credit_monitor.activate_fallback()
            ctx.model = fallback_cfg.get("model", ctx.model)
            ctx.api_key = fallback_cfg.get("api_key", ctx.api_key)
            ctx.base_url = fallback_cfg.get("base_url", ctx.base_url)
            logger.warning(f"[Stage4:Credit] 已切换到兜底模型: {ctx.model}")
        ctx.record_stage("credit_check", (time.perf_counter() - t) * 1000)
        return ctx

    def _stage_api_call(self, ctx: ExecutionContext) -> ExecutionContext:
        t = time.perf_counter()

        # ── AgenticLoop 分支（tool_use 循环）──────────────────────────────────
        if ctx.use_tools:
            ctx.response = self._run_agentic(ctx)
            ctx.record_stage("api_call", (time.perf_counter() - t) * 1000)
            return ctx

        # 先查缓存
        if ctx.use_cache:
            cached = self._cache.get(ctx.message, ctx.model)
            if cached is not None:
                ctx.response = cached
                ctx.cache_hit = True
                logger.info(f"[Stage5:API] 缓存命中，跳过API调用")
                ctx.record_stage("api_call", (time.perf_counter() - t) * 1000)
                return ctx

        # 构建消息列表
        messages = self._build_messages(ctx)

        # 熔断器调用
        breaker = self._breaker_registry.get_breaker(ctx.model)
        try:
            response = breaker.call(self._call_api, ctx, messages)
            ctx.response = response
            breaker.record_success()
        except CircuitOpenError as e:
            ctx.error = str(e)
            ctx.response = f"[熔断] {e}"
        except Exception as e:
            ctx.error = str(e)
            ctx.response = f"[API错误] {e}"

        ctx.record_stage("api_call", (time.perf_counter() - t) * 1000)
        return ctx

    def _run_agentic(self, ctx: ExecutionContext) -> str:
        """
        调用 AgenticLoop 执行 streaming tool_use 循环。
        。
        """
        from executor.agentic_loop import run_agentic
        from tools import build_tool_registry

        tools = build_tool_registry(ctx.enabled_tools)

        # 判断 provider
        if ctx.model.startswith("claude-"):
            provider = "claude"
            from core.config import GiraffeConfig
            _cfg = GiraffeConfig.get()
            project = _cfg.get_value("router.primary_model.project") or None
            region = _cfg.get_value("router.claude_location") or "global"
            from anthropic import AnthropicVertex
            client = AnthropicVertex(project_id=project, region=region)
        elif "grok" in ctx.model.lower():
            provider = "grok"
            from openai import OpenAI
            import google.auth
            import google.auth.transport.requests
            creds, project = google.auth.default(
                scopes=["https://www.googleapis.com/auth/cloud-platform"]
            )
            creds.refresh(google.auth.transport.requests.Request())
            client = OpenAI(
                base_url=f"https://aiplatform.googleapis.com/v1/projects/{project}/locations/global/endpoints/openapi",
                api_key=creds.token,
            )
        else:
            provider = "gemini"
            from google import genai
            client = genai.Client()

        def _on_text(t: str):
            print(t, end="", flush=True)

        def _on_tool_start(name: str, args: dict):
            logger.info(f"[AgenticLoop] 调用工具: {name}")

        def _on_tool_done(uid: str, result):
            status = "✅" if not result.is_error else "❌"
            logger.info(f"[AgenticLoop] 工具完成 {status}: {uid}")

        agentic_result = run_agentic(
            provider=provider,
            client=client,
            model=ctx.model,
            tools=tools,
            user_message=ctx.message,
            system=ctx.system_prompt,
            history=ctx.messages,
            config={"max_tokens": ctx.max_tokens},
            on_text=_on_text,
            on_tool_start=_on_tool_start,
            on_tool_done=_on_tool_done,
        )

        if agentic_result.error:
            ctx.error = agentic_result.error
            return f"[AgenticLoop 错误] {agentic_result.error}"

        ctx._tool_calls_made = agentic_result.tool_calls_made
        logger.info(
            f"[AgenticLoop] 完成: turns={agentic_result.turns} "
            f"tool_calls={agentic_result.tool_calls_made}"
        )
        return agentic_result.final_text

    def _build_messages(self, ctx: ExecutionContext) -> list[dict]:
        """构建发送给API的消息列表。支持多模态图像输入。"""
        msgs = []
        if ctx.system_prompt:
            msgs.append({"role": "system", "content": ctx.system_prompt})
        msgs.extend(ctx.messages or [])
        # 始终将当前用户消息追加到末尾（ctx.messages 是历史，ctx.message 是本次新消息）
        if ctx.images:
            from integration.multimodal import build_multimodal_content
            content = build_multimodal_content(ctx.message, ctx.images)
            msgs.append({"role": "user", "content": content})
        else:
            msgs.append({"role": "user", "content": ctx.message})
        return msgs

    def _call_api(self, ctx: ExecutionContext, messages: list[dict]) -> str:
        """实际调用API，根据配置选择 ADC 认证或 API Key 认证。"""
        use_adc = not ctx.api_key or ctx.api_key.startswith("${")

        # ── Claude ──────────────────────────────────────
        if ctx.model.startswith("claude-"):
            if use_adc:
                from core.config import GiraffeConfig
                _cfg = GiraffeConfig.get()
                _project = _cfg.get_value("router.primary_model.project") or None
                return self._call_claude_rawpredict(ctx, messages, _project, _cfg)
            else:
                return self._call_claude_apikey(ctx, messages)

        # ── Grok ──────────────────────────────────────
        elif "grok" in ctx.model.lower():
            if use_adc:
                return self._call_grok_xai(ctx, messages)
            # 使用 API Key 时，由于 xAI 兼容 OpenAI，穿透到最下方的通用 REST 客户端

        # ── Gemini ──────────────────────────────────────
        elif ctx.model.startswith("gemini-"):
            return self._call_gemini(ctx, messages, use_adc)

        # ── 兼容 OpenAI 协议的 API Key 调用 (OpenAI, DeepSeek, Mistral, xAI 等) ──
        if use_adc:
            logger.warning(f"[API] 模型 {ctx.model} 不支持 ADC，将尝试使用空 API Key 调用兼容接口")
            
        import json, urllib.request, urllib.error
        payload = {
            "model": ctx.model,
            "messages": messages,
            "max_tokens": ctx.max_tokens,
            "temperature": ctx.temperature,
        }
        if getattr(ctx, 'mcp_tools', None):
            payload["tools"] = ctx.mcp_tools
        data = json.dumps(payload).encode("utf-8")
        base_url = getattr(ctx, 'base_url', '') or 'https://api.openai.com/v1'
        url = f"{base_url.rstrip('/')}/chat/completions"
        req = urllib.request.Request(
            url,
            data=data,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {ctx.api_key}",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                resp_data = json.loads(resp.read().decode("utf-8"))
                if self._credit_monitor:
                    self._credit_monitor.check_credit(200, ctx.model)
                return resp_data["choices"][0]["message"]["content"]
        except urllib.error.HTTPError as e:
            if self._credit_monitor:
                self._credit_monitor.check_credit(e.code, ctx.model)
            raise

    def _call_gemini(
        self,
        ctx: ExecutionContext,
        messages: list[dict],
        use_adc: bool,
    ) -> str:
        """调用 Gemini 平台（支持 Vertex ADC 或 Google AI Studio API Key）"""
        try:
            from google import genai
            from google.genai import types
        except ImportError:
            return f"[Giraffe模拟响应] 缺少 google-genai | 模型:{ctx.model} | 消息:{ctx.message[:50]}..."

        contents = []
        system_instruction = None
        for m in messages:
            role = m.get("role")
            content = m.get("content", "")
            if role == "system":
                system_instruction = content
                continue

            gemini_role = "model" if role == "assistant" else "user"
            if isinstance(content, list):
                parts = []
                for p in content:
                    if p.get("type") == "text":
                        parts.append(types.Part.from_text(text=p["text"]))
                if parts:
                    contents.append(types.Content(role=gemini_role, parts=parts))
            else:
                contents.append(types.Content(role=gemini_role, parts=[types.Part.from_text(text=str(content))]))

        try:
            if use_adc:
                from core.config import GiraffeConfig
                _cfg = GiraffeConfig.get()
                _project = _cfg.get_value("router.primary_model.project") or None
                _location = _cfg.get_value("router.primary_model.location") or "global"
                client = genai.Client(vertexai=True, project=_project, location=_location)
                logger.debug(f"[API] Gemini 调用 (ADC): model={ctx.model} location={_location}")
            else:
                # 兼容自定 base_url
                base_url = getattr(ctx, "base_url", "")
                if base_url:
                    # 如果指定了 base_url，可以覆盖 http_options。但通常 genai 知道自己的默认值。
                    client = genai.Client(api_key=ctx.api_key, http_options={"base_url": base_url})
                else:
                    client = genai.Client(api_key=ctx.api_key)
                logger.debug(f"[API] Gemini 调用 (API Key): model={ctx.model}")

            config = types.GenerateContentConfig(
                temperature=ctx.temperature,
                max_output_tokens=ctx.max_tokens,
                system_instruction=system_instruction,
            )
            response = client.models.generate_content(
                model=ctx.model,
                contents=contents,
                config=config,
            )

            if self._credit_monitor:
                self._credit_monitor.check_credit(200, ctx.model)

            text = response.text
            if text is None:
                try:
                    parts = []
                    for cand in response.candidates:
                        for part in cand.content.parts:
                            if hasattr(part, 'text') and part.text:
                                parts.append(part.text)
                    text = "\n".join(parts) if parts else ""
                except Exception:
                    text = ""

            try:
                finish_reason = response.candidates[0].finish_reason
                if str(finish_reason).upper() in ('MAX_TOKENS', 'FINISHREASON.MAX_TOKENS', '2'):
                    ctx.truncated = True
                    logger.warning(
                        f"[API] 回复被 max_tokens={ctx.max_tokens} 截断 (model={ctx.model})"
                    )
            except Exception:
                pass
            return text
        except Exception as e:
            try:
                from google.api_core.exceptions import GoogleAPIError
                if isinstance(e, GoogleAPIError) and self._credit_monitor:
                    self._credit_monitor.check_credit(getattr(e, 'code', 500), ctx.model)
            except ImportError:
                pass
            raise

    def _call_claude_apikey(
        self,
        ctx: ExecutionContext,
        messages: list[dict],
    ) -> str:
        """调用 Anthropic 官方平台 (通过 API Key)"""
        try:
            from anthropic import Anthropic
        except ImportError:
            raise RuntimeError(
                "[Claude] 需要安装 anthropic 包: pip install anthropic"
            )

        system_content = None
        anthropic_messages = []
        for m in messages:
            role = m.get("role")
            content = m.get("content", "")
            if role == "system":
                system_content = content
            elif role in ("user", "assistant"):
                if isinstance(content, list):
                    anthropic_messages.append({"role": role, "content": content})
                else:
                    anthropic_messages.append({"role": role, "content": str(content)})

        if not anthropic_messages:
            anthropic_messages = [{"role": "user", "content": ctx.message}]

        logger.debug(f"[Claude] Anthropic API Key 调用: model={ctx.model}")
        
        # 支持 base_url 覆盖 (例如代理地址)
        base_url = getattr(ctx, "base_url", "")
        if base_url:
            client = Anthropic(api_key=ctx.api_key, base_url=base_url)
        else:
            client = Anthropic(api_key=ctx.api_key)

        kwargs = {
            "model": ctx.model,
            "max_tokens": ctx.max_tokens,
            "messages": anthropic_messages,
            "temperature": ctx.temperature,
        }
        if system_content:
            kwargs["system"] = system_content

        response = client.messages.create(**kwargs)

        if self._credit_monitor:
            self._credit_monitor.check_credit(200, ctx.model)

        text = "\n".join(
            block.text for block in response.content
            if hasattr(block, "text") and block.text
        )

        if response.stop_reason == "max_tokens":
            ctx.truncated = True
            logger.warning(
                f"[Claude] 回复被 max_tokens={ctx.max_tokens} 截断 (model={ctx.model})"
            )

        return text

    def _call_grok_xai(
        self,
        ctx: ExecutionContext,
        messages: list[dict],
    ) -> str:
        """
        调用 xAI Grok 模型（通过 Vertex AI OpenAI-compatible 端点）。

        认证：和 Gemini/Claude 一样使用 Google Cloud ADC（无需额外密钥）
        端点： https://aiplatform.googleapis.com/v1/projects/{project}/locations/global/endpoints/openapi
        格式： OpenAI-compatible Chat Completions
        模型名： xai/grok-4.20-reasoning
        文档： https://console.cloud.google.com/vertex-ai/publishers/xai/model-garden/grok-4.20-reasoning
        依赖： pip install openai google-auth
        """
        try:
            from openai import OpenAI
        except ImportError:
            raise RuntimeError(
                "[Grok] 需要安装 openai 包: pip install openai"
            )

        # 获取 ADC 令牌（和 Gemini/Claude 一致，无需额外配置）
        try:
            import google.auth
            import google.auth.transport.requests
            credentials, _ = google.auth.default(
                scopes=["https://www.googleapis.com/auth/cloud-platform"]
            )
            credentials.refresh(google.auth.transport.requests.Request())
            token = credentials.token
        except Exception as e:
            raise RuntimeError(
                f"[Grok] ADC 认证失败: {e}\n"
                "请运行: gcloud auth application-default login"
            )

        from core.config import GiraffeConfig
        _cfg = GiraffeConfig.get()
        project = _cfg.get_value("router.primary_model.project") or ""
        if not project:
            raise RuntimeError("[Grok] 配置中缺少 router.primary_model.project")

        base_url = (
            f"https://aiplatform.googleapis.com/v1/projects/{project}"
            f"/locations/global/endpoints/openapi"
        )

        client = OpenAI(
            api_key=token,       # ADC Bearer Token
            base_url=base_url,
        )

        # 构建消息列表
        openai_msgs: list[dict] = []
        if ctx.system_prompt:
            openai_msgs.append({"role": "system", "content": ctx.system_prompt})
        for msg in messages:
            role = msg.get("role", "user")
            content = msg.get("content", "")
            if role in ("user", "assistant", "system"):
                openai_msgs.append({"role": role, "content": str(content)})
        if not openai_msgs or openai_msgs[-1]["role"] != "user":
            openai_msgs.append({"role": "user", "content": ctx.message})

        logger.debug(
            f"[Grok] Vertex AI 调用: model={ctx.model} "
            f"project={project} msgs={len(openai_msgs)}"
        )

        try:
            response = client.chat.completions.create(
                model=ctx.model,          # 应为 "xai/grok-4.20-reasoning"
                messages=openai_msgs,
                max_tokens=ctx.max_tokens,
                temperature=ctx.temperature,
            )
            if self._credit_monitor:
                self._credit_monitor.check_credit(200, ctx.model)

            choice = response.choices[0]
            if choice.finish_reason == "length":
                ctx.truncated = True
                logger.warning(
                    f"[Grok] 回复被 max_tokens={ctx.max_tokens} 截断 (model={ctx.model})"
                )
            return choice.message.content or ""

        except Exception as e:
            if self._credit_monitor:
                code = getattr(e, "status_code", 500)
                self._credit_monitor.check_credit(code, ctx.model)
            raise

    def _call_claude_rawpredict(
        self,
        ctx: ExecutionContext,
        messages: list[dict],
        project: str,
        cfg,
    ) -> str:
        """
        Claude on Vertex AI 专用调用路径。
        使用官方 AnthropicVertex SDK（anthropic>=0.20），通过 ADC 自动认证。

        官方文档: https://docs.anthropic.com/en/api/claude-on-vertex-ai
        推荐端点: region="global"（最大可用性，无额外费用）
        """
        try:
            from anthropic import AnthropicVertex
        except ImportError:
            raise RuntimeError(
                "[Claude] 需要安装 anthropic 包: pip install anthropic"
            )

        # 解析 messages：将 system 和 user/assistant 分开
        system_content = None
        anthropic_messages = []
        for m in messages:
            role = m.get("role")
            content = m.get("content", "")
            if role == "system":
                system_content = content
            elif role in ("user", "assistant"):
                if isinstance(content, list):
                    anthropic_messages.append({"role": role, "content": content})
                else:
                    anthropic_messages.append({"role": role, "content": str(content)})

        if not anthropic_messages:
            anthropic_messages = [{"role": "user", "content": ctx.message}]

        # 官方推荐 region="global"（Claude Sonnet 4.6 及以上均支持）
        _region = cfg.get_value("router.claude_location") or "global"
        logger.debug(f"[Claude] AnthropicVertex: model={ctx.model} region={_region}")

        client = AnthropicVertex(project_id=project, region=_region)

        kwargs = {
            "model": ctx.model,
            "max_tokens": ctx.max_tokens,
            "messages": anthropic_messages,
            "temperature": ctx.temperature,
        }
        if system_content:
            kwargs["system"] = system_content

        response = client.messages.create(**kwargs)

        if self._credit_monitor:
            self._credit_monitor.check_credit(200, ctx.model)

        # 提取文本
        text = "\n".join(
            block.text for block in response.content
            if hasattr(block, "text") and block.text
        )

        # 检测截断
        if response.stop_reason == "max_tokens":
            ctx.truncated = True
            logger.warning(
                f"[Claude] 回复被 max_tokens={ctx.max_tokens} 截断 (model={ctx.model})"
            )

        return text

    def _stage_parallel_execute(self, ctx: ExecutionContext, decomposed) -> ExecutionContext:

        """阶段8（多子任务路径）：并行调用 API 执行每个子任务，聚合结果。"""
        from .parallel_executor import SubAgentTask as PExecTask
        t = time.perf_counter()
        tasks = []
        for sub in decomposed.subtasks:
            sub_ctx = ExecutionContext(
                message=sub.content,
                model=ctx.model,
                api_key=ctx.api_key,
                base_url=ctx.base_url,
                task_type=sub.task_type,
                messages=[],
                system_prompt=ctx.system_prompt,
                max_tokens=ctx.max_tokens,
                temperature=ctx.temperature,
                use_cache=ctx.use_cache,
            )
            def _make_fn(c):
                def fn():
                    messages = self._build_messages(c)
                    breaker = self._breaker_registry.get_breaker(c.model)
                    return breaker.call(self._call_api, c, messages)
                return fn
            tasks.append(PExecTask(
                name=sub.title,
                func=_make_fn(sub_ctx),
                model=ctx.model,
            ))
        results = self._parallel.execute_parallel(tasks)
        # 聚合：将所有子任务结果拼接
        parts = []
        for r in results:
            if r.success:
                parts.append(f"**{r.name}**\n{r.result}")
            else:
                parts.append(f"**{r.name}** ⚠️ 执行失败: {r.error}")
        ctx.response = "\n\n---\n\n".join(parts)
        ctx.record_stage("parallel_execute", (time.perf_counter() - t) * 1000)
        return ctx

    def _stage_deep_compact(self, ctx: ExecutionContext) -> ExecutionContext:
        t = time.perf_counter()
        if ctx.messages:
            ctx.messages = self._deep.check_and_compact(ctx.messages)
        ctx.record_stage("deep_compact", (time.perf_counter() - t) * 1000)
        return ctx

    def _stage_cache_store(self, ctx: ExecutionContext) -> ExecutionContext:
        t = time.perf_counter()
        if ctx.response and not ctx.cache_hit and not ctx.error:
            self._cache.check_and_store(ctx.message, ctx.response, ctx.model)
        ctx.record_stage("cache_store", (time.perf_counter() - t) * 1000)
        return ctx

    # ─── 统计 ─────────────────────────────────────────────────────────────────
    def stats(self) -> dict:
        return {
            "total_calls": self._total_calls,
            "failed_calls": self._failed_calls,
            "success_rate": round(
                (self._total_calls - self._failed_calls) / self._total_calls, 3
            ) if self._total_calls > 0 else 1.0,
            "cache": self._cache.stats(),
            "micro_compact": self._micro.stats(),
            "deep_compact": self._deep.stats(),
        }

    def __repr__(self) -> str:
        return f"ExecutorPipeline(calls={self._total_calls})"

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

    # 执行过程中填充
    approved: bool = True
    approval_reason: str = ""
    cache_hit: bool = False
    response: str = ""
    error: str | None = None
    stage_times: dict[str, float] = field(default_factory=dict)

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

    def _build_messages(self, ctx: ExecutionContext) -> list[dict]:
        """构建发送给API的消息列表。支持多模态图像输入。"""
        msgs = []
        if ctx.system_prompt:
            msgs.append({"role": "system", "content": ctx.system_prompt})
        msgs.extend(ctx.messages or [])
        if not any(m.get("role") == "user" for m in msgs):
            # 多模态：如果有图片，构建 Vision API 格式的 content
            if ctx.images:
                from integration.multimodal import build_multimodal_content
                content = build_multimodal_content(ctx.message, ctx.images)
                msgs.append({"role": "user", "content": content})
            else:
                msgs.append({"role": "user", "content": ctx.message})
        return msgs

    def _call_api(self, ctx: ExecutionContext, messages: list[dict]) -> str:
        """实际调用API，根据配置选择 ADC 认证或 OpenAI API Key 认证。"""
        use_adc = not ctx.api_key or ctx.api_key.startswith("${")

        if use_adc:
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
                            parts.append(types.Part.from_text(p["text"]))
                        # TODO: 处理多模态图片映射
                    if parts:
                        contents.append(types.Content(role=gemini_role, parts=parts))
                else:
                    contents.append(types.Content(role=gemini_role, parts=[types.Part.from_text(str(content))]))

            try:
                client = genai.Client(vertexai=True)
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
                
                # 检查信用状态
                if self._credit_monitor:
                    self._credit_monitor.check_credit(200, ctx.model)
                return response.text
            except Exception as e:
                try:
                    from google.api_core.exceptions import GoogleAPIError
                    if isinstance(e, GoogleAPIError) and self._credit_monitor:
                        self._credit_monitor.check_credit(getattr(e, 'code', 500), ctx.model)
                except ImportError:
                    pass
                raise
        else:
            # 兼容 OpenAI 协议的 API Key 调用
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

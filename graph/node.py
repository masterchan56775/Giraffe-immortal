"""
graph/node.py — 抽象节点基类 + 8 个具体阶段节点

将 ExecutorPipeline 的 8 个阶段重构为独立的 Node 子类，
每个 Node 只负责单一阶段逻辑，通过 GraphState 传递状态。
"""
from __future__ import annotations

import abc
import time
import logging
from typing import TYPE_CHECKING

from .state import GraphState

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


# ─── 抽象基类 ──────────────────────────────────────────────────────────────────
class Node(abc.ABC):
    """
    DAG 图节点抽象基类。

    每个节点封装一个处理阶段：
    - name: 节点唯一标识
    - run(state): 接收全局 GraphState，处理后原地更新并返回

    子类只需实现 run()。
    """

    @property
    @abc.abstractmethod
    def name(self) -> str:
        """节点唯一标识。"""

    @abc.abstractmethod
    def run(self, state: GraphState) -> GraphState:
        """
        执行节点逻辑，原地修改并返回 state。

        Args:
            state: 全局共享状态字典

        Returns:
            更新后的 GraphState
        """

    def _record(self, state: GraphState, stage: str, t_start: float) -> None:
        """记录阶段耗时到 state。"""
        ms = (time.perf_counter() - t_start) * 1000
        if "stage_times" not in state:
            state["stage_times"] = {}
        state["stage_times"][stage] = round(ms, 2)
        if "stage_history" not in state:
            state["stage_history"] = []
        state["stage_history"].append(stage)

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(name={self.name})"


# ─── 具体节点实现 ──────────────────────────────────────────────────────────────

class DecomposeNode(Node):
    """阶段1：任务分解 — 包装 TaskDecomposer.decompose()。"""

    name = "decompose"

    def __init__(self, decomposer) -> None:
        self._decomposer = decomposer

    def run(self, state: GraphState) -> GraphState:
        t = time.perf_counter()
        try:
            result = self._decomposer.decompose(
                state.get("message", ""),
                state.get("task_type", "chat"),
            )
            state["decomposed"] = result if result.is_complex else None
            if result.is_complex:
                logger.info(f"[DecomposeNode] 拆解为 {len(result.subtasks)} 个子任务")
        except Exception as e:
            logger.warning(f"[DecomposeNode] 拆解失败（继续执行）: {e}")
            state["decomposed"] = None
        self._record(state, "decompose", t)
        return state


class ApprovalNode(Node):
    """阶段2：预审批 — 包装 ApprovalSystem.approve()。"""

    name = "pre_approve"

    def __init__(self, approval_system=None) -> None:
        self._approval_system = approval_system

    def run(self, state: GraphState) -> GraphState:
        t = time.perf_counter()
        if self._approval_system:
            approved, reason = self._approval_system.approve(
                state.get("task_type", "chat"),
                state.get("message", ""),
            )
            state["approved"] = approved
            state["approval_reason"] = reason
        else:
            state["approved"] = True
            state["approval_reason"] = "auto_approved"
        self._record(state, "pre_approve", t)
        return state


class MicroCompactNode(Node):
    """阶段3：微压缩 — 包装 MicroCompact.compact()。"""

    name = "micro_compact"

    def __init__(self, micro_compact) -> None:
        self._micro = micro_compact

    def run(self, state: GraphState) -> GraphState:
        t = time.perf_counter()
        msgs = state.get("messages", [])
        if msgs:
            state["messages"] = self._micro.compact(msgs)
        self._record(state, "micro_compact", t)
        return state


class CreditCheckNode(Node):
    """阶段4：信用检查 — 包装 CreditMonitor.should_fallback()。"""

    name = "credit_check"

    def __init__(self, credit_monitor=None) -> None:
        self._credit_monitor = credit_monitor

    def run(self, state: GraphState) -> GraphState:
        t = time.perf_counter()
        if self._credit_monitor and self._credit_monitor.should_fallback():
            fallback_cfg = self._credit_monitor.activate_fallback()
            state["model"] = fallback_cfg.get("model", state.get("model", ""))
            state["api_key"] = fallback_cfg.get("api_key", state.get("api_key", ""))
            state["base_url"] = fallback_cfg.get("base_url", state.get("base_url", ""))
            logger.warning(f"[CreditCheckNode] 已切换到兜底模型: {state['model']}")
        self._record(state, "credit_check", t)
        return state


class APICallNode(Node):
    """
    阶段5：API 调用 — 封装缓存查询 + 熔断器 + OpenAI 兼容调用。

    此节点执行后：
    - 成功：state["response"] 被填充，state["error"] = None
    - 失败：state["error"] 被填充
    """

    name = "api_call"

    def __init__(self, pipeline_ref) -> None:
        """
        Args:
            pipeline_ref: ExecutorPipeline 实例引用，复用其 _call_api 和 _cache。
        """
        self._pipeline = pipeline_ref

    def run(self, state: GraphState) -> GraphState:
        t = time.perf_counter()
        from executor.pipeline import ExecutionContext

        # 先查缓存
        if state.get("use_cache", True):
            cached = self._pipeline._cache.get(state.get("message", ""), state.get("model", ""))
            if cached is not None:
                state["response"] = cached
                state["cache_hit"] = True
                logger.info("[APICallNode] 缓存命中，跳过 API 调用")
                self._record(state, "api_call", t)
                return state

        # 构建 ExecutionContext（复用 pipeline 的 _build_messages 逻辑）
        ctx = ExecutionContext(
            message=state.get("message", ""),
            model=state.get("model", "mimo-v2.5"),
            api_key=state.get("api_key", ""),
            base_url=state.get("base_url", ""),
            task_type=state.get("task_type", "chat"),
            messages=list(state.get("messages", [])),
            system_prompt=state.get("system_prompt", ""),
            images=list(state.get("images", [])),
            mcp_tools=list(state.get("mcp_tools", [])),
            max_tokens=state.get("max_tokens", 2048),
            temperature=state.get("temperature", 0.7),
        )
        messages = self._pipeline._build_messages(ctx)

        try:
            breaker = self._pipeline._breaker_registry.get_breaker(ctx.model)
            response = breaker.call(self._pipeline._call_api, ctx, messages)
            state["response"] = response
            state["error"] = None
            breaker.record_success()
        except Exception as e:
            state["error"] = str(e)
            state["response"] = ""
            logger.error(f"[APICallNode] API 调用失败: {e}")

        self._record(state, "api_call", t)
        return state


class SelfHealNode(Node):
    """
    自愈节点 — 包装 ErrorProcessor.process() 和抗体匹配。
    在 API 调用失败后触发，实现重试或降级策略。
    """

    name = "self_heal"

    def __init__(self, error_processor, model_chain: list[str] | None = None) -> None:
        self._error_processor = error_processor
        self._model_chain = model_chain or []

    def run(self, state: GraphState) -> GraphState:
        t = time.perf_counter()
        error = state.get("error", "")
        retry_count = state.get("retry_count", 0)

        if error and self._error_processor:
            report = self._error_processor.process(
                error=error,
                model=state.get("model", ""),
                model_chain=self._model_chain,
            )
            # 如果错误处理建议切换模型
            if report.recovery_action and report.recovery_action.get("type") == "switch_model":
                new_model = report.recovery_action.get("model", "")
                if new_model:
                    state["model"] = new_model
                    logger.info(f"[SelfHealNode] 切换模型: {new_model}")

        state["retry_count"] = retry_count + 1
        state["error"] = None  # 清除错误，允许下一次重试
        self._record(state, "self_heal", t)
        return state


class DeepCompactNode(Node):
    """阶段6：深度压缩 — 包装 DeepCompact.check_and_compact()。"""

    name = "deep_compact"

    def __init__(self, deep_compact) -> None:
        self._deep = deep_compact

    def run(self, state: GraphState) -> GraphState:
        t = time.perf_counter()
        msgs = state.get("messages", [])
        if msgs:
            state["messages"] = self._deep.check_and_compact(msgs)
        self._record(state, "deep_compact", t)
        return state


class CacheNode(Node):
    """阶段7：响应缓存 — 包装 ResponseCache 的读写逻辑。"""

    name = "cache_store"

    def __init__(self, cache) -> None:
        self._cache = cache

    def run(self, state: GraphState) -> GraphState:
        t = time.perf_counter()
        response = state.get("response", "")
        cache_hit = state.get("cache_hit", False)
        error = state.get("error")

        if response and not cache_hit and not error:
            self._cache.check_and_store(
                state.get("message", ""),
                response,
                state.get("model", ""),
            )
        self._record(state, "cache_store", t)
        return state


class ParallelExecuteNode(Node):
    """阶段8（可选）：并行子任务执行。"""

    name = "parallel_execute"

    def __init__(self, pipeline_ref) -> None:
        self._pipeline = pipeline_ref

    def run(self, state: GraphState) -> GraphState:
        t = time.perf_counter()
        decomposed = state.get("decomposed")
        if decomposed is None or not decomposed.is_complex:
            self._record(state, "parallel_execute", t)
            return state

        from executor.pipeline import ExecutionContext
        from executor.parallel_executor import SubAgentTask as PExecTask

        tasks = []
        for sub in decomposed.subtasks:
            sub_ctx = ExecutionContext(
                message=sub.content,
                model=state.get("model", ""),
                api_key=state.get("api_key", ""),
                base_url=state.get("base_url", ""),
                task_type=sub.task_type,
                messages=[],
                system_prompt=state.get("system_prompt", ""),
                max_tokens=state.get("max_tokens", 2048),
                temperature=state.get("temperature", 0.7),
                use_cache=state.get("use_cache", True),
            )

            def _make_fn(c):
                def fn():
                    msgs = self._pipeline._build_messages(c)
                    breaker = self._pipeline._breaker_registry.get_breaker(c.model)
                    return breaker.call(self._pipeline._call_api, c, msgs)
                return fn

            tasks.append(PExecTask(
                name=sub.title,
                func=_make_fn(sub_ctx),
                model=state.get("model", ""),
            ))

        results = self._pipeline._parallel.execute_parallel(tasks)
        parts = []
        for r in results:
            if r.success:
                parts.append(f"**{r.name}**\n{r.result}")
            else:
                parts.append(f"**{r.name}** ⚠️ 执行失败: {r.error}")
        state["response"] = "\n\n---\n\n".join(parts)
        self._record(state, "parallel_execute", t)
        return state

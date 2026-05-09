"""
RouterEngine — 路由主引擎
协调双维度路由（关键词 + LLM）和五档模式
"""
from __future__ import annotations

import logging
import time

from dataclasses import dataclass
from .intent_classifier import IntentClassifier
from .gatekeeper import Gatekeeper
from .intent_classifier import TaskType
from .query_complexity import ComplexityEstimator, ComplexityLevel
from .llm_classifier import LLMClassifier
from .model_registry import ModelRegistry
from .subagent_router import SubAgentRouter
from observability.tracer import get_tracer

logger = logging.getLogger(__name__)


@dataclass
class RouteDecision:
    """最终路由决策，包含所有关键信息。"""
    task_type: TaskType
    tier: RouteTier
    primary_model: str
    fallback_model: str
    emergency_model: str
    auto_execute: bool
    requires_confirmation: bool
    cost_threshold: float
    complexity_level: ComplexityLevel
    confidence: float
    classify_method: str    # "keyword" | "llm" | "default"
    latency_ms: float = 0.0
    matched_keyword: str = ""
    use_swarm: bool = False  # 是否启动 Swarm 群组讨论模式

    def to_dict(self) -> dict:
        return {
            "task_type": self.task_type.value,
            "tier": self.tier.value,
            "primary_model": self.primary_model,
            "fallback_model": self.fallback_model,
            "emergency_model": self.emergency_model,
            "auto_execute": self.auto_execute,
            "requires_confirmation": self.requires_confirmation,
            "cost_threshold": self.cost_threshold,
            "complexity": self.complexity_level.value,
            "confidence": round(self.confidence, 3),
            "classify_method": self.classify_method,
            "latency_ms": round(self.latency_ms, 2),
            "use_swarm": self.use_swarm,
        }


class RouterEngine:
    """
    路由主引擎（双维度路由）。

    流程：
    1. IntentClassifier 关键词匹配（<1ms）
    2. 若置信度不足 → LLMClassifier（~200ms）
    3. ComplexityEstimator 复杂度评估
    4. Gatekeeper 五档路由判断
    5. ModelRegistry 获取模型降级链

    输出：RouteDecision（包含模型选择+执行权限+成本阈值）
    """

    def __init__(
        self,
        config: dict | None = None,
        model_registry: ModelRegistry | None = None,
    ) -> None:
        cfg = config or {}
        self._cfg = cfg

        # 子组件
        self._intent_clf = IntentClassifier()
        self._complexity_est = ComplexityEstimator()
        self._gatekeeper = Gatekeeper(cfg.get("tiers"))
        self._llm_clf: LLMClassifier | None = None
        self._model_registry = model_registry or ModelRegistry.get()
        self._subagent_router = SubAgentRouter()

        # 统计
        self._route_count = 0
        self._keyword_hits = 0
        self._llm_hits = 0

        # 配置LLM分类器（可选）
        if cfg.get("llm_fallback", True):
            primary = cfg.get("primary_model", {})
            self._llm_clf = LLMClassifier(
                model=cfg.get("routing_model", "gemini-3.1-flash-lite"),
                api_key=primary.get("api_key", ""),
                base_url=primary.get("base_url", ""),
            )

        # 加载模型矩阵
        if "model_matrix" in cfg:
            self._model_registry.load_from_config(cfg["model_matrix"])

    def route(self, message: str, has_image: bool = False) -> RouteDecision:
        """
        对用户消息进行完整的路由决策。

        Args:
            message: 用户输入的消息文本
            has_image: 是否包含图片

        Returns:
            RouteDecision: 完整的路由决策
        """
        tracer = get_tracer("giraffe.router")
        with tracer.start_as_current_span("giraffe.router.route") as span:
            t_start = time.perf_counter()
            self._route_count += 1

            # ── 维度1：关键词匹配 ──────────────────────────────────────────────
            classify_result = self._intent_clf.classify(message, has_image=has_image)

            if self._intent_clf.is_ambiguous(classify_result) and self._llm_clf:
                # ── 维度2：LLM分类（仅在模糊时触发）────────────────────────────
                llm_result = self._llm_clf.classify(message)
                if llm_result.confidence > classify_result.confidence:
                    classify_result = llm_result
                    self._llm_hits += 1
                    logger.debug(f"[Router] LLM分类覆盖: {classify_result.task_type.value}")
            else:
                self._keyword_hits += 1

            task_type = classify_result.task_type

            # ── 复杂度评估 ────────────────────────────────────────────────────
            complexity_result = self._complexity_est.estimate(message, base_task_type=task_type)

            # 如果复杂度分析建议不同任务类型，则采纳
            if complexity_result.suggested_task_type != task_type:
                logger.debug(
                    f"[Router] 复杂度调整: {task_type.value} → "
                    f"{complexity_result.suggested_task_type.value}"
                )
                task_type = complexity_result.suggested_task_type

            # ── 五档路由 ──────────────────────────────────────────────────────
            gate_result = self._gatekeeper.check(task_type, complexity_result.level)

            # ── 获取模型降级链 ────────────────────────────────────────────────
            model_chain = self._model_registry.get_model_chain(task_type.value)

            t_end = time.perf_counter()
            latency_ms = (t_end - t_start) * 1000

            decision = RouteDecision(
                task_type=task_type,
                tier=gate_result.tier,
                primary_model=model_chain[0],
                fallback_model=model_chain[1],
                emergency_model=model_chain[2],
                auto_execute=gate_result.auto_execute,
                requires_confirmation=gate_result.requires_confirmation,
                cost_threshold=gate_result.cost_threshold,
                complexity_level=complexity_result.level,
                confidence=classify_result.confidence,
                classify_method=classify_result.method,
                latency_ms=latency_ms,
                matched_keyword=classify_result.matched_keyword,
                use_swarm=self._should_use_swarm(task_type, complexity_result.level),
            )

            # 记录 Span 属性
            span.set_attribute("giraffe.task_type", task_type.value)
            span.set_attribute("giraffe.tier", gate_result.tier.value)
            span.set_attribute("giraffe.model", model_chain[0])
            span.set_attribute("giraffe.classify_method", classify_result.method)
            span.set_attribute("giraffe.confidence", round(classify_result.confidence, 3))
            span.set_attribute("giraffe.latency_ms", round(latency_ms, 2))

            logger.info(
                f"[Router] ✅ {task_type.value} | {gate_result.tier.value} | "
                f"model={model_chain[0]} | auto={gate_result.auto_execute} | "
                f"{latency_ms:.1f}ms"
            )
            return decision

    def route_and_get_runtime(self, message: str, has_image: bool = False) -> tuple[str, dict]:
        """
        一次调用返回（模型名称, 运行时配置）。
        简化调用链路的便捷方法。
        """
        decision = self.route(message, has_image)
        runtime = {
            "task_type": decision.task_type.value,
            "tier": decision.tier.value,
            "auto_execute": decision.auto_execute,
            "cost_threshold": decision.cost_threshold,
            "model_chain": [
                decision.primary_model,
                decision.fallback_model,
                decision.emergency_model,
            ],
        }
        return decision.primary_model, runtime

    # ─── 统计 ─────────────────────────────────────────────────────────────────
    def _should_use_swarm(
        self, task_type: TaskType, complexity: ComplexityLevel
    ) -> bool:
        """
        判断是否应该启动 Swarm 群组讨论模式。

        触发条件：任务类型为 code_large 或 reasoning，
                  且复杂度为 high 或以上。
        """
        swarm_task_types = {
            TaskType.CODE_LARGE,
            TaskType.REASONING,
        }
        swarm_complexity = {
            ComplexityLevel.COMPLEX,
            ComplexityLevel.EXTREME,
        }
        return task_type in swarm_task_types and complexity in swarm_complexity

    def stats(self) -> dict:
        return {
            "total_routes": self._route_count,
            "keyword_hits": self._keyword_hits,
            "llm_hits": self._llm_hits,
            "keyword_ratio": (
                round(self._keyword_hits / self._route_count, 3)
                if self._route_count > 0 else 0
            ),
        }

    def __repr__(self) -> str:
        return f"RouterEngine(routes={self._route_count})"

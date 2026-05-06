"""
SubAgentRouter — 子Agent路由器
负责将任务路由到适合的子Agent并支持并行执行
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from .intent_classifier import TaskType

logger = logging.getLogger(__name__)


class SubAgentType(str, Enum):
    TEXT_REASONING = "text_reasoning"    # 纯文本推理 → mimo-v2.5
    CODE           = "code"              # 代码任务 → claude-sonnet-4.6
    DEEP_REASONING = "deep_reasoning"    # 深度推理 → claude-opus-4.7
    MULTI_MODEL    = "multi_model"       # 多模型协作 → opus+gpt-5.5
    VISION         = "vision"            # 视觉任务 → mimo-v2-omni


# 子Agent类型 → 推荐模型
SUBAGENT_MODEL_MAP: dict[SubAgentType, str] = {
    SubAgentType.TEXT_REASONING: "mimo-v2.5",
    SubAgentType.CODE:           "claude-sonnet-4.6",
    SubAgentType.DEEP_REASONING: "claude-opus-4.7",
    SubAgentType.MULTI_MODEL:    "opus-4.7+gpt-5.5",
    SubAgentType.VISION:         "mimo-v2-omni",
}

# 任务类型 → 子Agent类型
TASK_TO_SUBAGENT: dict[TaskType, SubAgentType] = {
    TaskType.CHAT:            SubAgentType.TEXT_REASONING,
    TaskType.CODE_SMALL:      SubAgentType.CODE,
    TaskType.CODE_MEDIUM:     SubAgentType.CODE,
    TaskType.CODE_LARGE:      SubAgentType.CODE,
    TaskType.REASONING_LIGHT: SubAgentType.TEXT_REASONING,
    TaskType.REASONING:       SubAgentType.DEEP_REASONING,
    TaskType.VISION:          SubAgentType.VISION,
    TaskType.SEARCH:          SubAgentType.TEXT_REASONING,
    TaskType.SUBTASK:         SubAgentType.TEXT_REASONING,
}


@dataclass
class SubAgentTask:
    """子Agent任务描述。"""
    task_id: str
    task_type: SubAgentType
    model: str
    payload: Any
    priority: int = 5
    metadata: dict = field(default_factory=dict)


@dataclass
class SubAgentRoute:
    """子Agent路由结果。"""
    subagent_type: SubAgentType
    model: str
    parallel: bool = False
    reason: str = ""


class SubAgentRouter:
    """
    子Agent路由器。
    决定每个子任务使用哪种子Agent类型和模型。
    支持并行路由（多Agent同时执行）。
    """

    def __init__(self, model_map: dict | None = None) -> None:
        self._model_map: dict[SubAgentType, str] = SUBAGENT_MODEL_MAP.copy()
        if model_map:
            self._model_map.update(model_map)

    def route(self, task_type: TaskType, complex_task: bool = False) -> SubAgentRoute:
        """
        根据任务类型路由到合适的子Agent。
        complex_task=True 时考虑多模型协作。
        """
        if complex_task and task_type == TaskType.REASONING:
            subagent = SubAgentType.MULTI_MODEL
        else:
            subagent = TASK_TO_SUBAGENT.get(task_type, SubAgentType.TEXT_REASONING)

        model = self._model_map[subagent]
        return SubAgentRoute(
            subagent_type=subagent,
            model=model,
            parallel=False,
            reason=f"task_type={task_type.value} → subagent={subagent.value}",
        )

    def route_parallel(self, task_types: list[TaskType]) -> list[SubAgentRoute]:
        """
        为多个并行子任务分别路由。
        """
        routes = []
        for tt in task_types:
            route = self.route(tt)
            route = SubAgentRoute(
                subagent_type=route.subagent_type,
                model=route.model,
                parallel=True,
                reason=route.reason + " [parallel]",
            )
            routes.append(route)
        return routes

    def build_subagent_tasks(
        self,
        task_types: list[TaskType],
        payloads: list[Any],
    ) -> list[SubAgentTask]:
        """构建多个子Agent任务对象（用于并行执行器）。"""
        import uuid
        tasks = []
        for i, (tt, payload) in enumerate(zip(task_types, payloads)):
            route = self.route(tt)
            tasks.append(SubAgentTask(
                task_id=f"sub_{uuid.uuid4().hex[:6]}",
                task_type=route.subagent_type,
                model=route.model,
                payload=payload,
                priority=5,
            ))
        return tasks

    def __repr__(self) -> str:
        return f"SubAgentRouter(models={len(self._model_map)})"

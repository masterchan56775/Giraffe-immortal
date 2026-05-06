"""
TaskDecomposer — 任务分解器
将复杂任务拆解为可独立执行的子任务
"""
from __future__ import annotations

import logging
import re
import uuid
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class SubTask:
    """子任务数据对象。"""
    sub_id: str = field(default_factory=lambda: f"sub_{uuid.uuid4().hex[:6]}")
    title: str = ""
    content: str = ""
    task_type: str = "chat"
    order: int = 0
    dependencies: list[str] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "sub_id": self.sub_id,
            "title": self.title,
            "content": self.content,
            "task_type": self.task_type,
            "order": self.order,
        }


@dataclass
class DecomposedTask:
    """分解结果。"""
    original: str
    subtasks: list[SubTask]
    is_complex: bool = False
    decompose_reason: str = ""

    @property
    def is_single(self) -> bool:
        return len(self.subtasks) == 1


# 触发分解的模式（包含多步骤指示词）
MULTI_STEP_PATTERNS = [
    r"第[一二三四五六七八九十\d]+步",
    r"\d+[.、。]\s*\w",
    r"首先.*然后.*最后",
    r"先.*再.*然后",
    r"步骤|分步|逐步",
    r"多个|几个.*任务",
]

# 分隔符，用于拆分步骤
STEP_SEPARATORS = [
    r"\n第[一二三四五六七八九十\d]+步[：:]?",
    r"\n\d+[.、。]\s",
    r"\n[-•]\s",
]


class TaskDecomposer:
    """
    任务分解器。
    检测多步骤任务，将其拆解为有序子任务列表。
    单一任务直接透传，不增加开销。
    """

    def __init__(self) -> None:
        self._compiled_patterns = [
            re.compile(p, re.IGNORECASE | re.DOTALL) for p in MULTI_STEP_PATTERNS
        ]
        self._compiled_separators = [
            re.compile(p, re.IGNORECASE) for p in STEP_SEPARATORS
        ]
        self._decompose_count = 0

    def decompose(self, message: str, task_type: str = "chat") -> DecomposedTask:
        """
        分解任务。
        - 单一任务：直接返回包含一个子任务的结果
        - 多步骤任务：拆分为多个子任务

        Args:
            message: 用户输入消息，必须为字符串。为None或非字符串时抛出 TypeError。
            task_type: 任务类型字符串。

        Raises:
            TypeError: message 不是字符串时。
        """
        if message is None:
            raise TypeError(
                f"[TaskDecomposer] message 必须是字符串，得到 None。"
                f"请检查调用方。"
            )
        if not isinstance(message, str):
            raise TypeError(
                f"[TaskDecomposer] message 必须是 str，得到 {type(message).__name__}。"
            )
        # 空字符串直接返回单任务（不分解）
        if not message.strip():
            return DecomposedTask(
                original=message,
                subtasks=[SubTask(title="主任务", content=message, task_type=task_type, order=0)],
                is_complex=False,
                decompose_reason="空消息，不分解",
            )

        if self._is_multi_step(message):
            subtasks = self._split_into_subtasks(message, task_type)
            if len(subtasks) > 1:
                self._decompose_count += 1
                logger.info(f"[TaskDecomposer] 检测到多步骤任务，拆解为{len(subtasks)}个子任务")
                return DecomposedTask(
                    original=message,
                    subtasks=subtasks,
                    is_complex=True,
                    decompose_reason="检测到多步骤结构",
                )

        # 单一任务
        return DecomposedTask(
            original=message,
            subtasks=[SubTask(title="主任务", content=message, task_type=task_type, order=0)],
            is_complex=False,
        )

    def _is_multi_step(self, message: str) -> bool:
        """检测消息是否包含多步骤指示词。"""
        for pattern in self._compiled_patterns:
            if pattern.search(message):
                return True
        return False

    def _split_into_subtasks(self, message: str, task_type: str) -> list[SubTask]:
        """尝试按分隔符拆分子任务。"""
        for sep_pattern in self._compiled_separators:
            parts = sep_pattern.split(message)
            if len(parts) > 1:
                subtasks = []
                for i, part in enumerate(parts):
                    part = part.strip()
                    if not part:
                        continue
                    subtasks.append(SubTask(
                        title=f"子任务{i + 1}",
                        content=part,
                        task_type=task_type,
                        order=i,
                    ))
                if len(subtasks) > 1:
                    return subtasks

        # 无法自动拆分，按行分割（简单降级）
        lines = [l.strip() for l in message.split("\n") if l.strip()]
        if len(lines) >= 3:
            return [
                SubTask(title=f"子任务{i+1}", content=line, task_type=task_type, order=i)
                for i, line in enumerate(lines)
            ]

        return [SubTask(title="主任务", content=message, task_type=task_type, order=0)]

    @property
    def decompose_count(self) -> int:
        return self._decompose_count

    def __repr__(self) -> str:
        return f"TaskDecomposer(decomposed={self._decompose_count})"

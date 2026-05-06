"""
ComplexityEstimator — 复杂度评估器
根据消息长度、关键词等评估任务复杂度，辅助路由决策
"""
from __future__ import annotations

import re
from enum import Enum
from typing import NamedTuple

from .intent_classifier import TaskType


class ComplexityLevel(str, Enum):
    TRIVIAL = "trivial"    # 极简单
    SIMPLE = "simple"      # 简单
    MEDIUM = "medium"      # 中等
    COMPLEX = "complex"    # 复杂
    EXTREME = "extreme"    # 极复杂


class ComplexityResult(NamedTuple):
    level: ComplexityLevel
    suggested_task_type: TaskType
    score: float           # 0.0~10.0
    reason: str


# 复杂度调整关键词
COMPLEXITY_UP_KEYWORDS = [
    "系统", "架构", "大规模", "分布式", "并发", "性能优化", "重构",
    "设计模式", "微服务", "算法", "数学推导", "证明", "复杂"
]
COMPLEXITY_DOWN_KEYWORDS = [
    "简单", "快速", "一行", "一下", "稍微", "简短", "小改动"
]

REASONING_KEYWORDS = ["分析", "推理", "论证", "为什么", "逻辑", "比较", "评估"]
ARCH_KEYWORDS = ["架构", "系统", "模块", "设计", "整体", "框架"]


class ComplexityEstimator:
    """
    复杂度评估器。
    规则：
      消息长度 < 20字  → code_small
      消息长度 20-100字 → code_medium
      消息长度 > 100字 或 包含"系统/架构" → code_large
      包含"分析/推理/复杂" → reasoning
      包含"简单/快速/一下" → reasoning_light
    """

    def estimate(self, message: str, base_task_type: TaskType | None = None) -> ComplexityResult:
        """
        评估消息复杂度。
        base_task_type: 已有的意图分类结果（可选），用于辅助判断。
        """
        msg_len = len(message.strip())
        score = self._calc_score(message, msg_len)
        level = self._score_to_level(score)
        suggested = self._suggest_task_type(message, msg_len, base_task_type, score)
        reason = self._build_reason(msg_len, score, message)

        return ComplexityResult(
            level=level,
            suggested_task_type=suggested,
            score=round(score, 2),
            reason=reason,
        )

    def _calc_score(self, message: str, msg_len: int) -> float:
        """计算复杂度分数（0-10）。"""
        score = 0.0

        # 基础：消息长度
        if msg_len < 20:
            score += 1.0
        elif msg_len < 50:
            score += 2.5
        elif msg_len < 100:
            score += 4.0
        elif msg_len < 200:
            score += 6.0
        else:
            score += 8.0

        # 关键词调整
        msg_lower = message.lower()
        for kw in COMPLEXITY_UP_KEYWORDS:
            if kw in msg_lower:
                score += 0.5

        for kw in COMPLEXITY_DOWN_KEYWORDS:
            if kw in msg_lower:
                score -= 0.8

        return max(0.0, min(10.0, score))

    def _score_to_level(self, score: float) -> ComplexityLevel:
        if score < 2.0:
            return ComplexityLevel.TRIVIAL
        elif score < 4.0:
            return ComplexityLevel.SIMPLE
        elif score < 6.0:
            return ComplexityLevel.MEDIUM
        elif score < 8.0:
            return ComplexityLevel.COMPLEX
        else:
            return ComplexityLevel.EXTREME

    def _suggest_task_type(
        self,
        message: str,
        msg_len: int,
        base_type: TaskType | None,
        score: float,
    ) -> TaskType:
        """根据复杂度推荐任务类型。"""
        msg_lower = message.lower()

        # 架构类词汇 → code_large
        if any(kw in msg_lower for kw in ARCH_KEYWORDS) and score >= 4:
            return TaskType.CODE_LARGE

        # 推理类词汇
        if any(kw in msg_lower for kw in REASONING_KEYWORDS):
            return TaskType.REASONING if score >= 5 else TaskType.REASONING_LIGHT

        # 代码类（基于长度）
        if base_type and "code" in base_type.value:
            if msg_len < 20:
                return TaskType.CODE_SMALL
            elif msg_len < 100:
                return TaskType.CODE_MEDIUM
            else:
                return TaskType.CODE_LARGE

        # 简单降级
        if any(kw in msg_lower for kw in COMPLEXITY_DOWN_KEYWORDS):
            if base_type in (TaskType.REASONING, TaskType.REASONING_LIGHT):
                return TaskType.REASONING_LIGHT

        return base_type or TaskType.CHAT

    def _build_reason(self, msg_len: int, score: float, message: str) -> str:
        parts = [f"消息长度:{msg_len}字, 复杂度分:{score:.1f}"]
        found_up = [kw for kw in COMPLEXITY_UP_KEYWORDS if kw in message]
        found_down = [kw for kw in COMPLEXITY_DOWN_KEYWORDS if kw in message]
        if found_up:
            parts.append(f"上调词:{','.join(found_up[:3])}")
        if found_down:
            parts.append(f"下调词:{','.join(found_down[:3])}")
        return " | ".join(parts)

    def __repr__(self) -> str:
        return "ComplexityEstimator()"

"""
Gatekeeper — 准入控制器
实现五档路由模式：日常40% / 中等40% / 深度15% / 大神4% / 真神1%
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import NamedTuple

from .intent_classifier import TaskType
from .query_complexity import ComplexityLevel


class RouteTier(str, Enum):
    """五档路由档位。"""
    DAILY   = "daily"    # 日常 40%
    MEDIUM  = "medium"   # 中等 40%
    DEEP    = "deep"     # 深度 15%
    MASTER  = "master"   # 大神 4%
    DIVINE  = "divine"   # 真神 1%


@dataclass
class TierConfig:
    tier: RouteTier
    ratio: float
    auto_execute: bool
    cost_threshold: float  # 美元
    model: str
    description: str


# 五档配置
TIER_CONFIGS: dict[RouteTier, TierConfig] = {
    RouteTier.DAILY:  TierConfig(RouteTier.DAILY,  0.40, True,  0.01, "mimo-v2.5",        "日常任务，自动执行"),
    RouteTier.MEDIUM: TierConfig(RouteTier.MEDIUM, 0.40, True,  0.05, "mimo-v2.5-pro",    "中等任务，自动执行"),
    RouteTier.DEEP:   TierConfig(RouteTier.DEEP,   0.15, False, 1.00, "claude-sonnet-4.6","深度任务，需确认"),
    RouteTier.MASTER: TierConfig(RouteTier.MASTER, 0.04, False, 5.00, "opus-4.7",         "大神任务，必须确认"),
    RouteTier.DIVINE: TierConfig(RouteTier.DIVINE, 0.01, False,10.00, "opus-4.7+gpt-5.5", "真神任务，必须确认"),
}

# 任务类型 → 默认档位映射
TASK_TIER_MAP: dict[TaskType, RouteTier] = {
    TaskType.CHAT:            RouteTier.DAILY,
    TaskType.CODE_SMALL:      RouteTier.DAILY,
    TaskType.CODE_MEDIUM:     RouteTier.MEDIUM,
    TaskType.CODE_LARGE:      RouteTier.DEEP,
    TaskType.REASONING_LIGHT: RouteTier.MEDIUM,
    TaskType.REASONING:       RouteTier.MASTER,
    TaskType.VISION:          RouteTier.MEDIUM,
    TaskType.SEARCH:          RouteTier.DAILY,
    TaskType.ROUTING:         RouteTier.DAILY,
    TaskType.SUBTASK:         RouteTier.DAILY,
}


class GatekeeperResult(NamedTuple):
    tier: RouteTier
    auto_execute: bool
    requires_confirmation: bool
    cost_threshold: float
    suggested_model: str
    message: str


class Gatekeeper:
    """
    准入控制器。
    根据任务类型和复杂度决定路由档位，判断是否需要用户确认。
    """

    def __init__(self, tier_configs: dict | None = None) -> None:
        self._tiers = TIER_CONFIGS.copy()
        if tier_configs:
            self._load_tier_configs(tier_configs)

    def _load_tier_configs(self, cfg: dict) -> None:
        """从配置文件加载档位参数。"""
        for tier_name, tier_data in cfg.items():
            try:
                tier = RouteTier(tier_name)
                if tier in self._tiers:
                    tc = self._tiers[tier]
                    if "cost_threshold" in tier_data:
                        tc.cost_threshold = tier_data["cost_threshold"]
                    if "auto_execute" in tier_data:
                        tc.auto_execute = tier_data["auto_execute"]
                    if "model" in tier_data:
                        tc.model = tier_data["model"]
            except ValueError:
                pass

    def check(
        self,
        task_type: TaskType,
        complexity_level: ComplexityLevel | None = None,
    ) -> GatekeeperResult:
        """
        根据任务类型（和可选的复杂度）判断路由档位。
        """
        tier = self._determine_tier(task_type, complexity_level)
        tc = self._tiers[tier]

        return GatekeeperResult(
            tier=tier,
            auto_execute=tc.auto_execute,
            requires_confirmation=not tc.auto_execute,
            cost_threshold=tc.cost_threshold,
            suggested_model=tc.model,
            message=tc.description,
        )

    def _determine_tier(
        self,
        task_type: TaskType,
        complexity_level: ComplexityLevel | None,
    ) -> RouteTier:
        """综合任务类型和复杂度确定档位。"""
        base_tier = TASK_TIER_MAP.get(task_type, RouteTier.DAILY)

        # 复杂度提升档位
        if complexity_level in (ComplexityLevel.EXTREME,):
            # 极复杂：至少提升到 MASTER
            if base_tier in (RouteTier.DAILY, RouteTier.MEDIUM, RouteTier.DEEP):
                return RouteTier.MASTER
        elif complexity_level == ComplexityLevel.COMPLEX:
            # 复杂：提升一档
            tier_order = [RouteTier.DAILY, RouteTier.MEDIUM, RouteTier.DEEP,
                          RouteTier.MASTER, RouteTier.DIVINE]
            idx = tier_order.index(base_tier)
            if idx < len(tier_order) - 1:
                return tier_order[idx + 1]

        return base_tier

    def is_auto_executable(self, task_type: TaskType) -> bool:
        """快速判断是否可以自动执行（无需确认）。"""
        tier = TASK_TIER_MAP.get(task_type, RouteTier.DAILY)
        return self._tiers[tier].auto_execute

    def get_tier_info(self, tier: RouteTier) -> TierConfig:
        return self._tiers[tier]

    def all_tiers(self) -> list[TierConfig]:
        return list(self._tiers.values())

    def __repr__(self) -> str:
        return f"Gatekeeper(tiers={len(self._tiers)})"

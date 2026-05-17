"""
Gatekeeper — 准入控制器
实现五档路由模式：nano 40% / low 40% / medium 15% / high 4% / xhigh 1%
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import NamedTuple

from .intent_classifier import TaskType
from .query_complexity import ComplexityLevel


class RouteTier(str, Enum):
    """五档路由档位。"""
    NANO    = "nano"     # 40%
    LOW     = "low"      # 40%
    MEDIUM  = "medium"   # 15%
    HIGH    = "high"     # 4%
    XHIGH   = "xhigh"    # 1%


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
    RouteTier.NANO:   TierConfig(RouteTier.NANO,   0.40, True,  0.01, "gemini-3-flash-preview",  "nano: auto"),
    RouteTier.LOW:    TierConfig(RouteTier.LOW,    0.40, True,  0.05, "gemini-3.1-pro-preview",    "low: auto"),
    RouteTier.MEDIUM: TierConfig(RouteTier.MEDIUM, 0.15, False, 1.00, "claude-sonnet-4.6","medium: confirm"),
    RouteTier.HIGH:   TierConfig(RouteTier.HIGH,   0.04, False, 5.00, "opus-4.7",         "high: confirm"),
    RouteTier.XHIGH:  TierConfig(RouteTier.XHIGH,  0.01, False,10.00, "opus-4.7+gpt-5.5", "xhigh: confirm"),
}

# 任务类型 → 默认档位映射
TASK_TIER_MAP: dict[TaskType, RouteTier] = {
    TaskType.CHAT:            RouteTier.NANO,
    TaskType.CODE_SMALL:      RouteTier.NANO,
    TaskType.CODE_MEDIUM:     RouteTier.LOW,
    TaskType.CODE_LARGE:      RouteTier.MEDIUM,
    TaskType.REASONING_LIGHT: RouteTier.LOW,
    TaskType.REASONING:       RouteTier.HIGH,
    TaskType.VISION:          RouteTier.LOW,
    TaskType.SEARCH:          RouteTier.LOW,
    TaskType.ROUTING:         RouteTier.NANO,
    TaskType.SUBTASK:         RouteTier.NANO,
    TaskType.AGENT_TASK:      RouteTier.XHIGH,  # 自动化 Agent → xhigh 辩论档
    TaskType.REPO_ANALYSIS:   RouteTier.HIGH,   # 长仓库分析 → high
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
        base_tier = TASK_TIER_MAP.get(task_type, RouteTier.NANO)

        tier_order = [RouteTier.NANO, RouteTier.LOW, RouteTier.MEDIUM,
                      RouteTier.HIGH, RouteTier.XHIGH]

        # 复杂度提升档位
        if complexity_level == ComplexityLevel.EXTREME:
            # 极复杂：至少提升到 XHIGH（确保 reasoning+EXTREME 能触发辩论）
            idx = tier_order.index(base_tier)
            target = max(idx, tier_order.index(RouteTier.HIGH))
            # EXTREME 比 COMPLEX 多提升一档
            target = min(target + 1, len(tier_order) - 1)
            return tier_order[target]
        elif complexity_level == ComplexityLevel.COMPLEX:
            # 复杂：提升一档
            idx = tier_order.index(base_tier)
            if idx < len(tier_order) - 1:
                return tier_order[idx + 1]

        return base_tier

    def is_auto_executable(self, task_type: TaskType) -> bool:
        """快速判断是否可以自动执行（无需确认）。"""
        tier = TASK_TIER_MAP.get(task_type, RouteTier.NANO)
        return self._tiers[tier].auto_execute

    def get_tier_info(self, tier: RouteTier) -> TierConfig:
        return self._tiers[tier]

    def all_tiers(self) -> list[TierConfig]:
        return list(self._tiers.values())

    def __repr__(self) -> str:
        return f"Gatekeeper(tiers={len(self._tiers)})"

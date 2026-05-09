"""
EvolutionEngine — 进化引擎
分析所有成功和失败案例，自动生成新规则，更新抗体库
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime

from .antibody import AntibodyLibrary

logger = logging.getLogger(__name__)


@dataclass
class EvolutionReport:
    """进化报告。"""
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())
    new_antibodies: int = 0
    optimized_antibodies: int = 0
    pruned_antibodies: int = 0
    overall_success_rate: float = 0.0
    recommendations: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "timestamp": self.timestamp,
            "new_antibodies": self.new_antibodies,
            "optimized_antibodies": self.optimized_antibodies,
            "pruned_antibodies": self.pruned_antibodies,
            "overall_success_rate": self.overall_success_rate,
            "recommendations": self.recommendations,
        }


class EvolutionEngine:
    """
    进化引擎。
    每次错误处理完成后收集数据，分析成功/失败案例，
    自动优化抗体库，输出进化报告。
    """

    def __init__(self, antibody_lib: AntibodyLibrary | None = None) -> None:
        self._lib = antibody_lib or AntibodyLibrary.get()
        self._case_history: list[dict] = []
        self._evolve_count = 0

    def collect(self, error_report: dict) -> None:
        """收集一次错误处理结果。"""
        self._case_history.append(error_report)

    def evolve(self) -> EvolutionReport:
        """
        分析历史案例，执行一次进化迭代。

        进化流程：
        1. 分析成功案例 → 优化高效抗体优先级
        2. 分析失败案例 → 识别需要新抗体的场景
        3. 淘汰低效抗体
        4. 生成进化报告
        """
        self._evolve_count += 1
        report = EvolutionReport()
        logger.info(f"[EvolutionEngine] 开始第{self._evolve_count}次进化 (案例数={len(self._case_history)})")

        if not self._case_history:
            return report

        # ── 分析成功案例 ─────────────────────────────────────────────────
        success_cases = [c for c in self._case_history if c.get("resolved")]
        fail_cases = [c for c in self._case_history if not c.get("resolved")]

        # 统计最常用且成功的抗体
        ab_success_counts: dict[str, int] = {}
        for case in success_cases:
            ab = case.get("antibody", "")
            if ab and ab != "none":
                ab_success_counts[ab] = ab_success_counts.get(ab, 0) + 1

        # 优化高成功率抗体（提升优先级）
        for ab_name, count in ab_success_counts.items():
            if count >= 3:
                antibody = next(
                    (a for a in self._lib.all_antibodies() if a.name == ab_name), None
                )
                if antibody and antibody.priority < 10:
                    antibody.priority = min(antibody.priority + 1, 10)
                    report.optimized_antibodies += 1
                    report.recommendations.append(
                        f"优化抗体 [{ab_name}] 优先级 → {antibody.priority}"
                    )

        # ── 分析失败案例，生成新抗体 ──────────────────────────────────────
        unhandled_categories: dict[str, int] = {}
        for case in fail_cases:
            cat = case.get("category", "unknown")
            if case.get("antibody") in ("generic-catch", "none"):
                unhandled_categories[cat] = unhandled_categories.get(cat, 0) + 1

        for cat, count in unhandled_categories.items():
            if count >= 2:
                # 为该类别生成通用新抗体
                new_ab = self._lib.generate_new_antibody(
                    error_pattern=cat,
                    action=f"自动生成：处理{cat}类型错误",
                    fix_steps=[
                        f"识别{cat}类型错误",
                        "记录错误详情",
                        "尝试降级模型",
                        "等待后重试",
                    ],
                )
                report.new_antibodies += 1
                report.recommendations.append(f"新增抗体: {new_ab.name} (类别={cat})")

        # ── 淘汰低效抗体 ──────────────────────────────────────────────────
        pruned = self._lib.remove_poor_antibodies(min_success_rate=0.2)
        report.pruned_antibodies = pruned

        # ── 整体成功率 ────────────────────────────────────────────────────
        total = len(self._case_history)
        report.overall_success_rate = round(len(success_cases) / total, 3) if total > 0 else 0.0

        logger.info(
            f"[EvolutionEngine] 进化完成: 新增{report.new_antibodies}, "
            f"优化{report.optimized_antibodies}, 淘汰{report.pruned_antibodies}, "
            f"成功率={report.overall_success_rate:.1%}"
        )

        # 清空本次已分析的案例
        self._case_history.clear()
        return report

    def full_report(self) -> dict:
        return {
            "evolve_count": self._evolve_count,
            "pending_cases": len(self._case_history),
            "antibody_stats": self._lib.stats(),
        }

    def __repr__(self) -> str:
        return f"EvolutionEngine(evolve_count={self._evolve_count})"

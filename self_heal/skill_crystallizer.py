"""
SkillCrystallizer — 技能结晶器
将重复使用的解决方案自动结晶为可复用技能
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class CrystallizedSkill:
    """结晶化的技能。"""
    skill_id: str
    trigger_pattern: str   # 触发模式
    solution: str          # 解决方案
    usage_count: int = 1
    category: str = "auto"

    def to_dict(self) -> dict:
        return {
            "skill_id": self.skill_id,
            "trigger_pattern": self.trigger_pattern,
            "solution": self.solution,
            "usage_count": self.usage_count,
            "category": self.category,
        }


class SkillCrystallizer:
    """
    技能结晶器。
    监控重复出现的问题-解决方案对，
    当同一模式出现3次以上时，自动结晶为持久化技能。
    """

    CRYSTALLIZE_THRESHOLD = 3

    def __init__(self) -> None:
        self._pattern_counter: dict[str, int] = {}
        self._solution_map: dict[str, str] = {}
        self._crystallized: dict[str, CrystallizedSkill] = {}

    def observe(self, pattern: str, solution: str) -> CrystallizedSkill | None:
        """
        观察一个问题-解决方案对。
        若同一模式出现≥CRYSTALLIZE_THRESHOLD次，则结晶为技能。
        """
        key = pattern.strip().lower()[:50]
        self._pattern_counter[key] = self._pattern_counter.get(key, 0) + 1
        self._solution_map[key] = solution

        if (key not in self._crystallized
                and self._pattern_counter[key] >= self.CRYSTALLIZE_THRESHOLD):
            return self._crystallize(key, pattern, solution)
        return None

    def _crystallize(self, key: str, pattern: str, solution: str) -> CrystallizedSkill:
        """将模式结晶为技能。"""
        import uuid
        skill_id = f"crystal_{uuid.uuid4().hex[:6]}"
        skill = CrystallizedSkill(
            skill_id=skill_id,
            trigger_pattern=pattern[:100],
            solution=solution,
            usage_count=self._pattern_counter[key],
        )
        self._crystallized[key] = skill
        logger.info(f"[SkillCrystallizer] 技能结晶: {skill_id} (pattern={pattern[:30]})")
        return skill

    def get_crystallized_skills(self) -> list[CrystallizedSkill]:
        return list(self._crystallized.values())

    def stats(self) -> dict:
        return {
            "observed_patterns": len(self._pattern_counter),
            "crystallized_skills": len(self._crystallized),
        }

    def __repr__(self) -> str:
        return f"SkillCrystallizer(crystallized={len(self._crystallized)})"

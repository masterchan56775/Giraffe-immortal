"""
SkillReviewer — 技能审稿模块
负责技能的评分、查重（Jaccard相似度）、截断（30天未用+低分清理）和报告
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from datetime import datetime

logger = logging.getLogger(__name__)

# 评分权重常量
BASE_SCORE = 50
MAX_CONTENT_SCORE = 40
MAX_USAGE_SCORE = 20
MAX_TOTAL_SCORE = BASE_SCORE + MAX_CONTENT_SCORE + MAX_USAGE_SCORE  # 110

JACCARD_SIMILARITY_THRESHOLD = 0.7   # 超过此值视为重复技能
STALE_DAYS = 30                       # 未使用多少天算过期
STALE_SCORE_THRESHOLD = 65            # 过期技能低于此分数时截断（base=50，无内容/使用分的技能总分≤50+极小值）



@dataclass
class SkillScore:
    """技能评分结果。"""
    skill_id: str
    name: str
    base_score: float = BASE_SCORE
    content_score: float = 0.0
    usage_score: float = 0.0

    @property
    def total(self) -> float:
        return self.base_score + self.content_score + self.usage_score

    def to_dict(self) -> dict:
        return {
            "skill_id": self.skill_id,
            "name": self.name,
            "base_score": self.base_score,
            "content_score": self.content_score,
            "usage_score": self.usage_score,
            "total": round(self.total, 2),
        }


@dataclass
class Skill:
    """技能数据对象。"""
    skill_id: str
    name: str
    content: str
    category: str = "general"
    usage_count: int = 0
    created_at: datetime = field(default_factory=datetime.now)
    last_used_at: datetime = field(default_factory=datetime.now)
    metadata: dict = field(default_factory=dict)

    def use(self) -> None:
        self.usage_count += 1
        self.last_used_at = datetime.now()

    @property
    def days_since_used(self) -> int:
        return (datetime.now() - self.last_used_at).days

    def to_dict(self) -> dict:
        return {
            "skill_id": self.skill_id,
            "name": self.name,
            "content": self.content,
            "category": self.category,
            "usage_count": self.usage_count,
            "created_at": self.created_at.isoformat(),
            "last_used_at": self.last_used_at.isoformat(),
        }


class SkillReviewer:
    """
    技能审稿器。
    - 评分算法：基础分50 + 内容质量(40) + 使用次数(20) = 最高110分
    - 查重：Jaccard相似度检测
    - 截断：30天未用 + 评分<30 → 自动清理
    - 报告：总技能数/平均分/重复组/死技能数
    """

    def __init__(self, skills_path: Path | str | None = None) -> None:
        self._path = Path(skills_path) if skills_path else None
        self._skills: dict[str, Skill] = {}

    # ─── 技能管理 ─────────────────────────────────────────────────────────────
    def add_skill(self, skill: Skill) -> None:
        self._skills[skill.skill_id] = skill

    def remove_skill(self, skill_id: str) -> bool:
        return bool(self._skills.pop(skill_id, None))

    def get_skill(self, skill_id: str) -> Skill | None:
        return self._skills.get(skill_id)

    def all_skills(self) -> list[Skill]:
        return list(self._skills.values())

    # ─── 评分 ────────────────────────────────────────────────────────────────
    def score_skill(self, skill: Skill) -> SkillScore:
        """对单个技能打分（最高110分）。"""
        ss = SkillScore(skill_id=skill.skill_id, name=skill.name)

        # 内容质量得分（0-40）
        content_len = len(skill.content)
        has_examples = "例" in skill.content or "example" in skill.content.lower()
        has_steps = bool(re.search(r"\d+[.、]", skill.content))
        content_score = min(content_len / 100 * 20, 20)       # 长度得分（最多20）
        content_score += 10 if has_examples else 0              # 示例得分
        content_score += 10 if has_steps else 0                 # 步骤得分
        ss.content_score = min(content_score, MAX_CONTENT_SCORE)

        # 使用频次得分（0-20）
        usage_score = min(skill.usage_count * 2, MAX_USAGE_SCORE)
        ss.usage_score = usage_score

        return ss

    def score_all(self) -> list[SkillScore]:
        """对所有技能打分，按总分降序排列。"""
        scores = [self.score_skill(s) for s in self._skills.values()]
        return sorted(scores, key=lambda x: x.total, reverse=True)

    # ─── 查重（Jaccard相似度）────────────────────────────────────────────────
    def _tokenize(self, text: str) -> set[str]:
        """简单分词：按词拆分。"""
        return set(re.findall(r"\w+", text.lower()))

    def _jaccard(self, a: set, b: set) -> float:
        if not a or not b:
            return 0.0
        return len(a & b) / len(a | b)

    def find_duplicates(self) -> list[list[str]]:
        """返回重复技能组（每组内技能相似度超过阈值）。"""
        skills = list(self._skills.values())
        tokenized = [(s.skill_id, self._tokenize(s.content)) for s in skills]
        groups: list[list[str]] = []
        visited: set[str] = set()

        for i, (id_a, tokens_a) in enumerate(tokenized):
            if id_a in visited:
                continue
            group = [id_a]
            for id_b, tokens_b in tokenized[i + 1:]:
                if id_b in visited:
                    continue
                if self._jaccard(tokens_a, tokens_b) >= JACCARD_SIMILARITY_THRESHOLD:
                    group.append(id_b)
                    visited.add(id_b)
            if len(group) > 1:
                groups.append(group)
                visited.add(id_a)
        return groups

    # ─── 截断（Dead Skill Cleanup）───────────────────────────────────────────
    def find_stale_skills(self) -> list[Skill]:
        """找出应该被截断的死技能：30天未用 + 评分<30。"""
        dead = []
        for skill in self._skills.values():
            if skill.days_since_used >= STALE_DAYS:
                score = self.score_skill(skill)
                if score.total < STALE_SCORE_THRESHOLD:
                    dead.append(skill)
        return dead

    def prune_stale_skills(self) -> int:
        """自动清理死技能，返回清理数量。"""
        stale = self.find_stale_skills()
        for skill in stale:
            logger.info(f"[SkillReviewer] 清理死技能: {skill.skill_id} ({skill.name})")
            self.remove_skill(skill.skill_id)
        return len(stale)

    # ─── 报告 ────────────────────────────────────────────────────────────────
    def generate_report(self) -> dict:
        """生成技能审稿报告。"""
        all_scores = self.score_all()
        avg_score = sum(s.total for s in all_scores) / len(all_scores) if all_scores else 0
        duplicates = self.find_duplicates()
        stale = self.find_stale_skills()

        return {
            "total_skills": len(self._skills),
            "average_score": round(avg_score, 2),
            "max_score": round(all_scores[0].total, 2) if all_scores else 0,
            "min_score": round(all_scores[-1].total, 2) if all_scores else 0,
            "duplicate_groups": len(duplicates),
            "duplicate_skill_ids": duplicates,
            "stale_skill_count": len(stale),
            "stale_skill_ids": [s.skill_id for s in stale],
            "top_skills": [s.to_dict() for s in all_scores[:5]],
        }

    def __repr__(self) -> str:
        return f"SkillReviewer(skills={len(self._skills)})"

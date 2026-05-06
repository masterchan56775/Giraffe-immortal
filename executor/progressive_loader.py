"""
ProgressiveSkillLoader — 渐进式技能加载器
技能缓存 + 使用频率追踪 + 优先级自动提升 + 过期清理
"""
from __future__ import annotations

import json
import logging
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

DEFAULT_CACHE_DURATION = 86400     # 1天（秒）
DEFAULT_CLEANUP_INTERVAL = 2592000  # 30天（秒）
DEFAULT_PRIORITY_BOOST_THRESHOLD = 5


@dataclass
class CachedSkill:
    """缓存的技能记录。"""
    skill_id: str
    name: str
    content: Any
    category: str = "general"
    priority: int = 5
    usage_count: int = 0
    cached_at: float = field(default_factory=time.time)
    last_used: float = field(default_factory=time.time)
    expires_at: float = field(default_factory=lambda: time.time() + DEFAULT_CACHE_DURATION)

    def use(self) -> None:
        self.usage_count += 1
        self.last_used = time.time()

    def is_expired(self) -> bool:
        return time.time() > self.expires_at

    def is_stale(self, stale_threshold: float = DEFAULT_CLEANUP_INTERVAL) -> bool:
        return (time.time() - self.last_used) > stale_threshold

    def to_dict(self) -> dict:
        d = asdict(self)
        d["content"] = str(d["content"])  # 序列化时转字符串
        return d


class ProgressiveSkillLoader:
    """
    渐进式技能加载器（单例）。
    - 技能缓存（JSON持久化）
    - 使用频率追踪 + 优先级自动提升（使用次数 ≥ boost_threshold 时提升）
    - 过期清理（30天未使用自动清除）
    - 统计报告
    """

    def __init__(
        self,
        cache_path: Path | str | None = None,
        priority_boost_threshold: int = DEFAULT_PRIORITY_BOOST_THRESHOLD,
        cache_duration: float = DEFAULT_CACHE_DURATION,
        cleanup_interval: float = DEFAULT_CLEANUP_INTERVAL,
    ) -> None:
        self._cache_path = Path(cache_path) if cache_path else None
        self._boost_threshold = priority_boost_threshold
        self._cache_duration = cache_duration
        self._cleanup_interval = cleanup_interval
        self._skills: dict[str, CachedSkill] = {}
        self._load_from_disk()

    # ─── 技能管理 ─────────────────────────────────────────────────────────────
    def register(self, skill_id: str, name: str, content: Any,
                 category: str = "general", priority: int = 5) -> CachedSkill:
        """注册技能到缓存。"""
        skill = CachedSkill(
            skill_id=skill_id,
            name=name,
            content=content,
            category=category,
            priority=priority,
            expires_at=time.time() + self._cache_duration,
        )
        self._skills[skill_id] = skill
        return skill

    def get(self, skill_id: str) -> CachedSkill | None:
        """获取技能（记录使用频率）。"""
        skill = self._skills.get(skill_id)
        if skill is None or skill.is_expired():
            return None
        skill.use()
        self._maybe_boost_priority(skill)
        return skill

    def _maybe_boost_priority(self, skill: CachedSkill) -> None:
        """使用次数达到阈值时自动提升优先级。"""
        if skill.usage_count >= self._boost_threshold and skill.priority < 10:
            skill.priority = min(skill.priority + 1, 10)
            logger.debug(f"[ProgressiveLoader] 优先级提升: {skill.skill_id} → P{skill.priority}")

    def cleanup(self) -> int:
        """清理过期和闲置技能，返回清理数量。"""
        stale_ids = [
            sid for sid, s in self._skills.items()
            if s.is_expired() or s.is_stale(self._cleanup_interval)
        ]
        for sid in stale_ids:
            del self._skills[sid]
        if stale_ids:
            logger.info(f"[ProgressiveLoader] 清理了 {len(stale_ids)} 个过期技能")
        return len(stale_ids)

    def top_skills(self, n: int = 10) -> list[CachedSkill]:
        """按使用频率降序返回热门技能。"""
        return sorted(
            self._skills.values(),
            key=lambda s: (s.priority, s.usage_count),
            reverse=True,
        )[:n]

    # ─── 持久化 ───────────────────────────────────────────────────────────────
    def save_to_disk(self) -> None:
        if not self._cache_path:
            return
        self._cache_path.parent.mkdir(parents=True, exist_ok=True)
        data = {sid: s.to_dict() for sid, s in self._skills.items()}
        with open(self._cache_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def _load_from_disk(self) -> None:
        if not self._cache_path or not self._cache_path.exists():
            return
        try:
            with open(self._cache_path, encoding="utf-8") as f:
                data = json.load(f)
            for sid, item in data.items():
                skill = CachedSkill(**item)
                if not skill.is_expired():
                    self._skills[sid] = skill
            logger.info(f"[ProgressiveLoader] 从磁盘加载 {len(self._skills)} 个技能")
        except Exception as e:
            logger.warning(f"[ProgressiveLoader] 加载失败: {e}")

    def stats(self) -> dict:
        return {
            "cached_skills": len(self._skills),
            "top_5": [{"id": s.skill_id, "usage": s.usage_count} for s in self.top_skills(5)],
        }

    def __repr__(self) -> str:
        return f"ProgressiveSkillLoader(cached={len(self._skills)})"

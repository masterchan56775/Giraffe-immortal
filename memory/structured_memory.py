"""
StructuredMemory — 结构化记忆
三层结构：UserContext / HistoryContext / Facts
"""
from __future__ import annotations

import json
import logging
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class UserContext:
    """用户画像上下文。"""
    work_context: str = ""        # 工作背景（如"我是前端开发"）
    personal_context: str = ""    # 个人偏好（如"我喜欢简洁代码"）
    top_of_mind: str = ""         # 当前关注（如"我正在做登录模块"）
    updated_at: str = field(default_factory=lambda: datetime.now().isoformat())

    def update(self, **kwargs) -> None:
        for k, v in kwargs.items():
            if hasattr(self, k):
                setattr(self, k, v)
        self.updated_at = datetime.now().isoformat()

    def to_prompt(self) -> str:
        parts = []
        if self.work_context:
            parts.append(f"工作背景: {self.work_context}")
        if self.personal_context:
            parts.append(f"个人偏好: {self.personal_context}")
        if self.top_of_mind:
            parts.append(f"当前关注: {self.top_of_mind}")
        return "\n".join(parts)


@dataclass
class HistoryContext:
    """历史背景上下文。"""
    recent_months: str = ""       # 近几个月重要事件
    earlier_context: str = ""     # 更早期上下文
    long_term_background: str = "" # 长期背景

    def to_prompt(self) -> str:
        parts = []
        if self.long_term_background:
            parts.append(f"长期背景: {self.long_term_background}")
        if self.earlier_context:
            parts.append(f"早期上下文: {self.earlier_context}")
        if self.recent_months:
            parts.append(f"近期事件: {self.recent_months}")
        return "\n".join(parts)


@dataclass
class MemoryFact:
    """单条事实记录。"""
    id: str = field(default_factory=lambda: f"fact_{uuid.uuid4().hex[:8]}")
    content: str = ""
    category: str = "general"    # tech_stack / preference / project / other
    confidence: float = 0.8
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now().isoformat())
    source: str = "auto"          # auto / manual

    def to_dict(self) -> dict:
        return asdict(self)


class StructuredMemory:
    """
    结构化记忆系统。
    三层结构：UserContext / HistoryContext / Facts
    支持JSON持久化和系统提示词生成。
    """

    def __init__(self, persist_path: Path | str | None = None) -> None:
        self._path = Path(persist_path) if persist_path else None
        self.user_context = UserContext()
        self.history_context = HistoryContext()
        self._facts: dict[str, MemoryFact] = {}
        self._load()

    # ─── 事实管理 ─────────────────────────────────────────────────────────────
    def add_fact(self, content: str, category: str = "general",
                 confidence: float = 0.8, source: str = "auto") -> MemoryFact:
        """添加一条事实。"""
        fact = MemoryFact(content=content, category=category,
                          confidence=confidence, source=source)
        self._facts[fact.id] = fact
        logger.debug(f"[StructuredMemory] 添加事实: {content[:50]}")
        self._save()
        return fact

    def update_fact(self, fact_id: str, content: str | None = None,
                    confidence: float | None = None) -> bool:
        fact = self._facts.get(fact_id)
        if not fact:
            return False
        if content is not None:
            fact.content = content
        if confidence is not None:
            fact.confidence = confidence
        fact.updated_at = datetime.now().isoformat()
        self._save()
        return True

    def remove_fact(self, fact_id: str) -> bool:
        if fact_id in self._facts:
            del self._facts[fact_id]
            self._save()
            return True
        return False

    def get_facts(
        self,
        category: str | None = None,
        min_confidence: float = 0.0,
    ) -> list[MemoryFact]:
        """按分类和最低置信度过滤事实。"""
        facts = list(self._facts.values())
        if category:
            facts = [f for f in facts if f.category == category]
        facts = [f for f in facts if f.confidence >= min_confidence]
        return sorted(facts, key=lambda f: f.confidence, reverse=True)

    # ─── 上下文更新 ───────────────────────────────────────────────────────────
    def update_user_context(self, **kwargs) -> None:
        """更新用户画像。"""
        self.user_context.update(**kwargs)
        self._save()

    def update_history_context(self, **kwargs) -> None:
        """更新历史背景。"""
        for k, v in kwargs.items():
            if hasattr(self.history_context, k):
                setattr(self.history_context, k, v)
        self._save()

    # ─── 提示词生成 ───────────────────────────────────────────────────────────
    def generate_system_prompt(self, min_confidence: float = 0.7) -> str:
        """生成注入到AI上下文的系统提示词。"""
        parts = ["## 关于用户的记忆"]

        user_prompt = self.user_context.to_prompt()
        if user_prompt:
            parts.append("### 用户画像")
            parts.append(user_prompt)

        history_prompt = self.history_context.to_prompt()
        if history_prompt:
            parts.append("### 历史背景")
            parts.append(history_prompt)

        facts = self.get_facts(min_confidence=min_confidence)
        if facts:
            parts.append("### 已知事实")
            for f in facts[:20]:  # 最多注入20条
                parts.append(f"- [{f.category}] {f.content} (置信度:{f.confidence:.0%})")

        return "\n".join(parts) if len(parts) > 1 else ""

    # ─── 统计 ─────────────────────────────────────────────────────────────────
    def stats(self) -> dict:
        categories: dict[str, int] = {}
        for f in self._facts.values():
            categories[f.category] = categories.get(f.category, 0) + 1
        return {
            "total_facts": len(self._facts),
            "categories": categories,
            "avg_confidence": round(
                sum(f.confidence for f in self._facts.values()) / len(self._facts), 3
            ) if self._facts else 0.0,
        }

    # ─── 持久化 ───────────────────────────────────────────────────────────────
    def _save(self) -> None:
        if not self._path:
            return
        self._path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "user_context": asdict(self.user_context),
            "history_context": asdict(self.history_context),
            "facts": {fid: f.to_dict() for fid, f in self._facts.items()},
        }
        with open(self._path, "w", encoding="utf-8") as fp:
            json.dump(data, fp, ensure_ascii=False, indent=2)

    def _load(self) -> None:
        if not self._path or not self._path.exists():
            return
        try:
            with open(self._path, encoding="utf-8") as fp:
                data = json.load(fp)
            self.user_context = UserContext(**data.get("user_context", {}))
            self.history_context = HistoryContext(**data.get("history_context", {}))
            for fid, fdata in data.get("facts", {}).items():
                self._facts[fid] = MemoryFact(**fdata)
            logger.info(f"[StructuredMemory] 加载 {len(self._facts)} 条事实")
        except Exception as e:
            logger.warning(f"[StructuredMemory] 加载失败: {e}")

    def __repr__(self) -> str:
        return f"StructuredMemory(facts={len(self._facts)})"

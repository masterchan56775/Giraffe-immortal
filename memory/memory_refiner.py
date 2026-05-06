"""
MemoryRefiner — 记忆精炼器
对累积的事实进行去重、合并、质量提升
"""
from __future__ import annotations

import logging
from .structured_memory import StructuredMemory, MemoryFact

logger = logging.getLogger(__name__)


class MemoryRefiner:
    """
    记忆精炼器。
    - refine(StructuredMemory) → 对结构化记忆去重，返回报告 dict
    - refine(list[str])        → 对字符串列表去重，返回精炼后列表
    """

    def __init__(self, memory: StructuredMemory | None = None) -> None:
        self._memory = memory
        self._total_refined = 0

    def refine(self, target=None):
        """
        精炼记忆。
        - target 为 list[str]        → 返回去重后的 list[str]
        - target 为 StructuredMemory → 返回精炼报告 dict
        - target 为 None             → 使用构造时传入的 memory
        """
        if isinstance(target, list):
            return self._refine_list(target)

        mem = target or self._memory
        if not mem:
            return {"error": "未提供记忆对象"}

        facts = mem.get_facts()
        deduped = self._deduplicate(facts)
        removed = len(facts) - len(deduped)

        all_ids = {f.id for f in facts}
        kept_ids = {f.id for f in deduped}
        for fid in all_ids - kept_ids:
            mem.remove_fact(fid)

        self._total_refined += removed
        return {
            "original_count": len(facts),
            "after_refine": len(deduped),
            "removed": removed,
        }

    def _refine_list(self, contents: list[str]) -> list[str]:
        """对字符串列表去重（保序，忽略大小写和首尾空格）。"""
        seen: set[str] = set()
        result: list[str] = []
        for c in contents:
            key = c.strip().lower()[:80]
            if key and key not in seen:
                seen.add(key)
                result.append(c)
        removed = len(contents) - len(result)
        if removed > 0:
            self._total_refined += removed
        return result

    def _deduplicate(self, facts: list[MemoryFact]) -> list[MemoryFact]:
        """相同内容保留置信度最高的那条。"""
        seen: dict[str, MemoryFact] = {}
        for fact in facts:
            key = fact.content.strip().lower()[:50]
            if key not in seen or fact.confidence > seen[key].confidence:
                seen[key] = fact
        return list(seen.values())

    def stats(self) -> dict:
        return {"total_refined": self._total_refined}

    def __repr__(self) -> str:
        return f"MemoryRefiner(total_refined={self._total_refined})"

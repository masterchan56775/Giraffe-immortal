"""
AutoExtract — 自动事实提取
从对话中自动提取用户信息和偏好，写入记忆系统
"""
from __future__ import annotations

import logging
import re
from typing import NamedTuple

logger = logging.getLogger(__name__)


class ExtractedFact(NamedTuple):
    content: str
    category: str
    confidence: float


# 提取规则：(正则, 分类, 置信度)
EXTRACT_RULES: list[tuple[re.Pattern, str, float]] = [
    (re.compile(r"我(?:是|做|从事|在做)(.{2,20})", re.I), "work_context", 0.85),
    (re.compile(r"我(?:用|使用|喜欢用|正在用)([A-Za-z\u4e00-\u9fff]{2,20})", re.I), "tech_stack", 0.80),
    (re.compile(r"我(?:正在做|在开发|在写)(.{2,30})", re.I), "project", 0.75),
    (re.compile(r"我(?:喜欢|偏好|希望)(.{2,30})", re.I), "preference", 0.70),
    (re.compile(r"我(?:的电脑|用的系统|在)([A-Za-z\u4e00-\u9fff]{2,10})(上|系统)", re.I), "env", 0.80),
    (re.compile(r"(?:我的)?(.{2,20})项目", re.I), "project", 0.65),
]


class AutoExtract:
    """
    自动事实提取器。
    对每条用户消息运行规则匹配，提取关键事实。
    """

    def __init__(self, confidence_threshold: float = 0.7) -> None:
        self._threshold = confidence_threshold
        self._extract_count = 0

    def extract(self, message: str, role: str = "user") -> list[ExtractedFact]:
        """
        从消息中提取事实。
        仅对 role=user 的消息提取。
        """
        if role != "user":
            return []

        facts = []
        for pattern, category, confidence in EXTRACT_RULES:
            for match in pattern.finditer(message):
                content = match.group(1).strip() if match.lastindex else match.group(0).strip()
                if content and confidence >= self._threshold:
                    facts.append(ExtractedFact(
                        content=content,
                        category=category,
                        confidence=confidence,
                    ))
                    self._extract_count += 1

        # 去重（按内容）
        seen: set[str] = set()
        unique_facts = []
        for f in facts:
            if f.content not in seen:
                seen.add(f.content)
                unique_facts.append(f)

        if unique_facts:
            logger.debug(f"[AutoExtract] 提取到 {len(unique_facts)} 条事实")
        return unique_facts

    def extract_from_conversation(
        self, messages: list[dict]
    ) -> list[ExtractedFact]:
        """从完整对话历史中提取事实。"""
        all_facts = []
        for msg in messages:
            role = msg.get("role", "")
            content = msg.get("content", "")
            if isinstance(content, str):
                facts = self.extract(content, role)
                all_facts.extend(facts)
        return all_facts

    @property
    def extract_count(self) -> int:
        return self._extract_count

    def __repr__(self) -> str:
        return f"AutoExtract(threshold={self._threshold}, extracted={self._extract_count})"

"""
MicroCompact — 微压缩
消息超过500字符时自动摘要，节省token
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

DEFAULT_THRESHOLD = 500   # 字符数阈值


class MicroCompact:
    """
    微压缩器。
    单条消息超过 threshold 字符时，截断并附加摘要标记。
    适用于单次消息的轻量压缩。
    """

    def __init__(self, threshold: int = DEFAULT_THRESHOLD) -> None:
        self._threshold = threshold
        self._compact_count = 0

    def compact(self, messages: list[dict]) -> list[dict]:
        """
        对消息列表进行微压缩。
        仅压缩 role=user/assistant 的 content 过长消息。
        system消息不压缩。

        Args:
            messages: OpenAI格式的消息列表
        Returns:
            压缩后的消息列表（保留原结构，仅缩短内容）
        """
        result = []
        for msg in messages:
            role = msg.get("role", "")
            content = msg.get("content", "")

            if role != "system" and isinstance(content, str) and len(content) > self._threshold:
                compacted_content = self._truncate_with_summary(content)
                result.append({**msg, "content": compacted_content})
                self._compact_count += 1
                logger.debug(
                    f"[MicroCompact] 压缩消息: {len(content)}字 → "
                    f"{len(compacted_content)}字"
                )
            else:
                result.append(msg)
        return result

    def compact_single(self, content: str) -> str:
        """压缩单条消息内容。"""
        if len(content) <= self._threshold:
            return content
        self._compact_count += 1
        return self._truncate_with_summary(content)

    def _truncate_with_summary(self, content: str) -> str:
        """
        截断策略：保留前1/3和后1/6，中间用摘要标记替换。
        """
        keep_head = self._threshold // 3
        keep_tail = self._threshold // 6
        head = content[:keep_head]
        tail = content[-keep_tail:] if keep_tail > 0 else ""
        omitted = len(content) - keep_head - keep_tail
        return (
            f"{head}\n"
            f"[...已压缩{omitted}字符...]\n"
            f"{tail}"
        )

    def needs_compact(self, messages: list[dict]) -> bool:
        """判断消息列表是否需要压缩。"""
        return any(
            msg.get("role") != "system" and len(msg.get("content", "")) > self._threshold
            for msg in messages
        )

    @property
    def compact_count(self) -> int:
        return self._compact_count

    def stats(self) -> dict:
        return {
            "threshold": self._threshold,
            "compact_count": self._compact_count,
        }

    def __repr__(self) -> str:
        return f"MicroCompact(threshold={self._threshold})"

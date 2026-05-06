"""
DeepCompact — 深度压缩
对话超过20条时压缩历史，防止上下文溢出
"""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

DEFAULT_DEEP_THRESHOLD = 20   # 对话条数阈值
KEEP_RECENT = 6               # 压缩后保留最近N条（不压缩）
KEEP_SYSTEM = True            # 始终保留system消息


class DeepCompact:
    """
    深度压缩器（滑动窗口策略）。
    当对话历史超过 threshold 条时，将中间段压缩为摘要。
    策略：保留 system消息 + 前2条 + 最近 keep_recent 条，中间压缩。
    """

    def __init__(
        self,
        threshold: int = DEFAULT_DEEP_THRESHOLD,
        keep_recent: int = KEEP_RECENT,
    ) -> None:
        self._threshold = threshold
        self._keep_recent = keep_recent
        self._compact_count = 0

    def check_and_compact(self, messages: list[dict]) -> list[dict]:
        """
        检查并压缩对话历史。
        若不超过阈值则直接返回原列表。
        """
        if not self.needs_compact(messages):
            return messages

        self._compact_count += 1
        logger.info(
            f"[DeepCompact] 触发深度压缩: {len(messages)}条对话 → 压缩"
        )
        return self._sliding_window_compact(messages)

    def _sliding_window_compact(self, messages: list[dict]) -> list[dict]:
        """
        滑动窗口压缩。
        结构：[system消息] + [摘要消息] + [最近N条]
        """
        system_msgs = [m for m in messages if m.get("role") == "system"]
        non_system = [m for m in messages if m.get("role") != "system"]

        if len(non_system) <= self._keep_recent:
            return messages

        # 需要压缩的部分
        to_compact = non_system[:-self._keep_recent]
        recent = non_system[-self._keep_recent:]

        summary_content = self._summarize(to_compact)
        summary_msg = {
            "role": "system",
            "content": f"[历史摘要 - 已压缩{len(to_compact)}条对话]\n{summary_content}",
        }

        result = system_msgs + [summary_msg] + recent
        logger.debug(
            f"[DeepCompact] 压缩结果: {len(messages)}条 → {len(result)}条"
        )
        return result

    def _summarize(self, messages: list[dict]) -> str:
        """
        简单摘要策略：提取每条消息的前50字。
        生产环境可替换为LLM摘要调用。
        """
        lines = []
        for msg in messages:
            role = msg.get("role", "unknown")
            content = str(msg.get("content", ""))[:50]
            lines.append(f"[{role}]: {content}...")
        return "\n".join(lines)

    def needs_compact(self, messages: list[dict]) -> bool:
        """判断是否需要深度压缩。"""
        non_system = [m for m in messages if m.get("role") != "system"]
        return len(non_system) > self._threshold

    @property
    def compact_count(self) -> int:
        return self._compact_count

    def stats(self) -> dict:
        return {
            "threshold": self._threshold,
            "keep_recent": self._keep_recent,
            "compact_count": self._compact_count,
        }

    def __repr__(self) -> str:
        return f"DeepCompact(threshold={self._threshold})"

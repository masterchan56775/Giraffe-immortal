"""
工具结果持久化 — 
大结果写磁盘，上下文中保留 <persisted-output> 引用，防止 context 溢出。
"""
from __future__ import annotations

import hashlib
import logging
import os
import time
from pathlib import Path

logger = logging.getLogger("tool_result_store")

PERSISTED_TAG = "<persisted-output>"
PERSISTED_CLOSE = "</persisted-output>"
TOOL_RESULT_CLEARED = "[Old tool result content cleared]"

# 每个工具的默认大小阈值（字符数），超过则写磁盘
_DEFAULT_THRESHOLD = 50_000

_TOOL_THRESHOLDS: dict[str, int] = {
    "bash":        50_000,
    "read_file":   30_000,
    "grep":        40_000,
    "glob":        20_000,
    "web_fetch":   30_000,
    "todo_read":   float("inf"),   # 永不持久化
    "todo_write":  float("inf"),
}

# 会话存储根目录
_store_root: Path | None = None

def init_store(session_dir: str | Path) -> None:
    """初始化存储目录。"""
    global _store_root
    _store_root = Path(session_dir) / "tool-results"
    _store_root.mkdir(parents=True, exist_ok=True)

def _get_store_root() -> Path:
    if _store_root is None:
        # fallback：用户目录
        p = Path.home() / ".giraffe" / "sessions" / "default" / "tool-results"
        p.mkdir(parents=True, exist_ok=True)
        return p
    return _store_root

def get_threshold(tool_name: str) -> float:
    """获取工具的持久化阈值。"""
    return _TOOL_THRESHOLDS.get(tool_name, _DEFAULT_THRESHOLD)

def maybe_persist(tool_name: str, content: str) -> str:
    """
    如果内容超过阈值，写磁盘并返回 <persisted-output> 引用。
    否则原样返回内容。

    """
    threshold = get_threshold(tool_name)
    if len(content) <= threshold:
        return content

    # 生成唯一文件名
    digest = hashlib.md5(content.encode()).hexdigest()[:8]
    ts = int(time.time() * 1000)
    filename = f"{tool_name}_{ts}_{digest}.txt"
    filepath = _get_store_root() / filename

    try:
        filepath.write_text(content, encoding="utf-8")
        logger.info(
            f"[ToolResultStore] {tool_name} 结果 {len(content)} 字符 → 写入 {filepath}"
        )
        return f"{PERSISTED_TAG}{filepath}{PERSISTED_CLOSE}"
    except Exception as e:
        logger.warning(f"[ToolResultStore] 写入失败: {e}，改用截断")
        return content[:threshold] + f"\n...[截断，原始长度 {len(content)} 字符]"

def clear_old_tool_results(messages: list[dict], keep_recent: int = 5) -> list[dict]:
    """
    清理历史 tool_result（保留最近 keep_recent 个），
    用 TOOL_RESULT_CLEARED 替换内容，节省 token。
    对应 microCompact 的 tool_result 清理。
    """
    # 找出所有 tool_result 消息的位置
    tool_result_indices: list[int] = []
    for i, msg in enumerate(messages):
        if msg.get("role") == "user":
            content = msg.get("content", [])
            if isinstance(content, list) and any(
                c.get("type") == "tool_result" for c in content
            ):
                tool_result_indices.append(i)

    # 保留最近 N 个，清理其余
    to_clear = tool_result_indices[:-keep_recent] if len(tool_result_indices) > keep_recent else []

    new_messages = []
    for i, msg in enumerate(messages):
        if i not in to_clear:
            new_messages.append(msg)
            continue
        # 清理 tool_result 内容
        new_msg = dict(msg)
        content = msg.get("content", [])
        if isinstance(content, list):
            new_content = []
            for block in content:
                if block.get("type") == "tool_result":
                    new_content.append({**block, "content": TOOL_RESULT_CLEARED})
                else:
                    new_content.append(block)
            new_msg["content"] = new_content
        new_messages.append(new_msg)

    cleared = len(to_clear)
    if cleared:
        logger.info(f"[ToolResultStore] 清理了 {cleared} 条旧 tool_result")
    return new_messages

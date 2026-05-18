"""
工具结果持久化
大结果写磁盘，上下文只保留 <persisted-output> 预览引用，防止 context 溢出。
参考 src/utils/toolResultStorage.ts
"""
from __future__ import annotations

import logging
import math
from pathlib import Path

logger = logging.getLogger("tool_result_store")

PERSISTED_TAG   = "<persisted-output>"
PERSISTED_CLOSE = "</persisted-output>"
TOOL_RESULT_CLEARED = "[Old tool result content cleared]"

# 预览大小（字节）
PREVIEW_SIZE = 2_000

# 各工具的持久化阈值（字符数），超过则写磁盘
# math.inf 表示永不持久化（结果需完整传给模型）
_DEFAULT_THRESHOLD = 50_000

_TOOL_THRESHOLDS: dict[str, float] = {
    "bash":        50_000,
    "read_file":   30_000,
    "grep":        40_000,
    "glob":        20_000,
    "web_fetch":   30_000,
    "todo_read":   math.inf,   # 永不持久化
    "todo_write":  math.inf,
}

# 会话存储根目录（由 init_store() 初始化）
_store_root: Path | None = None


def init_store(session_dir: str | Path) -> None:
    """初始化存储目录（在会话启动时调用）。"""
    global _store_root
    _store_root = Path(session_dir) / "tool-results"
    _store_root.mkdir(parents=True, exist_ok=True)
    logger.debug(f"[ToolResultStore] 存储目录: {_store_root}")


def _get_store_root() -> Path:
    if _store_root is None:
        p = Path.home() / ".giraffe" / "sessions" / "default" / "tool-results"
        p.mkdir(parents=True, exist_ok=True)
        return p
    return _store_root


def get_threshold(tool_name: str) -> float:
    """获取工具的持久化阈值（字符数）。"""
    return _TOOL_THRESHOLDS.get(tool_name, _DEFAULT_THRESHOLD)


def _generate_preview(content: str, max_bytes: int = PREVIEW_SIZE) -> tuple[str, bool]:
    """
    生成内容预览，尽量在换行处截断。
    返回 (preview, has_more)。
    """
    if len(content) <= max_bytes:
        return content, False
    truncated = content[:max_bytes]
    last_newline = truncated.rfind("\n")
    cut = last_newline if last_newline > max_bytes * 0.5 else max_bytes
    return content[:cut], True


def _format_size(n: int) -> str:
    if n >= 1_000_000:
        return f"{n/1_000_000:.1f}MB"
    if n >= 1_000:
        return f"{n/1_000:.1f}KB"
    return f"{n}B"


def maybe_persist(tool_use_id: str, tool_name: str, content: str) -> str:
    """
    若内容超过阈值，写磁盘并返回 <persisted-output> 预览引用。
    否则原样返回内容。

    写入幂等：同一 tool_use_id 已有文件时跳过写入，直接生成预览。
    参考 src toolResultStorage.ts persistToolResult()。
    """
    threshold = get_threshold(tool_name)
    if not math.isfinite(threshold) or len(content) <= threshold:
        return content

    # 文件名用 tool_use_id 保证唯一幂等
    filepath = _get_store_root() / f"{tool_use_id}.txt"

    if not filepath.exists():
        try:
            filepath.write_text(content, encoding="utf-8")
            logger.info(
                f"[ToolResultStore] {tool_name} ({tool_use_id}) "
                f"{_format_size(len(content))} → {filepath.name}"
            )
        except Exception as e:
            logger.warning(f"[ToolResultStore] 写入失败: {e}，改用截断")
            return content[:int(threshold)] + f"\n...[截断，原始长度 {_format_size(len(content))}]"
    else:
        logger.debug(f"[ToolResultStore] {tool_use_id} 已持久化，跳过写入")

    preview, has_more = _generate_preview(content)
    size_str = _format_size(len(content))
    preview_str = f"{PERSISTED_TAG}\n"
    preview_str += f"Output too large ({size_str}). Full output saved to: {filepath}\n\n"
    preview_str += f"Preview (first {_format_size(PREVIEW_SIZE)}):\n"
    preview_str += preview
    preview_str += "\n...\n" if has_more else "\n"
    preview_str += PERSISTED_CLOSE
    return preview_str


def clear_old_tool_results(messages: list[dict], keep_recent: int = 5) -> list[dict]:
    """
    清理历史 tool_result（保留最近 keep_recent 个），
    用 TOOL_RESULT_CLEARED 替换内容，节省 token。
    对应 src 的 microCompact tool_result 清理。
    """
    tool_result_indices: list[int] = []
    for i, msg in enumerate(messages):
        if msg.get("role") == "user":
            content = msg.get("content", [])
            if isinstance(content, list) and any(
                c.get("type") == "tool_result" for c in content
            ):
                tool_result_indices.append(i)

    to_clear = set(tool_result_indices[:-keep_recent]) if len(tool_result_indices) > keep_recent else set()

    new_messages = []
    for i, msg in enumerate(messages):
        if i not in to_clear:
            new_messages.append(msg)
            continue
        new_msg = dict(msg)
        content = msg.get("content", [])
        if isinstance(content, list):
            new_msg["content"] = [
                {**block, "content": TOOL_RESULT_CLEARED}
                if block.get("type") == "tool_result"
                else block
                for block in content
            ]
        new_messages.append(new_msg)

    cleared = len(to_clear)
    if cleared:
        logger.info(f"[ToolResultStore] 清理了 {cleared} 条旧 tool_result")
    return new_messages

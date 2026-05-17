"""
Context Auto-Compaction
三级阈值触发、micro-compact（清旧 tool_result）、full-compact（LLM 摘要）。
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Callable

logger = logging.getLogger("compactor")

# 对应 calculateTokenWarningState 的三级阈值
WARN_THRESHOLD = 0.70     # 70%: 警告
AUTO_THRESHOLD = 0.85     # 85%: 自动触发 micro-compact
BLOCK_THRESHOLD = 0.95    # 95%: 全量压缩（blocking）

# 模型上下文窗口大小（token）
MODEL_CONTEXT_WINDOWS: dict[str, int] = {
    "claude-sonnet-4-6":          200_000,
    "claude-opus-4":              200_000,
    "gemini-3.1-pro-preview":     1_048_576,
    "gemini-3.1-flash-lite":      1_048_576,
    "xai/grok-4.20-reasoning":    131_072,
}
_DEFAULT_CONTEXT_WINDOW = 128_000

# 粗略 token 估算：4 字符/token
_CHARS_PER_TOKEN = 4

def estimate_tokens(messages: list[dict]) -> int:
    """粗略估算消息列表的 token 数。"""
    total_chars = 0
    for msg in messages:
        content = msg.get("content", "")
        if isinstance(content, str):
            total_chars += len(content)
        elif isinstance(content, list):
            for block in content:
                if isinstance(block, dict):
                    total_chars += len(str(block.get("content", "")))
                    total_chars += len(str(block.get("text", "")))
    return total_chars // _CHARS_PER_TOKEN

def get_context_window(model: str) -> int:
    for k, v in MODEL_CONTEXT_WINDOWS.items():
        if k in model:
            return v
    return _DEFAULT_CONTEXT_WINDOW

@dataclass
class CompactionState:
    """当前上下文状态。"""
    token_count: int
    context_window: int
    fill_ratio: float
    level: str   # 'ok' | 'warn' | 'auto' | 'block'
    needs_compact: bool
    message: str

def check_compaction_state(messages: list[dict], model: str) -> CompactionState:
    """
    计算当前上下文填充状态，对应 calculateTokenWarningState。
    """
    token_count = estimate_tokens(messages)
    context_window = get_context_window(model)
    ratio = token_count / context_window

    if ratio >= BLOCK_THRESHOLD:
        return CompactionState(
            token_count=token_count, context_window=context_window,
            fill_ratio=ratio, level="block", needs_compact=True,
            message=f"⛔ 上下文已满 {ratio:.0%}，需要立即压缩"
        )
    elif ratio >= AUTO_THRESHOLD:
        return CompactionState(
            token_count=token_count, context_window=context_window,
            fill_ratio=ratio, level="auto", needs_compact=True,
            message=f"🔄 上下文 {ratio:.0%}，自动触发压缩"
        )
    elif ratio >= WARN_THRESHOLD:
        return CompactionState(
            token_count=token_count, context_window=context_window,
            fill_ratio=ratio, level="warn", needs_compact=False,
            message=f"⚠️  上下文 {ratio:.0%}，建议使用 /compact"
        )
    return CompactionState(
        token_count=token_count, context_window=context_window,
        fill_ratio=ratio, level="ok", needs_compact=False, message=""
    )

def micro_compact(messages: list[dict], keep_recent_tool_results: int = 5) -> list[dict]:
    """
    微压缩：只清理旧 tool_result 内容，保留结构。
    对应 src microCompact.ts。快速、无需 LLM 调用。
    """
    from executor.tool_result_store import clear_old_tool_results
    before = estimate_tokens(messages)
    result = clear_old_tool_results(messages, keep_recent=keep_recent_tool_results)
    after = estimate_tokens(result)
    saved = before - after
    if saved > 0:
        logger.info(f"[Compactor] micro-compact: -{saved} tokens ({before}→{after})")
    return result

def full_compact(
    messages: list[dict],
    call_llm: Callable[[list[dict], str], str],
    keep_recent: int = 10,
) -> list[dict]:
    """
    完整压缩：用 LLM 生成摘要，替换历史消息。
    对应 src compact.ts:compactConversation()。
    """
    if len(messages) <= keep_recent:
        return messages

    # 分离：保留最近 N 条消息
    to_summarize = messages[:-keep_recent]
    to_keep = messages[-keep_recent:]

    # 构建摘要请求
    summary_request = [
        {
            "role": "user",
            "content": (
                "请将以下对话历史压缩为详细摘要，保留所有关键信息、"
                "决策、代码变更和重要结论：\n\n"
                + _format_messages_for_summary(to_summarize)
            )
        }
    ]

    try:
        summary = call_llm(
            summary_request,
            "你是一个专业的对话摘要器。生成详细、结构化的摘要，不遗漏任何重要内容。"
        )
        logger.info(
            f"[Compactor] full-compact: {len(to_summarize)} → 1 条摘要消息, "
            f"保留最近 {keep_recent} 条"
        )
        # 将摘要作为第一条消息
        summary_msg = {
            "role": "user",
            "content": f"[对话历史摘要]\n\n{summary}"
        }
        summary_reply = {
            "role": "assistant",
            "content": "已了解对话历史。请继续。"
        }
        return [summary_msg, summary_reply] + to_keep
    except Exception as e:
        logger.warning(f"[Compactor] 摘要生成失败，使用 micro-compact: {e}")
        return micro_compact(messages)

def _format_messages_for_summary(messages: list[dict]) -> str:
    """将消息列表格式化为文本供摘要用。"""
    lines = []
    for msg in messages:
        role = msg.get("role", "?")
        content = msg.get("content", "")
        if isinstance(content, list):
            text_parts = []
            for block in content:
                if isinstance(block, dict):
                    if block.get("type") == "text":
                        text_parts.append(block.get("text", ""))
                    elif block.get("type") == "tool_use":
                        text_parts.append(f"[调用工具: {block.get('name','?')}]")
                    elif block.get("type") == "tool_result":
                        text_parts.append(f"[工具结果: {str(block.get('content',''))[:100]}]")
            content = " ".join(text_parts)
        lines.append(f"{role}: {str(content)[:500]}")
    return "\n".join(lines)

class ContextCompactor:
    """
    主动上下文管理器，集成 check/micro/full compact。
    在 AgenticLoop 和 chat() 中使用。
    """

    def __init__(self, model: str, call_llm: Callable | None = None):
        self.model = model
        self.call_llm = call_llm

    def check_and_compact(
        self,
        messages: list[dict],
        force: bool = False,
    ) -> tuple[list[dict], CompactionState]:
        """
        检查状态并按需压缩。
        返回 (new_messages, state)。
        """
        state = check_compaction_state(messages, self.model)

        if not state.needs_compact and not force:
            if state.level == "warn":
                logger.info(state.message)
            return messages, state

        logger.info(state.message)

        if state.level == "auto":
            new_msgs = micro_compact(messages)
        elif state.level == "block":
            if self.call_llm:
                new_msgs = full_compact(messages, self.call_llm)
            else:
                new_msgs = micro_compact(messages)
        else:
            new_msgs = messages

        return new_msgs, state

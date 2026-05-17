"""
后台 LLM 查询 — 
用小模型非阻塞完成辅助任务：意图分类、记忆评分、摘要生成、会话标题。
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger("side_query")

# 默认使用最快的小模型
_DEFAULT_SMALL_MODEL = "gemini-3.1-flash-lite"
_DEFAULT_MAX_TOKENS = 512

@dataclass
class SideQueryResult:
    text: str
    model: str
    error: str | None = None
    ok: bool = True

class SideQuery:
    """
    后台 LLM 查询。
    总是使用快速小模型，不阻塞主对话流程。
    """

    def __init__(self, call_llm_fn=None, model: str = _DEFAULT_SMALL_MODEL):
        """
        call_llm_fn: (messages, system, model, max_tokens) -> str 的同步函数。
        如果为 None，从 pipeline 动态获取。
        """
        self._call_llm = call_llm_fn
        self._model = model

    def _get_llm_fn(self):
        if self._call_llm:
            return self._call_llm
        # 懒加载 pipeline
        from executor.pipeline import ExecutorPipeline, ExecutionContext
        pipeline = ExecutorPipeline.get_default()

        def _fn(messages: list, system: str, model: str, max_tokens: int) -> str:
            ctx = ExecutionContext(
                message=messages[-1]["content"] if messages else "",
                model=model,
                system_prompt=system,
                messages=messages[:-1] if len(messages) > 1 else [],
                max_tokens=max_tokens,
                use_cache=False,
            )
            result = pipeline.execute(ctx)
            return result.response or ""
        return _fn

    async def query(
        self,
        messages: list[dict],
        system: str = "",
        max_tokens: int = _DEFAULT_MAX_TOKENS,
        model: str | None = None,
    ) -> SideQueryResult:
        """非阻塞后台查询，使用 executor 线程池。"""
        _model = model or self._model
        fn = self._get_llm_fn()
        loop = asyncio.get_event_loop()
        try:
            text = await loop.run_in_executor(
                None, fn, messages, system, _model, max_tokens
            )
            return SideQueryResult(text=text, model=_model)
        except Exception as e:
            logger.debug(f"[SideQuery] 失败: {e}")
            return SideQueryResult(text="", model=_model, error=str(e), ok=False)

    def query_sync(self, messages: list[dict], system: str = "",
                   max_tokens: int = _DEFAULT_MAX_TOKENS,
                   model: str | None = None) -> SideQueryResult:
        """同步版本。"""
        _model = model or self._model
        fn = self._get_llm_fn()
        try:
            text = fn(messages, system, _model, max_tokens)
            return SideQueryResult(text=text, model=_model)
        except Exception as e:
            logger.debug(f"[SideQuery] 失败: {e}")
            return SideQueryResult(text="", model=_model, error=str(e), ok=False)

    # ── 预定义 side queries ────────────────────────────────────────────────

    async def classify_intent(self, user_message: str) -> str:
        """
        快速意图分类（用于路由决策辅助）。
        对应 src 中 yoloClassifier 的轻量版。
        """
        system = (
            "你是一个意图分类器。将用户消息分类为以下之一，只输出分类名：\n"
            "AGENT_TASK / REPO_ANALYSIS / CODE_DESIGN / CODING / GENERAL_CHAT / TRENDING"
        )
        result = await self.query(
            [{"role": "user", "content": user_message[:500]}],
            system=system, max_tokens=20,
        )
        return result.text.strip().upper() if result.ok else "GENERAL_CHAT"

    async def score_memory_relevance(self, memory_text: str, context: str) -> float:
        """
        评估记忆片段与当前上下文的相关性（0-1）。
        对应 startRelevantMemoryPrefetch。
        """
        system = "请评估以下记忆片段与当前对话的相关性，只输出 0.0-1.0 的数字。"
        msg = f"记忆：{memory_text[:200]}\n\n当前对话：{context[:300]}"
        result = await self.query(
            [{"role": "user", "content": msg}],
            system=system, max_tokens=10,
        )
        try:
            return float(result.text.strip())
        except ValueError:
            return 0.0

    async def generate_title(self, messages: list[dict], max_words: int = 6) -> str:
        """
        为对话生成简短标题（用于会话记录）。
        """
        recent = messages[-3:] if len(messages) > 3 else messages
        content = "\n".join(
            f"{m['role']}: {str(m.get('content',''))[:100]}" for m in recent
        )
        result = await self.query(
            [{"role": "user",
              "content": f"为以下对话生成一个不超过{max_words}个词的标题：\n{content}"}],
            system="只输出标题，不加引号或标点。",
            max_tokens=30,
        )
        return result.text.strip() or "新对话"

    async def generate_tool_summary(self, tool_calls: list[dict]) -> str:
        """
        将多个工具调用摘要为一句话（用于上下文压缩）。
        对应 generateToolUseSummary。
        """
        if not tool_calls:
            return ""
        calls_text = "\n".join(
            f"- {tc.get('name','?')}: {str(tc.get('input',''))[:80]}"
            for tc in tool_calls[:10]
        )
        result = await self.query(
            [{"role": "user",
              "content": f"用一句话总结以下工具调用的目的：\n{calls_text}"}],
            system="只输出一句话摘要。",
            max_tokens=80,
        )
        return result.text.strip()

    async def is_command_safe(self, command: str) -> bool:
        """
        用 LLM 判断 bash 命令是否安全（yoloClassifier 简化版）。
        先走规则引擎，规则不确定时才调用 LLM。
        """
        from tools.shell_validator import classify_command
        level, _ = classify_command(command)
        if level == "safe":
            return True
        if level == "deny":
            return False
        # 'ask' → 用 LLM 二次判断
        system = (
            "你是安全分析器。判断以下 shell 命令是否安全（只读/无副作用）。"
            "只回答 SAFE 或 UNSAFE。"
        )
        result = await self.query(
            [{"role": "user", "content": f"命令：{command}"}],
            system=system, max_tokens=10,
        )
        return "SAFE" in result.text.upper()

# ── 全局单例 ──────────────────────────────────────────────────────────────────

_side_query: SideQuery | None = None

def get_side_query(call_llm_fn=None) -> SideQuery:
    global _side_query
    if _side_query is None:
        _side_query = SideQuery(call_llm_fn=call_llm_fn)
    return _side_query

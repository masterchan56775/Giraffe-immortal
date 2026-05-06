"""
LLMClassifier — LLM意图分类器
仅在关键词匹配不明确时触发（约200ms）
"""
from __future__ import annotations

import json
import logging
from typing import Any

from .intent_classifier import ClassifyResult, TaskType

logger = logging.getLogger(__name__)


# LLM分类的系统提示
CLASSIFY_SYSTEM_PROMPT = """你是一个精确的任务意图分类器。
请将用户消息分类为以下类型之一，并以JSON格式返回：
- chat: 日常对话、问候、闲聊
- code_small: 简单代码修改（一行或少量修改）
- code_medium: 中等代码任务（函数、模块）
- code_large: 复杂代码任务（系统设计、架构）
- reasoning_light: 简单分析、解释
- reasoning: 复杂推理、论证、深度分析
- vision: 图像相关任务
- search: 搜索查询

返回格式: {"task_type": "...", "confidence": 0.95, "reason": "..."}"""


class LLMClassifier:
    """
    LLM意图分类器（维度2，慢路径）。
    仅在关键词分类置信度不足时触发。
    支持任何OpenAI兼容接口。
    """

    def __init__(
        self,
        model: str = "mimo-v2-flash",
        api_key: str = "",
        base_url: str = "",
        timeout: float = 5.0,
    ) -> None:
        self._model = model
        self._api_key = api_key
        self._base_url = base_url
        self._timeout = timeout
        self._call_count = 0
        self._cache: dict[str, ClassifyResult] = {}

    def classify(self, message: str) -> ClassifyResult:
        """
        使用LLM对消息进行意图分类。
        先查本地缓存，缓存命中直接返回。
        """
        cache_key = message[:100]  # 用前100字符作key
        if cache_key in self._cache:
            logger.debug(f"[LLMClassifier] 缓存命中: {cache_key[:30]}...")
            return self._cache[cache_key]

        result = self._call_llm(message)
        self._cache[cache_key] = result
        self._call_count += 1
        return result

    def _call_llm(self, message: str) -> ClassifyResult:
        """实际调用LLM（需要API Key和base_url配置）。"""
        if not self._api_key or not self._base_url or self._api_key.startswith("${"):
            logger.warning("[LLMClassifier] 未配置真实API Key或base_url，返回默认分类")
            return ClassifyResult(
                task_type=TaskType.CHAT,
                confidence=0.5,
                method="llm_unavailable",
            )

        try:
            import urllib.request
            import urllib.error

            payload = {
                "model": self._model,
                "messages": [
                    {"role": "system", "content": CLASSIFY_SYSTEM_PROMPT},
                    {"role": "user", "content": f"请分类这条消息：{message}"},
                ],
                "max_tokens": 100,
                "temperature": 0.1,
            }
            data = json.dumps(payload).encode("utf-8")
            url = f"{self._base_url.rstrip('/')}/chat/completions"
            req = urllib.request.Request(
                url,
                data=data,
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {self._api_key}",
                },
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=self._timeout) as resp:
                resp_data = json.loads(resp.read().decode("utf-8"))
                content = resp_data["choices"][0]["message"]["content"]
                parsed = json.loads(content)
                task_type = TaskType(parsed.get("task_type", "chat"))
                confidence = float(parsed.get("confidence", 0.8))
                return ClassifyResult(
                    task_type=task_type,
                    confidence=confidence,
                    method="llm",
                )
        except Exception as e:
            logger.error(f"[LLMClassifier] 调用失败: {e}")
            return ClassifyResult(
                task_type=TaskType.CHAT,
                confidence=0.4,
                method="llm_error",
            )

    @property
    def call_count(self) -> int:
        return self._call_count

    def clear_cache(self) -> None:
        self._cache.clear()

    def __repr__(self) -> str:
        return f"LLMClassifier(model={self._model}, calls={self._call_count})"

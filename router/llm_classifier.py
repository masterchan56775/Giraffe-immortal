"""
LLMClassifier — LLM意图分类器
仅在关键词匹配不明确时触发（约200ms）
"""
from __future__ import annotations

import json
import logging

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
        model: str = "gemini-3.1-flash-lite",
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
        """实际调用LLM，根据配置选择 ADC 认证或 OpenAI API Key 认证。"""
        # 判断是否使用 ADC 认证
        use_adc = not self._api_key or self._api_key.startswith("${")

        if use_adc:
            try:
                from google import genai
                from google.genai import types
            except ImportError:
                logger.error("[LLMClassifier] 缺少 google-genai 依赖，无法执行慢路径路由")
                return ClassifyResult(
                    task_type=TaskType.CHAT,
                    confidence=0.5,
                    method="llm_unavailable",
                )

            try:
                # 自动使用 ADC 凭据
                client = genai.Client(vertexai=True)
                response = client.models.generate_content(
                    model=self._model,
                    contents=f"请分类这条消息：{message}",
                    config=types.GenerateContentConfig(
                        system_instruction=CLASSIFY_SYSTEM_PROMPT,
                        temperature=0.1,
                        max_output_tokens=100,
                        response_mime_type="application/json",
                    )
                )
                content = response.text
                parsed = json.loads(content)
                task_type = TaskType(parsed.get("task_type", "chat"))
                confidence = float(parsed.get("confidence", 0.8))
                return ClassifyResult(
                    task_type=task_type,
                    confidence=confidence,
                    method="llm_adc",
                )
            except Exception as e:
                logger.error(f"[LLMClassifier] ADC 调用失败: {e}")
                return ClassifyResult(
                    task_type=TaskType.CHAT,
                    confidence=0.4,
                    method="llm_error",
                )
        else:
            # 兼容 OpenAI 协议的 API Key 调用
            import urllib.request
            import urllib.error
            
            payload = {
                "model": self._model,
                "messages": [
                    {"role": "system", "content": CLASSIFY_SYSTEM_PROMPT},
                    {"role": "user", "content": f"请分类这条消息：{message}"}
                ],
                "temperature": 0.1,
                "max_tokens": 100,
                "response_format": {"type": "json_object"}
            }
            data = json.dumps(payload).encode("utf-8")
            base_url = self._base_url or "https://api.openai.com/v1"
            url = f"{base_url.rstrip('/')}/chat/completions"
            req = urllib.request.Request(
                url,
                data=data,
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {self._api_key}",
                },
                method="POST",
            )
            try:
                with urllib.request.urlopen(req, timeout=self._timeout) as resp:
                    resp_data = json.loads(resp.read().decode("utf-8"))
                    content = resp_data["choices"][0]["message"]["content"]
                    parsed = json.loads(content)
                    task_type = TaskType(parsed.get("task_type", "chat"))
                    confidence = float(parsed.get("confidence", 0.8))
                    return ClassifyResult(
                        task_type=task_type,
                        confidence=confidence,
                        method="llm_apikey",
                    )
            except Exception as e:
                logger.error(f"[LLMClassifier] API Key 调用失败: {e}")
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

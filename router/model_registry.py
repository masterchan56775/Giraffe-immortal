"""
ModelRegistry — 模型注册表
维护 9种任务类型 × 3级降级 的完整模型矩阵
集成别名解析（haiku/sonnet/opus/flash/grok/[1m]...)
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Literal
from router.model_aliases import (
    parse_model_alias, get_canonical_name, get_api_provider,
    get_default_sonnet_model, get_small_fast_model,
    is_model_alias, MODEL_ALIASES,
)

ModelLevel = Literal["primary", "fallback", "emergency"]

@dataclass
class ModelConfig:
    """单个模型的配置信息。"""
    model: str
    provider: str = ""
    api_key: str = ""
    base_url: str = ""
    max_tokens: int = 4096
    temperature: float = 0.7

    def to_dict(self) -> dict:
        return {
            "model": self.model,
            "provider": self.provider,
            "api_key": self.api_key,
            "base_url": self.base_url,
            "max_tokens": self.max_tokens,
            "temperature": self.temperature,
        }

# 默认模型矩阵
# 路由设计：
#   Grok  (grok-4.20-reasoning)    ← agent_task, repo_analysis, search
#   Claude (claude-sonnet-4-6)     ← reasoning, code_large
#   Gemini (其他所有)              ← chat, code_small, code_medium, reasoning_light, vision
DEFAULT_MODEL_MATRIX: dict[str, dict[ModelLevel, str]] = {
    # ── Gemini Pro 层（通用任务） ───────────────────────────────────────────────────
    "chat":             {"primary": "gemini-3.1-pro-preview",  "fallback": "gemini-3-flash-preview",  "emergency": "gemini-3.1-flash-lite"},
    "code_small":       {"primary": "gemini-3.1-pro-preview",  "fallback": "gemini-3-flash-preview",  "emergency": "gemini-3.1-flash-lite"},
    "code_medium":      {"primary": "gemini-3.1-pro-preview",  "fallback": "gemini-3-flash-preview",  "emergency": "gemini-3.1-flash-lite"},
    "reasoning_light":  {"primary": "gemini-3.1-pro-preview",  "fallback": "gemini-3-flash-preview",  "emergency": "gemini-3.1-flash-lite"},
    "vision":           {"primary": "gemini-3.1-pro-preview",  "fallback": "gemini-3-flash-preview",  "emergency": "gemini-3.1-flash-lite"},
    "routing":          {"primary": "gemini-3.1-flash-lite",   "fallback": "gemini-3-flash-preview",  "emergency": "gemini-3.1-flash-lite"},
    "subtask":          {"primary": "gemini-3.1-pro-preview",  "fallback": "gemini-3-flash-preview",  "emergency": "gemini-3.1-flash-lite"},

    # ── Claude 层（严肃研究 + 系统级编码） ───────────────────────────────────
    "reasoning":        {"primary": "claude-sonnet-4-6",       "fallback": "gemini-3.1-pro-preview",  "emergency": "gemini-3-flash-preview"},
    "code_large":       {"primary": "claude-sonnet-4-6",       "fallback": "gemini-3.1-pro-preview",  "emergency": "gemini-3-flash-preview"},

    # ── Grok 层（自动化 Agent + 热点追踪 + 长仓库分析） ────────────────
    "agent_task":       {"primary": "xai/grok-4.20-reasoning",     "fallback": "claude-sonnet-4-6",       "emergency": "gemini-3.1-pro-preview"},
    "repo_analysis":    {"primary": "xai/grok-4.20-reasoning",     "fallback": "claude-sonnet-4-6",       "emergency": "gemini-3.1-pro-preview"},
    "search":           {"primary": "xai/grok-4.20-reasoning",     "fallback": "gemini-3.1-pro-preview",  "emergency": "gemini-3-flash-preview"},
}

# 子Agent路由矩阵
SUBAGENT_MATRIX: dict[str, str] = {
    "text_reasoning": "gemini-3-flash-preview",
    "code":           "claude-sonnet-4.6",
    "deep_reasoning": "claude-opus-4.7",
    "multi_model":    "opus-4.7+gpt-5.5",
}

class ModelRegistry:
    """
    模型注册表（单例）。
    提供按任务类型和降级级别查询模型名称的接口。
    """

    _instance: ModelRegistry | None = None

    def __init__(self, matrix: dict | None = None) -> None:
        self._matrix: dict[str, dict[ModelLevel, str]] = matrix or DEFAULT_MODEL_MATRIX
        self._subagent_matrix: dict[str, str] = SUBAGENT_MATRIX.copy()
        self._provider_map: dict[str, str] = {}   # model_name → provider
        self._base_url_map: dict[str, str] = {}    # model_name → base_url
        self._api_key_map: dict[str, str] = {}     # model_name → api_key

    @classmethod
    def get(cls) -> "ModelRegistry":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    @classmethod
    def reset(cls) -> None:
        cls._instance = None

    def load_from_config(self, model_matrix_cfg: dict) -> None:
        """从配置文件中加载模型矩阵（支持新任务类型动态注册）。"""
        for task_type, levels in model_matrix_cfg.items():
            # 允许新任务类型（不强制要求在默认矩阵中）
            if task_type not in self._matrix:
                self._matrix[task_type] = {
                    "primary": "gemini-3.1-pro-preview",
                    "fallback": "gemini-3-flash-preview",
                    "emergency": "gemini-3.1-flash-lite",
                }
            for level in ("primary", "fallback", "emergency"):
                if level in levels:
                    self._matrix[task_type][level] = levels[level]

    # ─── 查询接口 ─────────────────────────────────────────────────────────────
    def resolve_model_input(self, model_input: str) -> str:
        """
        将用户输入的模型名/别名解析为完整 API 模型名。
        。
        优先级：ANTHROPIC_MODEL 环境变量 > 别名解析 > 原样返回。
        """
        env_model = os.environ.get("ANTHROPIC_MODEL")
        if env_model:
            return parse_model_alias(env_model)
        return parse_model_alias(model_input)

    def get_model(self, task_type: str, level: ModelLevel = "primary") -> str:
        """获取指定任务类型和降级级别的模型名称（已解析别名）。"""
        task_matrix = self._matrix.get(task_type, self._matrix["chat"])
        raw = task_matrix.get(level, task_matrix.get("primary", "gemini-3-flash-preview"))
        # 矩阵中如果存在别名（如 "sonnet"），自动解析
        base = raw.split("[")[0].strip().lower()
        return parse_model_alias(raw) if base in MODEL_ALIASES else raw

    def get_model_chain(self, task_type: str) -> list[str]:
        """返回完整的降级链：[primary, fallback, emergency]。"""
        task_matrix = self._matrix.get(task_type, self._matrix["chat"])
        return [
            task_matrix.get("primary", "gemini-3-flash-preview"),
            task_matrix.get("fallback", "gemini-3-flash-preview"),
            task_matrix.get("emergency", "gemini-3.1-flash-lite"),
        ]

    def get_subagent_model(self, subagent_type: str) -> str:
        """获取子Agent的模型。"""
        return self._subagent_matrix.get(subagent_type, "gemini-3-flash-preview")

    def get_model_config(self, model_name: str) -> ModelConfig:
        """获取模型的完整配置。"""
        return ModelConfig(
            model=model_name,
            provider=self._provider_map.get(model_name, ""),
            api_key=self._api_key_map.get(model_name, ""),
            base_url=self._base_url_map.get(model_name, ""),
        )

    # ─── 注册 ────────────────────────────────────────────────────────────────
    def register_provider(self, model_name: str, provider: str,
                          base_url: str = "", api_key: str = "") -> None:
        """注册模型的Provider信息。"""
        self._provider_map[model_name] = provider
        if base_url:
            self._base_url_map[model_name] = base_url
        if api_key:
            self._api_key_map[model_name] = api_key

    def list_all_models(self) -> list[str]:
        """列出矩阵中所有涉及的模型名称（去重）。"""
        models: set[str] = set()
        for levels in self._matrix.values():
            models.update(levels.values())
        return sorted(models)

    def list_task_types(self) -> list[str]:
        return list(self._matrix.keys())

    def matrix_summary(self) -> dict:
        """返回完整矩阵摘要。"""
        return {
            task: {
                "primary": m.get("primary"),
                "fallback": m.get("fallback"),
                "emergency": m.get("emergency"),
            }
            for task, m in self._matrix.items()
        }

    def get_display_name(self, model: str) -> str:
        """获取模型的可读显示名称。"""
        canonical = get_canonical_name(model)
        display_map = {
            "claude-opus-4-6":   "Opus 4.6",
            "claude-opus-4-5":   "Opus 4.5",
            "claude-sonnet-4-6": "Sonnet 4.6",
            "claude-sonnet-4-5": "Sonnet 4.5",
            "claude-haiku-4-5":  "Haiku 4.5",
        }
        return display_map.get(canonical, model)

    def __repr__(self) -> str:
        return f"ModelRegistry(tasks={len(self._matrix)}, models={len(self.list_all_models())})"

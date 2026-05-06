"""
ModelRegistry — 模型注册表
维护 9种任务类型 × 3级降级 的完整模型矩阵
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


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


# 默认模型矩阵（9种任务 × 3级）
DEFAULT_MODEL_MATRIX: dict[str, dict[ModelLevel, str]] = {
    "chat":            {"primary": "mimo-v2.5",      "fallback": "mimo-v2.5",        "emergency": "mimo-v2-flash"},
    "code_small":      {"primary": "mimo-v2.5-pro",  "fallback": "mimo-v2.5",        "emergency": "mimo-v2.5"},
    "code_medium":     {"primary": "mimo-v2.5",      "fallback": "claude-haiku-4.5", "emergency": "mimo-v2.5-pro"},
    "code_large":      {"primary": "claude-sonnet-4.6", "fallback": "mimo-v2.5",     "emergency": "claude-haiku-4.5"},
    "reasoning_light": {"primary": "mimo-v2.5",      "fallback": "mimo-v2.5",        "emergency": "claude-haiku-4.5"},
    "reasoning":       {"primary": "opus-4.7",       "fallback": "claude-sonnet-4.6","emergency": "gpt-5.5"},
    "vision":          {"primary": "mimo-v2-omni",   "fallback": "gemini-3-flash",   "emergency": "claude-sonnet-4.6"},
    "routing":         {"primary": "mimo-v2-flash",  "fallback": "mimo-v2.5",        "emergency": "mimo-v2.5"},
    "subtask":         {"primary": "mimo-v2.5",      "fallback": "mimo-v2.5",        "emergency": "mimo-v2-flash"},
}

# 子Agent路由矩阵
SUBAGENT_MATRIX: dict[str, str] = {
    "text_reasoning": "mimo-v2.5",
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
        """从配置文件中加载模型矩阵。"""
        for task_type, levels in model_matrix_cfg.items():
            if task_type in self._matrix:
                for level in ("primary", "fallback", "emergency"):
                    if level in levels:
                        self._matrix[task_type][level] = levels[level]

    # ─── 查询接口 ─────────────────────────────────────────────────────────────
    def get_model(self, task_type: str, level: ModelLevel = "primary") -> str:
        """获取指定任务类型和降级级别的模型名称。"""
        task_matrix = self._matrix.get(task_type, self._matrix["chat"])
        return task_matrix.get(level, task_matrix.get("primary", "mimo-v2.5"))

    def get_model_chain(self, task_type: str) -> list[str]:
        """返回完整的降级链：[primary, fallback, emergency]。"""
        task_matrix = self._matrix.get(task_type, self._matrix["chat"])
        return [
            task_matrix.get("primary", "mimo-v2.5"),
            task_matrix.get("fallback", "mimo-v2.5"),
            task_matrix.get("emergency", "mimo-v2-flash"),
        ]

    def get_subagent_model(self, subagent_type: str) -> str:
        """获取子Agent的模型。"""
        return self._subagent_matrix.get(subagent_type, "mimo-v2.5")

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

    def __repr__(self) -> str:
        return f"ModelRegistry(tasks={len(self._matrix)}, models={len(self.list_all_models())})"

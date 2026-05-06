"""
GiraffeConfig — 全局配置管理类
负责加载、访问、更新 config.json 中的所有配置项
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


class GiraffeConfig:
    """
    全局配置单例。
    所有模块通过 GiraffeConfig.get() 获取配置实例。
    """

    _instance: GiraffeConfig | None = None
    _config_path: Path = Path(__file__).parent.parent / "config.json"

    def __init__(self, config_path: Path | str | None = None) -> None:
        if config_path:
            self._config_path = Path(config_path)
        self._data: dict[str, Any] = {}
        self.load()

    # ─── 单例访问 ────────────────────────────────────────────────────────────
    @classmethod
    def get(cls, config_path: Path | str | None = None) -> "GiraffeConfig":
        """获取全局配置单例。"""
        if cls._instance is None:
            cls._instance = cls(config_path)
        return cls._instance

    @classmethod
    def reset(cls) -> None:
        """重置单例（主要用于测试）。"""
        cls._instance = None

    # ─── 加载 / 保存 ─────────────────────────────────────────────────────────
    def load(self) -> None:
        """从磁盘加载配置文件。

        注意:
        - 会自动加载项目根目录下的 .env 文件以支持环境变量。
        - 配置文件不存在时，静默使用空配置。
        - JSON 格式错误时，记录错误并回落到空配置，不会抛出异常导致启动失败。
        """
        import logging as _log
        try:
            from dotenv import load_dotenv
            env_path = self._config_path.parent / ".env"
            if env_path.exists():
                load_dotenv(dotenv_path=env_path)
        except ImportError:
            _log.getLogger(__name__).warning("[GiraffeConfig] 未安装 python-dotenv，将无法自动加载 .env 文件。")

        if not self._config_path.exists():
            _log.getLogger(__name__).info(
                f"[GiraffeConfig] 配置文件不存在: {self._config_path} —— 使用空配置。"
            )
            self._data = {}
            return
        try:
            with open(self._config_path, encoding="utf-8") as f:
                raw = json.load(f)
            if not isinstance(raw, dict):
                raise ValueError(
                    f"[GiraffeConfig] 配置文件根元素必须是 JSON 对象，得到 {type(raw).__name__}。"
                )
            self._data = self._resolve_env_vars(raw)
        except json.JSONDecodeError as e:
            _log.getLogger(__name__).error(
                f"[GiraffeConfig] JSON 解析失败: {self._config_path} | {e} —— 回落到空配置。"
            )
            self._data = {}
        except Exception as e:
            _log.getLogger(__name__).error(
                f"[GiraffeConfig] 加载配置失败: {e} —— 回落到空配置。"
            )
            self._data = {}

    def save(self) -> None:
        """将当前配置写回磁盘。"""
        self._config_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self._config_path, "w", encoding="utf-8") as f:
            json.dump(self._data, f, ensure_ascii=False, indent=2)

    # ─── 读取 ────────────────────────────────────────────────────────────────
    def get_value(self, key_path: str, default: Any = None) -> Any:
        """
        按点分路径获取配置值。
        例：get_value("router.circuit_breaker.cooldown_seconds") → 60
        """
        keys = key_path.split(".")
        node = self._data
        for k in keys:
            if not isinstance(node, dict):
                return default
            node = node.get(k, default)
            if node is default:
                return default
        return node

    def set_value(self, key_path: str, value: Any) -> None:
        """按点分路径设置配置值，并自动保存。"""
        keys = key_path.split(".")
        node = self._data
        for k in keys[:-1]:
            node = node.setdefault(k, {})
        node[keys[-1]] = value
        self.save()

    # ─── 便捷属性 ─────────────────────────────────────────────────────────────
    @property
    def router(self) -> dict:
        return self._data.get("router", {})

    @property
    def model_matrix(self) -> dict:
        return self.router.get("model_matrix", {})

    @property
    def primary_model(self) -> dict:
        return self.router.get("primary_model", {})

    @property
    def security(self) -> dict:
        return self._data.get("security", {})

    @property
    def memory_cfg(self) -> dict:
        return self._data.get("memory", {})

    @property
    def compression(self) -> dict:
        return self._data.get("compression", {})

    @property
    def credit_monitor(self) -> dict:
        return self._data.get("credit_monitor", {})

    @property
    def executor(self) -> dict:
        return self._data.get("executor", {})

    @property
    def display(self) -> dict:
        return self._data.get("display", {})

    @property
    def auto_fusion(self) -> dict:
        return self._data.get("auto_fusion", {})

    @property
    def raw(self) -> dict:
        """返回完整的原始配置字典。"""
        return self._data

    # ─── 内部工具 ─────────────────────────────────────────────────────────────
    def _resolve_env_vars(self, obj: Any) -> Any:
        """递归解析配置值中的 ${ENV_VAR} 环境变量引用。"""
        if isinstance(obj, dict):
            return {k: self._resolve_env_vars(v) for k, v in obj.items()}
        if isinstance(obj, list):
            return [self._resolve_env_vars(item) for item in obj]
        if isinstance(obj, str) and obj.startswith("${") and obj.endswith("}"):
            var_name = obj[2:-1]
            return os.environ.get(var_name, obj)  # 未找到时保留原字符串
        return obj

    def __repr__(self) -> str:
        return f"GiraffeConfig(path={self._config_path})"

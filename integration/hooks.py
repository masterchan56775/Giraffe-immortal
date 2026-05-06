"""
HookSystem — 钩子系统
在API调用前/后/出错时执行自定义逻辑
"""
from __future__ import annotations

import logging
from typing import Any, Callable

logger = logging.getLogger(__name__)

# 支持的钩子事件
HOOK_EVENTS = [
    "pre_api_request",     # API调用前
    "post_api_response",   # API响应后
    "error_occurred",      # 错误发生
    "session_start",       # 会话开始
    "session_end",         # 会话结束
    "memory_updated",      # 记忆更新后
    "model_switched",      # 模型切换后
]


class HookSystem:
    """
    钩子系统（单例）。
    支持在生命周期关键节点注册和触发自定义回调。
    """

    _instance: HookSystem | None = None

    def __init__(self) -> None:
        self._hooks: dict[str, list[Callable]] = {event: [] for event in HOOK_EVENTS}
        self._fire_count: dict[str, int] = {event: 0 for event in HOOK_EVENTS}

    @classmethod
    def get(cls) -> "HookSystem":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    @classmethod
    def reset(cls) -> None:
        cls._instance = None

    def register(self, event: str, callback: Callable, priority: int = 5) -> None:
        """注册钩子回调函数。"""
        if event not in self._hooks:
            logger.warning(f"[HookSystem] 未知事件: {event}")
            return
        self._hooks[event].append(callback)
        logger.debug(f"[HookSystem] 注册钩子: {event}")

    def fire(self, event: str, **kwargs) -> list[Any]:
        """触发事件，返回所有回调的结果。"""
        if event not in self._hooks:
            return []
        self._fire_count[event] = self._fire_count.get(event, 0) + 1
        results = []
        for cb in self._hooks[event]:
            try:
                result = cb(**kwargs)
                results.append(result)
            except Exception as e:
                logger.error(f"[HookSystem] 钩子回调错误 [{event}]: {e}")
        return results

    def unregister(self, event: str, callback) -> bool:
        """取消注册特定钩子。"""
        if event in self._hooks and callback in self._hooks[event]:
            self._hooks[event].remove(callback)
            return True
        return False

    def list_events(self) -> list:
        """返回所有支持的事件名称。"""
        return list(self._hooks.keys())

    def clear(self, event: str | None = None) -> None:
        """清除钩子（全部或指定事件）。"""
        if event:
            self._hooks[event] = []
        else:
            for k in self._hooks:
                self._hooks[k] = []

    def stats(self) -> dict:
        return {
            "registered": {e: len(cbs) for e, cbs in self._hooks.items()},
            "fired": self._fire_count,
        }

    def __repr__(self) -> str:
        total = sum(len(cbs) for cbs in self._hooks.values())
        return f"HookSystem(total_hooks={total})"

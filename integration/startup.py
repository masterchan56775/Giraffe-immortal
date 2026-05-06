"""StartupManager — 启动管理器"""
from __future__ import annotations
import logging
from typing import Callable
logger = logging.getLogger(__name__)

class StartupManager:
    """管理系统启动时需要执行的初始化任务。"""
    def __init__(self) -> None:
        self._tasks: list[tuple[int, str, Callable]] = []

    def register(self, name: str, func: Callable, order: int = 50) -> None:
        self._tasks.append((order, name, func))
        self._tasks.sort(key=lambda x: x[0])

    def run_all(self) -> dict:
        results = {}
        for order, name, func in self._tasks:
            try:
                func()
                results[name] = "ok"
                logger.info(f"[Startup] ✓ {name}")
            except Exception as e:
                results[name] = f"error: {e}"
                logger.error(f"[Startup] ✗ {name}: {e}")
        return results

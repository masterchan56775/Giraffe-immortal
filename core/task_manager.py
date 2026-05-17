"""
TaskManager — 任务调度器
管理任务队列、优先级、生命周期
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Callable


class TaskStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class TaskPriority(int, Enum):
    LOW = 1
    NORMAL = 5
    HIGH = 8
    CRITICAL = 10


@dataclass
class Task:
    """单个任务的数据对象。"""
    task_id: str = field(default_factory=lambda: f"task_{uuid.uuid4().hex[:8]}")
    name: str = ""
    payload: Any = None
    priority: TaskPriority = TaskPriority.NORMAL
    status: TaskStatus = TaskStatus.PENDING
    created_at: datetime = field(default_factory=datetime.now)
    started_at: datetime | None = None
    completed_at: datetime | None = None
    result: Any = None
    error: str | None = None
    metadata: dict = field(default_factory=dict)

    def start(self) -> None:
        self.status = TaskStatus.RUNNING
        self.started_at = datetime.now()

    def complete(self, result: Any = None) -> None:
        self.status = TaskStatus.COMPLETED
        self.completed_at = datetime.now()
        self.result = result

    def fail(self, error: str) -> None:
        self.status = TaskStatus.FAILED
        self.completed_at = datetime.now()
        self.error = error

    def cancel(self) -> None:
        self.status = TaskStatus.CANCELLED
        self.completed_at = datetime.now()

    @property
    def duration_ms(self) -> float | None:
        if self.started_at and self.completed_at:
            return (self.completed_at - self.started_at).total_seconds() * 1000
        return None

    def to_dict(self) -> dict:
        return {
            "task_id": self.task_id,
            "name": self.name,
            "priority": self.priority.value,
            "status": self.status.value,
            "created_at": self.created_at.isoformat(),
            "duration_ms": self.duration_ms,
            "error": self.error,
        }


class TaskManager:
    """
    任务调度管理器（单例）。
    维护任务队列，提供注册、查询、状态变更接口。
    """

    _instance: TaskManager | None = None

    def __init__(self) -> None:
        self._tasks: dict[str, Task] = {}
        self._hooks: dict[str, list[Callable]] = {
            "on_start": [],
            "on_complete": [],
            "on_fail": [],
        }

    @classmethod
    def get(cls) -> "TaskManager":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    @classmethod
    def reset(cls) -> None:
        cls._instance = None

    # ─── 任务注册 ─────────────────────────────────────────────────────────────
    def register(
        self,
        name: str,
        payload: Any = None,
        priority: TaskPriority = TaskPriority.NORMAL,
        metadata: dict | None = None,
    ) -> Task:
        """注册一个新任务，返回 Task 对象。"""
        task = Task(name=name, payload=payload, priority=priority, metadata=metadata or {})
        self._tasks[task.task_id] = task
        return task

    def create(self, name: str, payload: Any = None) -> Task:
        """便捷方法：以普通优先级创建任务。"""
        return self.register(name, payload)

    # ─── 状态变更 ─────────────────────────────────────────────────────────────
    def start_task(self, task_id: str) -> Task | None:
        task = self._tasks.get(task_id)
        if task:
            task.start()
            self._fire("on_start", task)
        return task

    def complete_task(self, task_id: str, result: Any = None) -> Task | None:
        task = self._tasks.get(task_id)
        if task:
            task.complete(result)
            self._fire("on_complete", task)
        return task

    def fail_task(self, task_id: str, error: str) -> Task | None:
        task = self._tasks.get(task_id)
        if task:
            task.fail(error)
            self._fire("on_fail", task)
        return task

    def cancel_task(self, task_id: str) -> Task | None:
        task = self._tasks.get(task_id)
        if task:
            task.cancel()
        return task

    # ─── 查询 ─────────────────────────────────────────────────────────────────
    def get_task(self, task_id: str) -> Task | None:
        return self._tasks.get(task_id)

    def list_tasks(self, status: TaskStatus | None = None) -> list[Task]:
        tasks = list(self._tasks.values())
        if status:
            tasks = [t for t in tasks if t.status == status]
        return sorted(tasks, key=lambda t: (-t.priority.value, t.created_at))

    def pending_count(self) -> int:
        return sum(1 for t in self._tasks.values() if t.status == TaskStatus.PENDING)

    def running_count(self) -> int:
        return sum(1 for t in self._tasks.values() if t.status == TaskStatus.RUNNING)

    # ─── 钩子 ─────────────────────────────────────────────────────────────────
    def on(self, event: str, callback: Callable) -> None:
        if event in self._hooks:
            self._hooks[event].append(callback)

    def _fire(self, event: str, task: Task) -> None:
        for cb in self._hooks.get(event, []):
            try:
                cb(task)
            except Exception as e:
                logger.debug(f"[TaskManager] 钩子回调失败({event}): {e}")  # 钩子失败不影响主流程

    # ─── 统计 ─────────────────────────────────────────────────────────────────
    def stats(self) -> dict:
        all_tasks = list(self._tasks.values())
        return {
            "total": len(all_tasks),
            "pending": sum(1 for t in all_tasks if t.status == TaskStatus.PENDING),
            "running": sum(1 for t in all_tasks if t.status == TaskStatus.RUNNING),
            "completed": sum(1 for t in all_tasks if t.status == TaskStatus.COMPLETED),
            "failed": sum(1 for t in all_tasks if t.status == TaskStatus.FAILED),
        }

    def __repr__(self) -> str:
        return f"TaskManager(tasks={len(self._tasks)})"

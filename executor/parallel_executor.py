"""
ParallelSubAgentExecutor — 并行子Agent执行器
使用ThreadPoolExecutor并行执行多个子Agent任务
"""
from __future__ import annotations

import logging
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed, Future
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable

logger = logging.getLogger(__name__)

DEFAULT_MAX_WORKERS = 3
DEFAULT_TIMEOUT = 300


class SubAgentStatus(str, Enum):
    PENDING   = "pending"
    RUNNING   = "running"
    COMPLETED = "completed"
    FAILED    = "failed"


@dataclass
class SubAgentTask:
    """子Agent任务描述。"""
    task_id: str = field(default_factory=lambda: f"sub_{uuid.uuid4().hex[:6]}")
    name: str = ""
    func: Callable | None = None       # 实际执行函数
    args: tuple = field(default_factory=tuple)
    kwargs: dict = field(default_factory=dict)
    model: str = ""
    priority: int = 5
    status: SubAgentStatus = SubAgentStatus.PENDING
    metadata: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "task_id": self.task_id,
            "name": self.name,
            "model": self.model,
            "status": self.status.value,
        }


@dataclass
class ParallelResult:
    """并行执行结果。"""
    task_id: str
    name: str
    status: SubAgentStatus
    result: Any = None
    error: str | None = None
    duration_ms: float = 0.0

    @property
    def success(self) -> bool:
        return self.status == SubAgentStatus.COMPLETED


class ParallelSubAgentExecutor:
    """
    并行子Agent执行器。
    使用 ThreadPoolExecutor 并行执行多个子Agent任务。
    最大并行数可配置（默认3），支持超时控制。
    """

    def __init__(
        self,
        max_workers: int = DEFAULT_MAX_WORKERS,
        timeout: float = DEFAULT_TIMEOUT,
    ) -> None:
        self._max_workers = max_workers
        self._timeout = timeout
        self._total_executed = 0
        self._total_failed = 0

    def execute_parallel(self, tasks: list[SubAgentTask]) -> list[ParallelResult]:
        """
        并行执行一批子Agent任务。
        返回所有任务的结果列表（包含成功和失败）。
        """
        if not tasks:
            return []

        if len(tasks) == 1:
            # 单任务无需并行
            return [self._run_single(tasks[0])]

        logger.info(f"[ParallelExecutor] 并行执行 {len(tasks)} 个子任务 (workers={self._max_workers})")
        results: list[ParallelResult] = []
        future_to_task: dict[Future, SubAgentTask] = {}

        with ThreadPoolExecutor(max_workers=self._max_workers) as executor:
            for task in tasks:
                task.status = SubAgentStatus.RUNNING
                future = executor.submit(self._run_task, task)
                future_to_task[future] = task

            for future in as_completed(future_to_task, timeout=self._timeout):
                task = future_to_task[future]
                try:
                    result = future.result(timeout=1)
                    results.append(result)
                    self._total_executed += 1
                except Exception as e:
                    self._total_failed += 1
                    results.append(ParallelResult(
                        task_id=task.task_id,
                        name=task.name,
                        status=SubAgentStatus.FAILED,
                        error=str(e),
                    ))
                    logger.error(f"[ParallelExecutor] 子任务失败: {task.task_id} - {e}")

        logger.info(f"[ParallelExecutor] 完成: {len(results)} 个结果")
        return results

    def _run_single(self, task: SubAgentTask) -> ParallelResult:
        """运行单个任务（同步）。"""
        return self._run_task(task)

    def _run_task(self, task: SubAgentTask) -> ParallelResult:
        """执行单个子任务，捕获异常。"""
        t_start = time.perf_counter()
        try:
            if task.func:
                result = task.func(*task.args, **task.kwargs)
            else:
                # 没有实际函数时，返回占位结果（用于测试）
                result = f"[SubAgent:{task.model}] 处理任务: {task.name}"

            task.status = SubAgentStatus.COMPLETED
            duration_ms = (time.perf_counter() - t_start) * 1000
            return ParallelResult(
                task_id=task.task_id,
                name=task.name,
                status=SubAgentStatus.COMPLETED,
                result=result,
                duration_ms=duration_ms,
            )
        except Exception as e:
            task.status = SubAgentStatus.FAILED
            duration_ms = (time.perf_counter() - t_start) * 1000
            return ParallelResult(
                task_id=task.task_id,
                name=task.name,
                status=SubAgentStatus.FAILED,
                error=str(e),
                duration_ms=duration_ms,
            )

    def execute_with_aggregation(
        self,
        tasks: list[SubAgentTask],
        aggregate_func: Callable[[list[ParallelResult]], Any] | None = None,
    ) -> Any:
        """
        并行执行并聚合结果。
        aggregate_func 接受 ParallelResult 列表，返回聚合结果。
        """
        results = self.execute_parallel(tasks)
        if aggregate_func:
            return aggregate_func(results)
        # 默认聚合：拼接所有成功结果
        return "\n\n---\n\n".join(
            str(r.result) for r in results if r.success
        )

    def stats(self) -> dict:
        return {
            "max_workers": self._max_workers,
            "timeout_seconds": self._timeout,
            "total_executed": self._total_executed,
            "total_failed": self._total_failed,
        }

    def __repr__(self) -> str:
        return f"ParallelSubAgentExecutor(workers={self._max_workers})"

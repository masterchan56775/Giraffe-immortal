"""
WorkflowStep — 工作流步骤定义
"""
from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable

class StepStatus(str, Enum):
    PENDING   = "pending"
    RUNNING   = "running"
    COMPLETED = "completed"
    FAILED    = "failed"
    SKIPPED   = "skipped"

@dataclass
class WorkflowStep:
    """单个工作流步骤。"""
    name: str
    action: str
    executor: Callable | None = None
    args: dict = field(default_factory=dict)
    status: StepStatus = StepStatus.PENDING
    result: Any = None
    error: str | None = None
    depends_on: list[str] = field(default_factory=list)

    def run(self) -> Any:
        if not self.executor:
            raise ValueError(f"步骤 {self.name} 没有配置执行器")
        self.status = StepStatus.RUNNING
        try:
            self.result = self.executor(**self.args)
            self.status = StepStatus.COMPLETED
            return self.result
        except Exception as e:
            self.status = StepStatus.FAILED
            self.error = str(e)
            raise

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "action": self.action,
            "status": self.status.value,
            "error": self.error,
        }

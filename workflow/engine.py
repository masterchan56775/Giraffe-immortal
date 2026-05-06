"""
WorkflowEngine — 工作流引擎
支持暂停/恢复，状态持久化到磁盘
"""
from __future__ import annotations
import json, logging, uuid
from pathlib import Path
from typing import Any, Callable
from .step import WorkflowStep, StepStatus
logger = logging.getLogger(__name__)

class WorkflowEngine:
    """多步骤工作流引擎，支持暂停/恢复和断电续跑。"""

    def __init__(self, checkpoint_dir: Path | str | None = None) -> None:
        self._steps: list[WorkflowStep] = []
        self._action_registry: dict[str, Callable] = {}
        self._paused = False
        self._workflow_id = f"wf_{uuid.uuid4().hex[:6]}"
        self._checkpoint_dir = Path(checkpoint_dir) if checkpoint_dir else None

    def register(self, action: str, executor: Callable) -> None:
        """注册步骤执行器。"""
        self._action_registry[action] = executor

    def add_step(self, name: str, action: str, **kwargs) -> WorkflowStep:
        executor = self._action_registry.get(action)
        step = WorkflowStep(name=name, action=action, executor=executor, args=kwargs)
        self._steps.append(step)
        return step

    def run(self) -> dict:
        """按顺序执行所有步骤。"""
        results = {}
        for step in self._steps:
            if self._paused:
                logger.info(f"[Workflow] 暂停在步骤: {step.name}")
                break
            if step.status == StepStatus.COMPLETED:
                continue  # 断点续跑：跳过已完成步骤
            try:
                result = step.run()
                results[step.name] = result
                self._save_checkpoint()
            except Exception as e:
                logger.error(f"[Workflow] 步骤失败: {step.name} - {e}")
                break
        return results

    def pause(self) -> None:
        self._paused = True
        logger.info("[Workflow] 已暂停")

    def resume(self) -> dict:
        self._paused = False
        logger.info("[Workflow] 恢复运行")
        return self.run()

    def _save_checkpoint(self) -> None:
        if not self._checkpoint_dir:
            return
        self._checkpoint_dir.mkdir(parents=True, exist_ok=True)
        data = {
            "workflow_id": self._workflow_id,
            "steps": [s.to_dict() for s in self._steps],
        }
        path = self._checkpoint_dir / f"{self._workflow_id}.json"
        with open(path, "w", encoding="utf-8") as fp:
            json.dump(data, fp, ensure_ascii=False, indent=2)

    def stats(self) -> dict:
        return {
            "workflow_id": self._workflow_id,
            "total_steps": len(self._steps),
            "completed": sum(1 for s in self._steps if s.status == StepStatus.COMPLETED),
            "paused": self._paused,
        }

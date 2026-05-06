"""
swarm/agent.py — 智能体基类定义

定义 AgentProfile 数据类和 Agent 实例类。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from executor.pipeline import ExecutorPipeline


@dataclass
class AgentProfile:
    """
    智能体角色配置数据类。

    Fields:
        name: 角色名称（如 "architect", "coder", "reviewer"）
        system_prompt: 该角色专属的系统提示词
        model: 该角色默认使用的模型（空字符串表示使用全局默认）
        tools: 该角色可调用的 MCP 工具名列表
        temperature: 创造性偏好（reviewer 建议设低值）
        description: 角色简要说明
    """
    name: str
    system_prompt: str = ""
    model: str = ""
    tools: list[str] = field(default_factory=list)
    temperature: float = 0.7
    description: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "system_prompt": (
                self.system_prompt[:80] + "..."
                if len(self.system_prompt) > 80
                else self.system_prompt
            ),
            "model": self.model,
            "tools": self.tools,
            "temperature": self.temperature,
            "description": self.description,
        }

    def __repr__(self) -> str:
        return f"AgentProfile(name={self.name!r}, model={self.model!r})"


class Agent:
    """
    智能体实例。

    绑定 AgentProfile 配置和 ExecutorPipeline，以指定角色身份调用大模型。
    """

    def __init__(self, profile: AgentProfile, pipeline: "ExecutorPipeline") -> None:
        self._profile = profile
        self._pipeline = pipeline

    @property
    def name(self) -> str:
        return self._profile.name

    @property
    def profile(self) -> AgentProfile:
        return self._profile

    def think(self, message: str, context: list[dict]) -> str:
        """
        以该角色的身份调用大模型，返回该角色的发言。

        Args:
            message: 当前任务或问题描述
            context: 消息历史上下文（含前序角色的发言）

        Returns:
            该角色的响应文本
        """
        from executor.pipeline import ExecutionContext

        # 构建消息列表：系统提示 + 上下文历史 + 当前消息
        messages = []
        if context:
            messages.extend(context)

        ctx = ExecutionContext(
            message=message,
            model=self._profile.model or "default",
            task_type="swarm_task",
            messages=messages,
            system_prompt=self._profile.system_prompt,
            temperature=self._profile.temperature,
        )

        result = self._pipeline.execute(ctx)
        return result.response if result.success else f"[{self.name}] 执行失败: {result.error}"

    def __repr__(self) -> str:
        return f"Agent({self._profile.name})"

"""
swarm/orchestrator.py — Swarm 群组讨论编排器

多个 Agent 在同一个任务上轮流发言、协作讨论，
直到达成共识（Reviewer 输出 APPROVED）或达到最大轮次。
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field


logger = logging.getLogger(__name__)


@dataclass
class SwarmResult:
    """Swarm 执行结果。"""
    success: bool
    final_output: str
    discussion: list[dict] = field(default_factory=list)  # 完整讨论记录
    rounds: int = 0
    duration_ms: float = 0.0
    termination_reason: str = ""   # "approved" | "max_rounds" | "error"
    agent_stats: dict[str, int] = field(default_factory=dict)  # {agent_name: turn_count}

    def to_dict(self) -> dict:
        return {
            "success": self.success,
            "final_output": self.final_output[:200] + "..." if len(self.final_output) > 200 else self.final_output,
            "rounds": self.rounds,
            "duration_ms": round(self.duration_ms, 2),
            "termination_reason": self.termination_reason,
            "agent_stats": self.agent_stats,
        }


class SwarmOrchestrator:
    """
    群组讨论协调器。

    执行流程：
    1. 第一个角色（通常是 Architect）接收任务并提出方案
    2. 将前序角色的发言作为上下文传给下一个角色
    3. 循环执行，直到 Reviewer 输出 APPROVED 或达到 max_rounds
    4. 每轮通过 EventBus 发布 swarm_turn 事件供前端实时展示

    Args:
        agents: 参与讨论的 Agent 列表（按发言顺序排列）
        max_rounds: 最大讨论轮次
    """

    def __init__(self, agents: list[Agent], max_rounds: int = 5) -> None:
        self._agents = agents
        self._max_rounds = max_rounds

    @property
    def agent_count(self) -> int:
        return len(self._agents)

    def run(self, task: str) -> SwarmResult:
        """
        核心编排逻辑。

        Args:
            task: 任务描述（发送给第一个 Agent）

        Returns:
            SwarmResult
        """
        t_start = time.perf_counter()

        # 尝试导入 EventBus（可选依赖）
        try:
            from integration.event_stream import EventBus
            event_bus = EventBus.get()
        except ImportError:
            event_bus = None

        discussion: list[dict] = []
        agent_stats: dict[str, int] = {a.name: 0 for a in self._agents}
        round_num = 0
        termination_reason = "max_rounds"
        final_output = ""

        logger.info(
            f"[Swarm] 开始群组讨论: task={task[:50]!r}, "
            f"agents={[a.name for a in self._agents]}, max_rounds={self._max_rounds}"
        )

        while round_num < self._max_rounds:
            round_num += 1
            logger.info(f"[Swarm] 第 {round_num} 轮")

            for agent in self._agents:
                # 将历史讨论作为上下文（仅取最近 10 条）
                context = [
                    {"role": m["role"], "content": m["content"]}
                    for m in discussion[-10:]
                ]

                # 第一个 Agent 的第一轮直接接受任务
                current_message = task if not discussion else (
                    f"【任务】{task}\n\n"
                    f"【上一位发言者】{discussion[-1]['name']}\n"
                    f"【内容摘要】{discussion[-1]['content'][:200]}\n\n"
                    f"请基于以上内容继续你的工作。"
                )

                # 发布事件
                if event_bus:
                    event_bus.emit(
                        "swarm_turn",
                        agent=agent.name,
                        round=round_num,
                        task=task[:50],
                    )

                # 调用 Agent
                response = agent.think(current_message, context)
                final_output = response

                # 记录讨论
                turn_record = {
                    "round": round_num,
                    "name": agent.name,
                    "role": "assistant",
                    "content": response,
                    "timestamp": time.time(),
                }
                discussion.append(turn_record)
                agent_stats[agent.name] = agent_stats.get(agent.name, 0) + 1

                logger.info(
                    f"[Swarm] {agent.name} 发言 (round={round_num}): "
                    f"{response[:80]}..."
                )

                # 发布完成事件
                if event_bus:
                    event_bus.emit(
                        "swarm_turn_done",
                        agent=agent.name,
                        round=round_num,
                        response_preview=response[:100],
                    )

                # 检查终止条件
                if self._check_termination(discussion):
                    termination_reason = "approved"
                    logger.info(f"[Swarm] Reviewer 批准，终止讨论 (round={round_num})")
                    break

            if termination_reason == "approved":
                break

        duration_ms = (time.perf_counter() - t_start) * 1000

        logger.info(
            f"[Swarm] 讨论结束: rounds={round_num}, "
            f"reason={termination_reason}, {duration_ms:.1f}ms"
        )

        return SwarmResult(
            success=True,
            final_output=final_output,
            discussion=discussion,
            rounds=round_num,
            duration_ms=duration_ms,
            termination_reason=termination_reason,
            agent_stats=agent_stats,
        )

    def _check_termination(self, messages: list[dict]) -> bool:
        """
        终止条件检查：最近一条消息包含 'APPROVED' 关键词。
        """
        if not messages:
            return False
        last = messages[-1]
        return "APPROVED" in last.get("content", "").upper()

"""
graph/nodes/swarm_node.py — Swarm 集群节点

在 DAG 图中将 SwarmOrchestrator 封装为单个可插拔节点。
当 GraphEngine 执行到此节点时，自动启动多角色讨论。
"""
from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING

from graph.node import Node
from graph.state import GraphState

if TYPE_CHECKING:
    from swarm.orchestrator import SwarmOrchestrator

logger = logging.getLogger(__name__)


class SwarmNode(Node):
    """
    Swarm 集群节点。

    在图中作为一个整体节点，内部委托给 SwarmOrchestrator.run()。
    输入：state["message"]
    输出：state["response"] = SwarmResult.final_output
    """

    name = "swarm"

    def __init__(self, orchestrator: "SwarmOrchestrator") -> None:
        self._orchestrator = orchestrator

    def run(self, state: GraphState) -> GraphState:
        t = time.perf_counter()
        task = state.get("message", "")

        logger.info(f"[SwarmNode] 启动多角色讨论: {task[:50]}")

        try:
            result = self._orchestrator.run(task)
            state["response"] = result.final_output
            state["error"] = None

            # 将讨论历史写入 stage_times 作为元数据
            if "stage_times" not in state:
                state["stage_times"] = {}
            state["stage_times"]["swarm"] = round(result.duration_ms, 2)

            logger.info(
                f"[SwarmNode] 讨论完成: rounds={result.rounds}, "
                f"reason={result.termination_reason}"
            )
        except Exception as e:
            logger.error(f"[SwarmNode] 执行失败: {e}")
            state["error"] = str(e)
            state["response"] = ""

        self._record(state, "swarm", t)
        return state

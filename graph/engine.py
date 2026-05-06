"""
graph/engine.py — DAG 图执行引擎

功能：
- 注册节点（add_node）
- 添加无条件边（add_edge）
- 添加条件边（add_conditional_edge）
- 设置入口/出口节点
- 按图结构执行（run）
- 检查点持久化（每节点后自动保存）
- 从检查点恢复（resume）
- 状态回滚（rollback）
"""
from __future__ import annotations

import logging
import time
import uuid
from typing import Callable

from .node import Node
from .state import GraphState
from .checkpoint import CheckpointStore

logger = logging.getLogger(__name__)

_FINISH_SENTINEL = "__FINISH__"


class GraphEngine:
    """
    有向图执行引擎。

    支持：
    - 无条件边：add_edge(from, to)
    - 条件边：add_conditional_edge(from, condition_fn, {result: next_node})
    - 入口/出口节点
    - 基于 CheckpointStore 的断点续跑和回滚
    """

    def __init__(
        self,
        checkpoint_store: CheckpointStore | None = None,
    ) -> None:
        self._nodes: dict[str, Node] = {}
        self._edges: dict[str, str] = {}                          # 无条件边 from→to
        self._cond_edges: dict[str, tuple[Callable, dict]] = {}   # 条件边
        self._entry: str | None = None
        self._finish: str | None = None
        self._checkpoint_store = checkpoint_store

    # ─── 构建图 ───────────────────────────────────────────────────────────────
    def add_node(self, node: Node) -> None:
        """注册一个节点。"""
        self._nodes[node.name] = node

    def add_edge(self, from_node: str, to_node: str) -> None:
        """
        添加无条件边：from_node 执行完后无条件跳转到 to_node。
        使用 "__FINISH__" 作为 to_node 表示终止。
        """
        self._edges[from_node] = to_node

    def add_conditional_edge(
        self,
        from_node: str,
        condition: Callable[[GraphState], str],
        mapping: dict[str, str],
    ) -> None:
        """
        添加条件边。

        Args:
            from_node: 触发条件判断的节点名
            condition: 接收 GraphState，返回字符串 key
            mapping: key → next_node_name（或 "__FINISH__"）

        示例：
            engine.add_conditional_edge(
                "api_call",
                lambda s: "error" if s.get("error") else "ok",
                {"error": "self_heal", "ok": "deep_compact"},
            )
        """
        self._cond_edges[from_node] = (condition, mapping)

    def set_entry(self, node_name: str) -> None:
        """设置入口节点。"""
        self._entry = node_name

    def set_finish(self, node_name: str) -> None:
        """设置结束节点（执行完后终止）。"""
        self._finish = node_name

    # ─── 执行 ─────────────────────────────────────────────────────────────────
    def run(
        self,
        initial_state: GraphState | None = None,
        trace_id: str | None = None,
        start_node: str | None = None,
    ) -> GraphState:
        """
        从入口节点开始执行，按边定义逐节点运行，直到到达结束节点或无后继节点。

        Args:
            initial_state: 初始状态
            trace_id: 本次执行的唯一标识（用于 checkpoint）
            start_node: 指定从哪个节点开始（用于 resume）

        Returns:
            最终 GraphState
        """
        state: GraphState = dict(initial_state or {})
        trace_id = trace_id or f"trace_{uuid.uuid4().hex[:8]}"
        step_index = 0

        current = start_node or self._entry
        if current is None:
            raise ValueError("[GraphEngine] 未设置入口节点，请调用 set_entry()")

        t_total = time.perf_counter()
        logger.info(f"[GraphEngine] 开始执行 trace={trace_id}, entry={current}")

        visited_counts: dict[str, int] = {}

        while current and current != _FINISH_SENTINEL:
            node = self._nodes.get(current)
            if node is None:
                logger.error(f"[GraphEngine] 未注册的节点: {current}")
                break

            # 防止无限循环（同一节点最多执行 5 次）
            visited_counts[current] = visited_counts.get(current, 0) + 1
            if visited_counts[current] > 5:
                logger.warning(f"[GraphEngine] 检测到潜在循环，强制终止: {current}")
                break

            logger.debug(f"[GraphEngine] 执行节点: {current} (step={step_index})")
            try:
                state = node.run(state)
            except Exception as e:
                logger.error(f"[GraphEngine] 节点 {current} 执行异常: {e}")
                state["error"] = str(e)

            # 保存检查点
            if self._checkpoint_store:
                self._checkpoint_store.save(
                    trace_id=trace_id,
                    node_name=current,
                    step_index=step_index,
                    state=state,
                )

            step_index += 1

            # 确定下一个节点（条件边优先）
            if current in self._cond_edges:
                condition_fn, mapping = self._cond_edges[current]
                try:
                    result_key = condition_fn(state)
                except Exception as e:
                    logger.warning(f"[GraphEngine] 条件函数异常 ({current}): {e}")
                    result_key = list(mapping.keys())[0]
                current = mapping.get(result_key, _FINISH_SENTINEL)
            elif current in self._edges:
                current = self._edges[current]
            elif current == self._finish:
                break
            else:
                # 无后继节点，自然结束
                break

        total_ms = (time.perf_counter() - t_total) * 1000
        logger.info(f"[GraphEngine] 执行完成: {step_index} 步, {total_ms:.1f}ms, trace={trace_id}")
        return state

    # ─── 断点恢复 ─────────────────────────────────────────────────────────────
    def resume(self, trace_id: str) -> GraphState:
        """
        从最新检查点恢复执行。

        Args:
            trace_id: 之前执行的 trace ID

        Returns:
            最终 GraphState

        Raises:
            ValueError: 未找到检查点
        """
        if not self._checkpoint_store:
            raise ValueError("[GraphEngine] 未配置 CheckpointStore")

        result = self._checkpoint_store.load_latest(trace_id)
        if result is None:
            raise ValueError(f"[GraphEngine] 未找到 trace_id={trace_id} 的检查点")

        last_node, state = result

        # 从上次执行的节点的「下一个节点」开始
        next_node = self._edges.get(last_node, self._finish or _FINISH_SENTINEL)
        if last_node in self._cond_edges:
            condition_fn, mapping = self._cond_edges[last_node]
            try:
                result_key = condition_fn(state)
                next_node = mapping.get(result_key, _FINISH_SENTINEL)
            except Exception:
                pass

        logger.info(f"[GraphEngine] 从断点恢复: last={last_node}, next={next_node}, trace={trace_id}")
        return self.run(initial_state=state, trace_id=trace_id, start_node=next_node)

    def rollback(self, trace_id: str, step_index: int) -> GraphState:
        """
        回滚到指定步骤后重新执行。

        Args:
            trace_id: 执行标识
            step_index: 要回滚到的步骤编号

        Returns:
            从该步骤重新执行后的最终 GraphState
        """
        if not self._checkpoint_store:
            raise ValueError("[GraphEngine] 未配置 CheckpointStore")

        state = self._checkpoint_store.load_at_step(trace_id, step_index)
        if state is None:
            raise ValueError(
                f"[GraphEngine] 未找到 trace_id={trace_id} step={step_index} 的检查点"
            )

        checkpoints = self._checkpoint_store.list_checkpoints(trace_id)
        node_at_step = next(
            (c["node_name"] for c in checkpoints if c["step_index"] == step_index),
            None,
        )

        logger.info(f"[GraphEngine] 回滚到步骤 {step_index} ({node_at_step})")
        return self.run(initial_state=state, trace_id=trace_id, start_node=node_at_step)

    # ─── 统计 ─────────────────────────────────────────────────────────────────
    @property
    def node_names(self) -> list[str]:
        return list(self._nodes.keys())

    def get_node(self, name: str) -> Node | None:
        return self._nodes.get(name)

    def __repr__(self) -> str:
        return f"GraphEngine(nodes={len(self._nodes)}, entry={self._entry})"

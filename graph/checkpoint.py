"""
graph/checkpoint.py — 节点状态持久化（Checkpointing）

基于 SQLite 的 GraphState 快照存储，支持断点续跑和回滚。
"""
from __future__ import annotations

import json
import logging
import sqlite3
import time
from pathlib import Path
from typing import Any

from .state import GraphState

logger = logging.getLogger(__name__)


class CheckpointStore:
    """
    基于 SQLite 的图执行状态快照存储。

    表结构：
        checkpoints(trace_id TEXT, node_name TEXT, step_index INT,
                    state_json TEXT, created_at REAL)

    使用方式：
        store = CheckpointStore(db_path=data_dir / "graph_checkpoints.db")
        store.save(trace_id="abc", node_name="api_call", step_index=4, state=state)
        trace_id, state = store.load_latest("abc")
    """

    def __init__(self, db_path: Path | str) -> None:
        self._db_path = Path(db_path)
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _init_db(self) -> None:
        with sqlite3.connect(str(self._db_path)) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS checkpoints (
                    trace_id    TEXT    NOT NULL,
                    node_name   TEXT    NOT NULL,
                    step_index  INTEGER NOT NULL,
                    state_json  TEXT    NOT NULL,
                    created_at  REAL    NOT NULL,
                    PRIMARY KEY (trace_id, step_index)
                )
            """)
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_trace ON checkpoints(trace_id, step_index)"
            )
            conn.commit()

    # ─── 写入 ─────────────────────────────────────────────────────────────────
    def save(
        self,
        trace_id: str,
        node_name: str,
        step_index: int,
        state: GraphState,
    ) -> None:
        """保存节点执行后的状态快照。"""
        try:
            # 过滤不可序列化的对象
            safe_state = _make_serializable(dict(state))
            state_json = json.dumps(safe_state, ensure_ascii=False)

            with sqlite3.connect(str(self._db_path)) as conn:
                conn.execute(
                    """
                    INSERT OR REPLACE INTO checkpoints
                        (trace_id, node_name, step_index, state_json, created_at)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (trace_id, node_name, step_index, state_json, time.time()),
                )
                conn.commit()
        except Exception as e:
            logger.warning(f"[CheckpointStore] 保存失败 ({node_name}@{step_index}): {e}")

    # ─── 读取 ─────────────────────────────────────────────────────────────────
    def load_latest(self, trace_id: str) -> tuple[str, GraphState] | None:
        """
        加载指定 trace 的最新检查点。

        Returns:
            (node_name, GraphState) 或 None（无记录）
        """
        with sqlite3.connect(str(self._db_path)) as conn:
            row = conn.execute(
                """
                SELECT node_name, state_json FROM checkpoints
                WHERE trace_id = ?
                ORDER BY step_index DESC LIMIT 1
                """,
                (trace_id,),
            ).fetchone()

        if not row:
            return None
        node_name, state_json = row
        return node_name, json.loads(state_json)

    def load_at_step(self, trace_id: str, step_index: int) -> GraphState | None:
        """
        加载指定步骤的状态快照（用于回滚）。

        Returns:
            GraphState 或 None
        """
        with sqlite3.connect(str(self._db_path)) as conn:
            row = conn.execute(
                "SELECT state_json FROM checkpoints WHERE trace_id = ? AND step_index = ?",
                (trace_id, step_index),
            ).fetchone()

        if not row:
            return None
        return json.loads(row[0])

    def list_checkpoints(self, trace_id: str) -> list[dict]:
        """
        列出某次执行的全部检查点。

        Returns:
            [{"node_name": ..., "step_index": ..., "created_at": ...}, ...]
        """
        with sqlite3.connect(str(self._db_path)) as conn:
            rows = conn.execute(
                """
                SELECT node_name, step_index, created_at FROM checkpoints
                WHERE trace_id = ?
                ORDER BY step_index ASC
                """,
                (trace_id,),
            ).fetchall()

        return [
            {"node_name": row[0], "step_index": row[1], "created_at": row[2]}
            for row in rows
        ]

    def delete_trace(self, trace_id: str) -> int:
        """删除某次执行的所有检查点，返回删除的行数。"""
        with sqlite3.connect(str(self._db_path)) as conn:
            cur = conn.execute("DELETE FROM checkpoints WHERE trace_id = ?", (trace_id,))
            conn.commit()
            return cur.rowcount


def _make_serializable(obj: Any) -> Any:
    """递归将不可 JSON 序列化的对象转为可序列化形式。"""
    if isinstance(obj, dict):
        return {k: _make_serializable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_make_serializable(v) for v in obj]
    if isinstance(obj, (str, int, float, bool)) or obj is None:
        return obj
    # 尝试调用 to_dict()
    if hasattr(obj, "to_dict"):
        return _make_serializable(obj.to_dict())
    # 最后兜底：转字符串
    return str(obj)

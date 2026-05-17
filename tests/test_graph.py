"""
tests/test_graph.py — 阶段三：DAG 图计算引擎完整测试

涵盖：
- GraphState 类型结构
- 各具体 Node 子类行为
- GraphEngine 图执行、条件边、反循环防护
- CheckpointStore SQLite 持久化
- GraphEngine.resume() 断点恢复
"""
import pytest
import tempfile
import os
from pathlib import Path

from graph.state import GraphState
from graph.node import Node, DecomposeNode, ApprovalNode, MicroCompactNode, DeepCompactNode, CacheNode
from graph.engine import GraphEngine
from graph.checkpoint import CheckpointStore


# ─── GraphState 测试 ──────────────────────────────────────────────────────────
class TestGraphState:
    def test_is_dict_compatible(self):
        state: GraphState = {"message": "hello", "model": "gpt"}
        assert state["message"] == "hello"
        assert state["model"] == "gpt"

    def test_partial_fields(self):
        state: GraphState = {}
        state["response"] = "hi"
        state["error"] = None
        assert state.get("retry_count", 0) == 0


# ─── 具体 Node 子类测试 ───────────────────────────────────────────────────────
class MockDecomposer:
    class _Result:
        def __init__(self, is_complex=False):
            self.is_complex = is_complex
            self.subtasks = []
    def decompose(self, msg, task_type):
        return self._Result()


class MockMicro:
    def compact(self, msgs):
        return msgs[-3:] if len(msgs) > 3 else msgs


class MockDeep:
    def check_and_compact(self, msgs):
        return msgs


class MockCache:
    def __init__(self):
        self._store = {}
    def check_and_store(self, msg, resp, model):
        self._store[(msg, model)] = resp
    def get(self, msg, model):
        return self._store.get((msg, model))


class MockApproval:
    def __init__(self, approved=True):
        self.approved = approved
    def approve(self, task_type, msg):
        return self.approved, "ok" if self.approved else "rejected"


class TestDecomposeNode:
    def test_simple_task(self):
        node = DecomposeNode(MockDecomposer())
        state: GraphState = {"message": "hello", "task_type": "chat"}
        result = node.run(state)
        assert result["decomposed"] is None
        assert "decompose" in result["stage_times"]

    def test_stage_recorded(self):
        node = DecomposeNode(MockDecomposer())
        state: GraphState = {"message": "x", "task_type": "chat"}
        state = node.run(state)
        assert "decompose" in state.get("stage_history", [])


class TestApprovalNode:
    def test_approved(self):
        node = ApprovalNode(MockApproval(True))
        state: GraphState = {"task_type": "chat", "message": "hello"}
        state = node.run(state)
        assert state["approved"] is True

    def test_rejected(self):
        node = ApprovalNode(MockApproval(False))
        state: GraphState = {"task_type": "chat", "message": "hello"}
        state = node.run(state)
        assert state["approved"] is False

    def test_no_approval_system(self):
        node = ApprovalNode(None)
        state: GraphState = {"task_type": "chat", "message": "hello"}
        state = node.run(state)
        assert state["approved"] is True


class TestMicroCompactNode:
    def test_compacts_messages(self):
        node = MicroCompactNode(MockMicro())
        state: GraphState = {
            "messages": [{"role": "user", "content": f"msg {i}"} for i in range(5)]
        }
        state = node.run(state)
        assert len(state["messages"]) == 3

    def test_empty_messages(self):
        node = MicroCompactNode(MockMicro())
        state: GraphState = {"messages": []}
        state = node.run(state)
        assert state["messages"] == []


class TestCacheNode:
    def test_stores_response(self):
        cache = MockCache()
        node = CacheNode(cache)
        state: GraphState = {
            "message": "q",
            "response": "answer",
            "cache_hit": False,
            "error": None,
            "model": "m1",
        }
        node.run(state)
        assert cache.get("q", "m1") == "answer"

    def test_skips_if_cache_hit(self):
        cache = MockCache()
        node = CacheNode(cache)
        state: GraphState = {
            "message": "q",
            "response": "answer",
            "cache_hit": True,
            "error": None,
            "model": "m1",
        }
        node.run(state)
        assert cache.get("q", "m1") is None

    def test_skips_if_error(self):
        cache = MockCache()
        node = CacheNode(cache)
        state: GraphState = {
            "message": "q",
            "response": "answer",
            "cache_hit": False,
            "error": "some error",
            "model": "m1",
        }
        node.run(state)
        assert cache.get("q", "m1") is None


# ─── GraphEngine 测试 ────────────────────────────────────────────────────────

class _IncrNode(Node):
    """测试用节点，将 state["count"] 加 n。"""
    def __init__(self, name_, n=1):
        self._name = name_
        self._n = n

    @property
    def name(self):
        return self._name

    def run(self, state):
        state["count"] = state.get("count", 0) + self._n
        return state


class TestGraphEngine:
    def test_simple_linear_run(self):
        engine = GraphEngine()
        engine.add_node(_IncrNode("a", 1))
        engine.add_node(_IncrNode("b", 10))
        engine.add_edge("a", "b")
        engine.set_entry("a")
        engine.set_finish("b")

        state = engine.run({"count": 0})
        assert state["count"] == 11

    def test_conditional_edge(self):
        engine = GraphEngine()
        engine.add_node(_IncrNode("start", 5))
        engine.add_node(_IncrNode("high", 100))
        engine.add_node(_IncrNode("low", 1))

        engine.add_conditional_edge(
            "start",
            lambda s: "high" if s.get("count", 0) >= 5 else "low",
            {"high": "high", "low": "low"},
        )
        engine.set_entry("start")
        engine.set_finish("high")

        state = engine.run({"count": 0})
        assert state["count"] == 105  # 5 + 100

    def test_finish_sentinel_stops_execution(self):
        engine = GraphEngine()
        engine.add_node(_IncrNode("a", 1))
        engine.add_edge("a", "__FINISH__")
        engine.set_entry("a")

        state = engine.run({"count": 0})
        assert state["count"] == 1

    def test_anti_cycle_protection(self):
        """同一节点执行超过5次时，引擎应强制终止而不是死循环。"""
        class InfiniteNode(Node):
            name = "loop"
            def run(self, s):
                return s

        engine = GraphEngine()
        engine.add_node(InfiniteNode())
        engine.add_edge("loop", "loop")
        engine.set_entry("loop")

        # 不应无限循环
        state = engine.run({})
        assert state is not None

    def test_node_exception_is_caught(self):
        class FailNode(Node):
            name = "fail"
            def run(self, s):
                raise RuntimeError("kaboom")

        engine = GraphEngine()
        engine.add_node(FailNode())
        engine.set_entry("fail")

        state = engine.run({})
        assert state.get("error") == "kaboom"


# ─── CheckpointStore 测试 ─────────────────────────────────────────────────────
class TestCheckpointStore:
    def test_save_and_load_latest(self, tmp_path):
        store = CheckpointStore(tmp_path / "ckpt.db")
        state: GraphState = {"message": "hello", "response": "world"}

        store.save("trace1", "api_call", 3, state)
        result = store.load_latest("trace1")

        assert result is not None
        node_name, loaded = result
        assert node_name == "api_call"
        assert loaded["message"] == "hello"

    def test_load_at_step(self, tmp_path):
        store = CheckpointStore(tmp_path / "ckpt.db")

        store.save("t1", "node_a", 0, {"step": 0})
        store.save("t1", "node_b", 1, {"step": 1})
        store.save("t1", "node_c", 2, {"step": 2})

        state = store.load_at_step("t1", 1)
        assert state is not None
        assert state["step"] == 1

    def test_list_checkpoints(self, tmp_path):
        store = CheckpointStore(tmp_path / "ckpt.db")
        for i in range(3):
            store.save("trace2", f"node_{i}", i, {"i": i})

        records = store.list_checkpoints("trace2")
        assert len(records) == 3
        assert records[0]["node_name"] == "node_0"
        assert records[-1]["node_name"] == "node_2"

    def test_load_latest_no_record(self, tmp_path):
        store = CheckpointStore(tmp_path / "ckpt.db")
        assert store.load_latest("nonexistent") is None

    def test_delete_trace(self, tmp_path):
        store = CheckpointStore(tmp_path / "ckpt.db")
        store.save("del_trace", "n", 0, {"x": 1})
        deleted = store.delete_trace("del_trace")
        assert deleted == 1
        assert store.load_latest("del_trace") is None

    def test_unserializable_state(self, tmp_path):
        """不可序列化的对象应被安全处理（转字符串）。"""
        store = CheckpointStore(tmp_path / "ckpt.db")

        class WeirdObj:
            def __str__(self): return "<WeirdObj>"

        state = {"obj": WeirdObj(), "normal": 42}
        # 不应抛异常
        store.save("t_weird", "n", 0, state)
        result = store.load_latest("t_weird")
        assert result is not None
        _, loaded = result
        assert loaded["normal"] == 42


# ─── GraphEngine + Checkpoint 集成 ───────────────────────────────────────────
class TestGraphEngineCheckpoint:
    def test_run_saves_checkpoints(self, tmp_path):
        store = CheckpointStore(tmp_path / "ckpt.db")
        engine = GraphEngine(checkpoint_store=store)
        engine.add_node(_IncrNode("a", 1))
        engine.add_node(_IncrNode("b", 2))
        engine.add_edge("a", "b")
        engine.set_entry("a")
        engine.set_finish("b")

        engine.run({"count": 0}, trace_id="test_trace")

        records = store.list_checkpoints("test_trace")
        assert len(records) == 2

    def test_resume_continues_from_checkpoint(self, tmp_path):
        store = CheckpointStore(tmp_path / "ckpt.db")

        # 模拟已运行到 "a" 节点后的状态
        store.save("resume_trace", "a", 0, {"count": 10})

        engine = GraphEngine(checkpoint_store=store)
        engine.add_node(_IncrNode("b", 5))
        engine.add_edge("b", "__FINISH__")
        engine.set_entry("b")
        engine.set_finish("b")

        state = engine.resume("resume_trace")
        assert state["count"] == 15  # 10 (from checkpoint) + 5 (b node)

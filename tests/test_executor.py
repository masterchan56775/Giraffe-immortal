"""
tests/test_executor.py — 执行管道测试
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest
from executor.circuit_breaker import CircuitBreaker, CircuitState, CircuitOpenError
from executor.micro_compact import MicroCompact
from executor.deep_compact import DeepCompact
from executor.response_cache import ResponseCache
from executor.task_decomposer import TaskDecomposer
from executor.parallel_executor import ParallelSubAgentExecutor, SubAgentTask


class TestCircuitBreaker:
    def setup_method(self):
        self.cb = CircuitBreaker(name="test", failure_threshold=3, cooldown_seconds=0.1)

    def test_initial_state_closed(self):
        assert self.cb.state == CircuitState.CLOSED

    def test_opens_after_threshold(self):
        for _ in range(3):
            self.cb.record_failure()
        assert self.cb.state == CircuitState.OPEN

    def test_success_resets_failure_count(self):
        self.cb.record_failure()
        self.cb.record_failure()
        self.cb.record_success()
        assert self.cb.failure_count == 0

    def test_call_raises_when_open(self):
        for _ in range(3):
            self.cb.record_failure()
        with pytest.raises(CircuitOpenError):
            self.cb.call(lambda: None)

    def test_recovers_after_cooldown(self):
        import time
        for _ in range(3):
            self.cb.record_failure()
        time.sleep(0.2)
        assert self.cb.state == CircuitState.HALF_OPEN


class TestMicroCompact:
    def setup_method(self):
        self.mc = MicroCompact(threshold=50)

    def test_short_message_not_compacted(self):
        msgs = [{"role": "user", "content": "你好"}]
        result = self.mc.compact(msgs)
        assert result[0]["content"] == "你好"

    def test_long_message_compacted(self):
        long_content = "a" * 200
        msgs = [{"role": "user", "content": long_content}]
        result = self.mc.compact(msgs)
        assert len(result[0]["content"]) < len(long_content)
        assert "已压缩" in result[0]["content"]

    def test_system_message_not_compacted(self):
        system_content = "s" * 200
        msgs = [{"role": "system", "content": system_content}]
        result = self.mc.compact(msgs)
        assert result[0]["content"] == system_content


class TestDeepCompact:
    def setup_method(self):
        self.dc = DeepCompact(threshold=5, keep_recent=2)

    def test_below_threshold_not_compacted(self):
        msgs = [{"role": "user", "content": f"msg{i}"} for i in range(3)]
        result = self.dc.check_and_compact(msgs)
        assert result == msgs

    def test_above_threshold_compacted(self):
        msgs = [{"role": "user", "content": f"msg{i}"} for i in range(10)]
        result = self.dc.check_and_compact(msgs)
        assert len(result) < len(msgs)

    def test_recent_messages_preserved(self):
        msgs = [{"role": "user", "content": f"msg{i}"} for i in range(10)]
        result = self.dc.check_and_compact(msgs)
        last_contents = [m["content"] for m in result[-2:]]
        assert "msg8" in last_contents
        assert "msg9" in last_contents


class TestResponseCache:
    def setup_method(self):
        self.cache = ResponseCache(ttl=60)

    def test_miss_returns_none(self):
        assert self.cache.get("test query") is None

    def test_set_and_get(self):
        self.cache.set("hello", "world response")
        assert self.cache.get("hello") == "world response"

    def test_model_scope(self):
        self.cache.set("query", "response_a", model="model-a")
        self.cache.set("query", "response_b", model="model-b")
        assert self.cache.get("query", model="model-a") == "response_a"
        assert self.cache.get("query", model="model-b") == "response_b"

    def test_hit_rate(self):
        self.cache.set("q", "r")
        self.cache.get("q")
        self.cache.get("nonexistent")
        assert 0 < self.cache.hit_rate < 1


class TestTaskDecomposer:
    def setup_method(self):
        self.td = TaskDecomposer()

    def test_single_task_not_decomposed(self):
        result = self.td.decompose("帮我写一个函数")
        assert result.is_single
        assert not result.is_complex

    def test_multi_step_detected(self):
        msg = "第一步：分析需求\n第二步：设计架构\n第三步：实现代码"
        result = self.td.decompose(msg)
        assert result.is_complex or len(result.subtasks) >= 1

    def test_none_message_raises_type_error(self):
        """None 输入必须抛出明确的 TypeError，包含清晰错误信息。"""
        with pytest.raises(TypeError, match="message 必须是字符串"):
            self.td.decompose(None)

    def test_integer_message_raises_type_error(self):
        """整数输入应抛 TypeError，不是 AttributeError 或 TypeError 含义模糊。"""
        with pytest.raises(TypeError, match="message 必须是 str"):
            self.td.decompose(123)

    def test_empty_string_returns_single_task(self):
        """空字符串不触发分解，返回单任务。"""
        result = self.td.decompose("")
        assert not result.is_complex
        assert len(result.subtasks) == 1

    def test_whitespace_only_returns_single_task(self):
        """纯空白字符串也不触发分解。"""
        result = self.td.decompose("   \t\n")
        assert not result.is_complex


class TestExecutionContextValidation:
    """ExecutionContext 构造时的输入验证测试。"""

    def test_none_message_raises(self):
        """message=None 应在 dataclass 初始化时即抛异常，而非在后续阶段以AttributeError崩溃。"""
        from executor.pipeline import ExecutionContext
        with pytest.raises((ValueError, TypeError)):
            ExecutionContext(message=None, model="test-model")

    def test_empty_model_raises(self):
        """model='' 应抛 ValueError，给出明确提示。"""
        from executor.pipeline import ExecutionContext
        with pytest.raises(ValueError, match="model"):
            ExecutionContext(message="hello", model="")

    def test_none_model_raises(self):
        """model=None 应抛 ValueError。"""
        from executor.pipeline import ExecutionContext
        with pytest.raises(ValueError, match="model"):
            ExecutionContext(message="hello", model=None)

    def test_valid_context_ok(self):
        """有效入参不应抛任何异常。"""
        from executor.pipeline import ExecutionContext
        ctx = ExecutionContext(message="hello world", model="mimo-v2.5")
        assert ctx.message == "hello world"
        assert ctx.model == "mimo-v2.5"
        assert ctx.task_type == "chat"
        assert ctx.approved is True


class TestParallelExecutor:
    def setup_method(self):
        self.executor = ParallelSubAgentExecutor(max_workers=2)

    def test_empty_tasks(self):
        assert self.executor.execute_parallel([]) == []

    def test_single_task(self):
        task = SubAgentTask(name="test", func=lambda: "ok")
        results = self.executor.execute_parallel([task])
        assert len(results) == 1
        assert results[0].success
        assert results[0].result == "ok"

    def test_multiple_tasks_parallel(self):
        tasks = [
            SubAgentTask(name=f"task{i}", func=lambda i=i: f"result_{i}")
            for i in range(3)
        ]
        results = self.executor.execute_parallel(tasks)
        assert len(results) == 3
        assert all(r.success for r in results)

    def test_failed_task_captured(self):
        """失败任务应被捕获为 FAILED 状态，不影响其他任务。"""
        def failing():
            raise ValueError("test error")
        task = SubAgentTask(name="failing", func=failing)
        results = self.executor.execute_parallel([task])
        assert len(results) == 1
        assert not results[0].success
        assert "test error" in results[0].error


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

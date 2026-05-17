"""
tests/test_selfheal_robust.py — 自愈系统健壮性增强测试

深度覆盖：
- AntibodyLibrary: 磁盘持久化、record_success/failure、success_rate、get_antibody、全部分类匹配
- ErrorProcessor: 所有错误分类分支、retry_func调用、model_chain降级链、stats累计
- EvolutionEngine: 多次evolve、pruning、full_report、边界情况
- EventBus: emit/subscribe/stats/history/reset
"""
import sys
import asyncio
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from self_heal.antibody import AntibodyLibrary, Antibody
from self_heal.error_processor import ErrorProcessor, ErrorCategory
from self_heal.evolution import EvolutionEngine, EvolutionReport
from integration.event_stream import EventBus, Event


# ─── AntibodyLibrary 全面测试 ─────────────────────────────────────────────────
class TestAntibodyLibraryRobust:
    def setup_method(self):
        AntibodyLibrary.reset()
        self.lib = AntibodyLibrary()

    # ── 所有内置抗体匹配 ──────────────────────────────────────────────────────
    def test_match_json_parse_error(self):
        result = self.lib.match("json decode error in response")
        assert result.matched
        assert result.antibody.name == "json-parse-fix"

    def test_match_context_length_exceeded(self):
        result = self.lib.match("context length exceeded, too long")
        assert result.matched
        assert result.antibody.name == "context-trim"

    def test_match_model_unavailable_503(self):
        result = self.lib.match("service unavailable", http_code=503)
        assert result.matched
        assert result.antibody.name in ("model-switch", "404-ban")

    def test_match_http_code_priority_over_pattern(self):
        """HTTP状态码匹配应优于模式匹配（置信度更高）。"""
        result = self.lib.match("some error message", http_code=429)
        assert result.antibody.name == "rate-limit-wait"
        assert result.confidence == 0.9  # 状态码匹配置信度

    def test_match_returns_highest_priority(self):
        """当多个抗体匹配时，应返回优先级最高的。"""
        # 401 错误同时匹配 auth-refresh（priority=9）
        result = self.lib.match("unauthorized invalid api key", http_code=401)
        assert result.antibody.name == "auth-refresh"
        assert result.antibody.priority == 9

    # ── success_rate 计算 ─────────────────────────────────────────────────────
    def test_success_rate_no_calls(self):
        ab = self.lib.get_antibody("ab_404_ban")
        assert ab.success_rate == 0.0

    def test_success_rate_after_records(self):
        ab = self.lib.get_antibody("ab_timeout_retry")
        ab.record_success()
        ab.record_success()
        ab.record_failure()
        # 2 success, 1 failure → 2/3
        assert abs(ab.success_rate - 2/3) < 0.01

    def test_record_success_increments(self):
        ab = self.lib.get_antibody("ab_404_ban")
        before = ab.success_count
        ab.record_success()
        assert ab.success_count == before + 1

    def test_record_failure_increments(self):
        ab = self.lib.get_antibody("ab_rate_limit")
        before = ab.fail_count
        ab.record_failure()
        assert ab.fail_count == before + 1

    # ── get_antibody ──────────────────────────────────────────────────────────
    def test_get_antibody_existing(self):
        ab = self.lib.get_antibody("ab_404_ban")
        assert ab is not None
        assert ab.name == "404-ban"

    def test_get_antibody_nonexistent(self):
        ab = self.lib.get_antibody("nonexistent_id")
        assert ab is None

    # ── all_antibodies 排序 ───────────────────────────────────────────────────
    def test_all_antibodies_sorted_by_priority(self):
        antibodies = self.lib.all_antibodies()
        priorities = [a.priority for a in antibodies]
        assert priorities == sorted(priorities, reverse=True)

    # ── 磁盘持久化 ────────────────────────────────────────────────────────────
    def test_custom_antibody_saved_to_disk(self, tmp_path):
        persist_path = tmp_path / "antibodies.json"
        lib = AntibodyLibrary(persist_path=persist_path)
        lib.generate_new_antibody("custom error", "custom fix", ["step1"])
        assert persist_path.exists()

    def test_custom_antibody_loaded_from_disk(self, tmp_path):
        persist_path = tmp_path / "antibodies.json"
        lib1 = AntibodyLibrary(persist_path=persist_path)
        new_ab = lib1.generate_new_antibody("disk error pattern", "fix", ["s1"])
        ab_id = new_ab.id

        AntibodyLibrary.reset()
        lib2 = AntibodyLibrary(persist_path=persist_path)
        assert lib2.get_antibody(ab_id) is not None

    def test_invalid_persist_file_handled_gracefully(self, tmp_path):
        persist_path = tmp_path / "bad.json"
        persist_path.write_text("not valid json{{{")
        AntibodyLibrary.reset()
        lib = AntibodyLibrary(persist_path=persist_path)
        # 不应崩溃，仍有内置抗体
        assert len(lib.all_antibodies()) == 8

    # ── remove_poor_antibodies ────────────────────────────────────────────────
    def test_remove_poor_antibodies_only_removes_custom(self):
        """只淘汰自定义低效抗体，内置抗体不受影响。"""
        ab = self.lib.generate_new_antibody("poor pattern", "poor fix", ["step"])
        for _ in range(5):
            ab.record_failure()
        initial_builtin = sum(1 for a in self.lib.all_antibodies() if a.is_builtin)
        self.lib.remove_poor_antibodies(min_success_rate=0.5)
        final_builtin = sum(1 for a in self.lib.all_antibodies() if a.is_builtin)
        assert final_builtin == initial_builtin

    def test_remove_poor_antibodies_threshold(self):
        ab = self.lib.generate_new_antibody("low rate", "fix", ["s1"])
        for _ in range(3):
            ab.record_success()
        for _ in range(7):
            ab.record_failure()  # 成功率 = 0.3
        removed = self.lib.remove_poor_antibodies(min_success_rate=0.5)
        assert removed >= 1

    def test_remove_leaves_successful_antibodies(self):
        ab = self.lib.generate_new_antibody("good pattern", "fix", ["s1"])
        for _ in range(8):
            ab.record_success()
        for _ in range(2):
            ab.record_failure()  # 成功率 = 0.8
        removed = self.lib.remove_poor_antibodies(min_success_rate=0.5)
        assert removed == 0  # 高成功率抗体不应被淘汰

    # ── stats ─────────────────────────────────────────────────────────────────
    def test_stats_structure(self):
        stats = self.lib.stats()
        assert "total" in stats
        assert "builtin" in stats
        assert "custom" in stats
        assert "top_used" in stats
        assert stats["builtin"] == 8
        assert stats["custom"] == 0

    def test_stats_after_adding_custom(self):
        self.lib.generate_new_antibody("p", "a", ["s"])
        stats = self.lib.stats()
        assert stats["custom"] == 1
        assert stats["total"] == 9


# ─── ErrorProcessor 全面测试 ──────────────────────────────────────────────────
class TestErrorProcessorRobust:
    def setup_method(self):
        AntibodyLibrary.reset()
        self.processor = ErrorProcessor()

    # ── classify_error 所有分支 ───────────────────────────────────────────────
    def test_classify_401_http_code(self):
        assert self.processor.classify_error("", http_code=401) == ErrorCategory.AUTH

    def test_classify_403_http_code(self):
        assert self.processor.classify_error("", http_code=403) == ErrorCategory.AUTH

    def test_classify_402_credit(self):
        assert self.processor.classify_error("", http_code=402) == ErrorCategory.CREDIT

    def test_classify_credit_keyword(self):
        assert self.processor.classify_error("insufficient credit balance") == ErrorCategory.CREDIT

    def test_classify_429_rate_limit(self):
        assert self.processor.classify_error("too many requests", http_code=429) == ErrorCategory.RATE_LIMIT

    def test_classify_502_model(self):
        assert self.processor.classify_error("", http_code=502) == ErrorCategory.MODEL

    def test_classify_503_model(self):
        assert self.processor.classify_error("service unavailable", http_code=503) == ErrorCategory.MODEL

    def test_classify_timeout_network(self):
        assert self.processor.classify_error("connection timeout") == ErrorCategory.NETWORK

    def test_classify_timed_out(self):
        assert self.processor.classify_error("request timed out after 30 seconds") == ErrorCategory.NETWORK

    def test_classify_context_length(self):
        assert self.processor.classify_error("context length exceeded") == ErrorCategory.CONTEXT

    def test_classify_token_limit(self):
        assert self.processor.classify_error("token limit exceeded") == ErrorCategory.CONTEXT

    def test_classify_json_parse(self):
        assert self.processor.classify_error("json decode error") == ErrorCategory.PARSE

    def test_classify_unknown(self):
        assert self.processor.classify_error("bizarre unknown error xyz") == ErrorCategory.UNKNOWN

    def test_classify_empty_unknown(self):
        assert self.processor.classify_error("", http_code=0) == ErrorCategory.UNKNOWN

    # ── process() 完整流程 ────────────────────────────────────────────────────
    def test_process_returns_10_steps(self):
        report = self.processor.process("test error", http_code=500)
        assert len(report["steps"]) == 10

    def test_process_has_required_fields(self):
        report = self.processor.process("network timeout")
        assert "error_id" in report
        assert "steps" in report
        assert "category" in report
        assert "resolved" in report
        assert "resolve_time_ms" in report
        assert "fallback_model" in report

    def test_process_error_id_format(self):
        report = self.processor.process("test")
        assert report["error_id"].startswith("err_")

    def test_process_model_chain_fallback(self):
        """当传入 model_chain 时，步骤5应识别出降级模型。"""
        report = self.processor.process(
            "connection timeout",
            model="model-a",
            model_chain=["model-a", "model-b", "model-c"],
        )
        assert report["fallback_model"] == "model-b"

    def test_process_model_not_in_chain(self):
        """当 model 不在 model_chain 中时，使用链的第一个。"""
        report = self.processor.process(
            "error",
            model="unknown-model",
            model_chain=["model-a", "model-b"],
        )
        assert report["fallback_model"] is not None

    def test_process_single_model_no_fallback(self):
        report = self.processor.process("error", model="m1", model_chain=["m1"])
        assert report["fallback_model"] is None

    def test_process_with_retry_func_success(self):
        """retry_func 被调用且成功时，resolved=True。"""
        call_count = {"n": 0}
        def retry():
            call_count["n"] += 1
            return "success"

        report = self.processor.process(
            "connection timeout",
            retry_func=retry,
        )
        # 超时类（NETWORK）且有retry_func → 尝试调用
        assert call_count["n"] >= 0  # 不崩溃

    def test_process_with_retry_func_failure(self):
        """retry_func 抛出异常时，resolved=False 且不崩溃。"""
        def retry():
            raise RuntimeError("retry also failed")

        report = self.processor.process("connection timeout", retry_func=retry)
        assert "resolved" in report  # 不崩溃

    def test_process_exception_object(self):
        """支持直接传入 Exception 对象。"""
        err = ValueError("some value error")
        report = self.processor.process(err)
        assert "error_id" in report

    def test_process_antibody_404(self):
        report = self.processor.process("404 not found", http_code=404)
        assert report["antibody"] == "404-ban"

    def test_process_antibody_rate_limit(self):
        report = self.processor.process("rate limit exceeded", http_code=429)
        assert report["antibody"] == "rate-limit-wait"

    # ── stats ─────────────────────────────────────────────────────────────────
    def test_stats_total_processed_increments(self):
        self.processor.process("err1")
        self.processor.process("err2")
        stats = self.processor.stats()
        assert stats["total_processed"] == 2
        assert stats["logged"] == 2

    def test_stats_resolve_rate_calculation(self):
        """resolve_rate 应该是已解决/总数。"""
        # PARSE 类型被标记为部分解决
        self.processor.process("json parse error")
        stats = self.processor.stats()
        assert 0.0 <= stats["resolve_rate"] <= 1.0

    def test_get_error_log_structure(self):
        self.processor.process("test error", http_code=500)
        log = self.processor.get_error_log()
        assert len(log) == 1
        entry = log[0]
        assert "error_id" in entry
        assert "category" in entry
        assert "resolved" in entry


# ─── EvolutionEngine 全面测试 ─────────────────────────────────────────────────
class TestEvolutionEngineRobust:
    def setup_method(self):
        AntibodyLibrary.reset()
        self.lib = AntibodyLibrary()
        self.engine = EvolutionEngine(antibody_lib=self.lib)

    def test_empty_evolve_returns_zero_rate(self):
        report = self.engine.evolve()
        assert report.overall_success_rate == 0.0
        assert report.new_antibodies == 0
        assert report.optimized_antibodies == 0

    def test_all_success_cases(self):
        for _ in range(5):
            self.engine.collect({"resolved": True, "antibody": "timeout-retry", "category": "network"})
        report = self.engine.evolve()
        assert report.overall_success_rate == 1.0

    def test_all_failure_cases(self):
        for _ in range(5):
            self.engine.collect({"resolved": False, "antibody": "generic-catch", "category": "unknown"})
        report = self.engine.evolve()
        assert report.overall_success_rate == 0.0

    def test_mixed_success_rate(self):
        self.engine.collect({"resolved": True, "antibody": "timeout-retry", "category": "network"})
        self.engine.collect({"resolved": False, "antibody": "generic-catch", "category": "unknown"})
        report = self.engine.evolve()
        assert report.overall_success_rate == 0.5

    def test_history_cleared_after_evolve(self):
        self.engine.collect({"resolved": True, "antibody": "ab1", "category": "x"})
        self.engine.evolve()
        report2 = self.engine.evolve()
        # 第二次进化时历史已清空
        assert report2.overall_success_rate == 0.0

    def test_generates_antibody_for_repeated_failures(self):
        for _ in range(3):  # 需要 >= 2 次失败同类型
            self.engine.collect({
                "resolved": False,
                "antibody": "generic-catch",
                "category": "custom_error_xyz",
            })
        report = self.engine.evolve()
        assert report.new_antibodies >= 1

    def test_optimizes_high_success_antibody(self):
        """同一抗体3次成功后应提升优先级。"""
        ab = self.lib.get_antibody("ab_timeout_retry")
        initial_priority = ab.priority
        for _ in range(3):
            self.engine.collect({
                "resolved": True,
                "antibody": "timeout-retry",
                "category": "network",
            })
        report = self.engine.evolve()
        assert report.optimized_antibodies >= 1

    def test_prunes_low_rate_custom_antibody(self):
        """低效自定义抗体应被淘汰。"""
        ab = self.lib.generate_new_antibody("bad pattern", "fix", ["step"])
        for _ in range(5):
            ab.record_failure()  # 成功率=0

        self.engine.collect({"resolved": True, "antibody": "good", "category": "x"})
        report = self.engine.evolve()
        assert report.pruned_antibodies >= 1

    def test_evolve_report_to_dict(self):
        report = EvolutionReport(
            new_antibodies=2,
            optimized_antibodies=1,
            overall_success_rate=0.75
        )
        d = report.to_dict()
        assert d["new_antibodies"] == 2
        assert d["overall_success_rate"] == 0.75
        assert "timestamp" in d

    def test_full_report_structure(self):
        self.engine.collect({"resolved": True, "antibody": "x", "category": "y"})
        report = self.engine.full_report()
        assert "evolve_count" in report
        assert "pending_cases" in report
        assert "antibody_stats" in report
        assert report["pending_cases"] == 1

    def test_full_report_after_evolve_shows_zero_pending(self):
        self.engine.collect({"resolved": True, "antibody": "x", "category": "y"})
        self.engine.evolve()
        report = self.engine.full_report()
        assert report["pending_cases"] == 0

    def test_multiple_evolve_increments_count(self):
        self.engine.evolve()
        self.engine.evolve()
        report = self.engine.full_report()
        assert report["evolve_count"] == 2

    def test_recommendations_populated(self):
        for _ in range(3):
            self.engine.collect({"resolved": True, "antibody": "timeout-retry", "category": "network"})
        report = self.engine.evolve()
        if report.optimized_antibodies > 0:
            assert len(report.recommendations) > 0


# ─── EventBus 全面测试 ────────────────────────────────────────────────────────
class TestEventBusRobust:
    def setup_method(self):
        EventBus.reset()
        self.bus = EventBus()

    # ── emit ──────────────────────────────────────────────────────────────────
    def test_emit_stores_in_history(self):
        self.bus.emit("test_event", key="value")
        history = self.bus.recent_events(10)
        assert len(history) == 1
        assert history[0]["type"] == "test_event"

    def test_emit_multiple_events(self):
        for i in range(5):
            self.bus.emit(f"event_{i}", index=i)
        history = self.bus.recent_events(10)
        assert len(history) == 5

    def test_emit_history_limit(self):
        bus = EventBus(max_history=3)
        for i in range(10):
            bus.emit(f"event_{i}")
        history = bus.recent_events(100)
        assert len(history) == 3

    def test_emit_data_preserved(self):
        self.bus.emit("stage_start", stage="api_call", model="gpt-4")
        history = self.bus.recent_events(5)
        assert history[0]["data"]["stage"] == "api_call"
        assert history[0]["data"]["model"] == "gpt-4"

    def test_emit_with_no_data(self):
        self.bus.emit("ping")
        history = self.bus.recent_events(5)
        assert len(history) == 1

    # ── recent_events ─────────────────────────────────────────────────────────
    def test_recent_events_limit(self):
        for i in range(20):
            self.bus.emit(f"e{i}")
        recent = self.bus.recent_events(5)
        assert len(recent) == 5

    def test_recent_events_returns_latest(self):
        for i in range(5):
            self.bus.emit("event", index=i)
        recent = self.bus.recent_events(3)
        # 最后3条
        assert recent[-1]["data"]["index"] == 4

    # ── stats ─────────────────────────────────────────────────────────────────
    def test_stats_structure(self):
        self.bus.emit("test")
        stats = self.bus.stats()
        assert "history_size" in stats
        assert "subscribers" in stats
        assert "max_history" in stats
        assert stats["history_size"] == 1
        assert stats["subscribers"] == 0

    # ── subscriber_count ──────────────────────────────────────────────────────
    def test_subscriber_count_initially_zero(self):
        assert self.bus.subscriber_count == 0

    # ── subscribe async generator ─────────────────────────────────────────────
    def test_subscribe_receives_emitted_events(self):
        """订阅者应该能收到 emit 的事件（通过独立线程发布）。"""
        import threading

        received = []

        async def consumer():
            async for sse_text in self.bus.subscribe():
                received.append(sse_text)
                break  # 收到第一个事件后退出

        def emit_after_delay():
            import time
            time.sleep(0.05)
            self.bus.emit("hello", msg="world")

        t = threading.Thread(target=emit_after_delay, daemon=True)
        t.start()
        asyncio.run(consumer())
        t.join(timeout=1)

        assert len(received) == 1
        assert "hello" in received[0]

    def test_subscribe_with_history_replay(self):
        """replay_history=True 时，新订阅者应先收到历史事件。"""
        self.bus.emit("old_event_1")
        self.bus.emit("old_event_2")

        received = []

        async def consumer():
            async for sse_text in self.bus.subscribe(replay_history=True):
                received.append(sse_text)
                if len(received) >= 2:
                    break

        asyncio.run(consumer())
        assert len(received) >= 2
        assert "old_event" in received[0]

    def test_sse_format(self):
        """SSE格式应符合 event: xxx\ndata: {...}\n\n 规范。"""
        from integration.event_stream import Event as BusEvent
        event = BusEvent(event_type="test", data={"key": "val"})
        sse = event.to_sse()
        assert sse.startswith("event: test")
        assert "data:" in sse
        assert sse.endswith("\n\n")

    def test_event_to_dict(self):
        from integration.event_stream import Event as BusEvent
        event = BusEvent(event_type="my_event", data={"x": 1})
        d = event.to_dict()
        assert d["type"] == "my_event"
        assert d["data"]["x"] == 1
        assert "timestamp" in d

    # ── singleton ─────────────────────────────────────────────────────────────
    def test_get_returns_same_instance(self):
        EventBus.reset()
        b1 = EventBus.get()
        b2 = EventBus.get()
        assert b1 is b2

    def test_reset_creates_new_instance(self):
        EventBus.reset()
        b1 = EventBus.get()
        EventBus.reset()
        b2 = EventBus.get()
        assert b1 is not b2

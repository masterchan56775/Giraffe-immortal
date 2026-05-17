"""
tests/test_observability.py — 可观测性、事件总线和多模态工具的测试
"""
import asyncio
import pytest
from observability.tracer import get_tracer, traced, _NoOpTracer, _NoOpSpan
from integration.event_stream import EventBus, Event
from integration.multimodal import build_multimodal_content


# ─── Tracer 测试 ──────────────────────────────────────────────────────────────
class TestTracer:
    """测试 NoOp 降级模式下的 Tracer。"""

    def test_get_tracer_returns_noop_without_init(self):
        """未初始化时应返回 NoOp Tracer。"""
        tracer = get_tracer("test")
        assert isinstance(tracer, _NoOpTracer)

    def test_noop_span_methods_safe(self):
        """NoOp Span 的所有方法不应抛出异常。"""
        span = _NoOpSpan()
        span.set_attribute("key", "value")
        span.set_status("OK")
        span.record_exception(RuntimeError("test"))
        span.end()

    def test_noop_span_context_manager(self):
        """NoOp Span 可作为 context manager 使用。"""
        with _NoOpSpan() as span:
            span.set_attribute("key", "value")

    def test_noop_tracer_start_as_current_span(self):
        """NoOp Tracer 的 start_as_current_span 返回 NoOpSpan。"""
        tracer = _NoOpTracer()
        span = tracer.start_as_current_span("test.span")
        assert isinstance(span, _NoOpSpan)

    def test_traced_decorator_noop(self):
        """@traced 装饰器在 NoOp 模式下不影响函数执行。"""

        @traced("test.func")
        def add(a, b):
            return a + b

        assert add(1, 2) == 3

    def test_traced_decorator_preserves_exception(self):
        """@traced 装饰器不应吞掉异常。"""

        @traced("test.error")
        def fail():
            raise ValueError("boom")

        with pytest.raises(ValueError, match="boom"):
            fail()


# ─── EventBus 测试 ────────────────────────────────────────────────────────────
class TestEventBus:
    """测试事件总线。"""

    def setup_method(self):
        EventBus.reset()

    def test_singleton(self):
        bus1 = EventBus.get()
        bus2 = EventBus.get()
        assert bus1 is bus2

    def test_emit_records_history(self):
        bus = EventBus.get()
        bus.emit("test_event", key="value")
        events = bus.recent_events(5)
        assert len(events) == 1
        assert events[0]["type"] == "test_event"
        assert events[0]["data"]["key"] == "value"

    def test_emit_multiple_events(self):
        bus = EventBus.get()
        bus.emit("event_a", x=1)
        bus.emit("event_b", y=2)
        bus.emit("event_c", z=3)
        events = bus.recent_events(10)
        assert len(events) == 3
        assert [e["type"] for e in events] == ["event_a", "event_b", "event_c"]

    def test_history_limit(self):
        bus = EventBus(max_history=5)
        for i in range(10):
            bus.emit("event", idx=i)
        events = bus.recent_events(100)
        assert len(events) == 5
        # 保留最新的 5 个
        assert events[0]["data"]["idx"] == 5

    def test_stats(self):
        bus = EventBus.get()
        bus.emit("a")
        bus.emit("b")
        stats = bus.stats()
        assert stats["history_size"] == 2
        assert stats["subscribers"] == 0

    def test_subscriber_count(self):
        bus = EventBus.get()
        assert bus.subscriber_count == 0


# ─── Event 测试 ───────────────────────────────────────────────────────────────
class TestEvent:
    def test_to_sse_format(self):
        event = Event(event_type="token_chunk", data={"text": "hello"}, timestamp=0)
        sse = event.to_sse()
        assert sse.startswith("event: token_chunk\n")
        assert "data: " in sse
        assert '"text": "hello"' in sse
        assert sse.endswith("\n\n")


# ─── 多模态工具测试 ───────────────────────────────────────────────────────────
class TestMultimodal:
    def test_build_multimodal_text_only(self):
        result = build_multimodal_content("hello", [])
        assert len(result) == 1
        assert result[0]["type"] == "text"
        assert result[0]["text"] == "hello"

    def test_build_multimodal_with_images(self):
        images = ["data:image/png;base64,abc123"]
        result = build_multimodal_content("describe this", images)
        assert len(result) == 2
        assert result[0]["type"] == "text"
        assert result[1]["type"] == "image_url"
        assert result[1]["image_url"]["url"] == "data:image/png;base64,abc123"

    def test_build_multimodal_auto_prefix(self):
        """纯 base64 字符串应自动补全 data URI 前缀。"""
        result = build_multimodal_content("test", ["abc123"])
        assert result[1]["image_url"]["url"] == "data:image/png;base64,abc123"

    def test_build_multimodal_multiple_images(self):
        images = [
            "data:image/jpeg;base64,img1",
            "data:image/png;base64,img2",
        ]
        result = build_multimodal_content("look", images)
        assert len(result) == 3  # 1 text + 2 images

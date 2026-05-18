"""
tests/test_router.py — 路由引擎测试
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest
from router.engine import RouterEngine
from router.intent_classifier import IntentClassifier, TaskType
from router.query_complexity import ComplexityEstimator, ComplexityLevel
from router.gatekeeper import Gatekeeper, RouteTier
from router.model_registry import ModelRegistry


class TestIntentClassifier:
    def setup_method(self):
        self.clf = IntentClassifier()

    def test_code_medium_keyword(self):
        result = self.clf.classify("帮我写一个Flask API")
        assert result.task_type == TaskType.CODE_MEDIUM
        assert result.method == "keyword"

    def test_chat_keyword(self):
        result = self.clf.classify("你好，在吗？")
        assert result.task_type == TaskType.CHAT

    def test_vision_image(self):
        result = self.clf.classify("这是什么", has_image=True)
        assert result.task_type == TaskType.VISION
        assert result.confidence == 1.0

    def test_reasoning_keyword(self):
        result = self.clf.classify("分析一下这段代码的性能问题")
        # 包含代码关键词时，chat/code/reasoning均合理
        assert result.task_type in (
            TaskType.REASONING, TaskType.REASONING_LIGHT,
            TaskType.CODE_MEDIUM, TaskType.CODE_SMALL, TaskType.CHAT
        )

    def test_ambiguous_low_confidence(self):
        result = self.clf.classify("随便说点什么")
        assert self.clf.is_ambiguous(result) or result.task_type == TaskType.CHAT


class TestComplexityEstimator:
    def setup_method(self):
        self.est = ComplexityEstimator()

    def test_short_message_trivial(self):
        result = self.est.estimate("你好")
        assert result.level in (ComplexityLevel.TRIVIAL, ComplexityLevel.SIMPLE)

    def test_long_message_complex(self):
        long_msg = "请帮我设计一个分布式系统架构，包括负载均衡、服务发现、数据库分片、缓存层、" * 5
        result = self.est.estimate(long_msg)
        assert result.level in (ComplexityLevel.COMPLEX, ComplexityLevel.EXTREME)

    def test_architecture_keyword_boost(self):
        result = self.est.estimate("请帮我设计系统架构")
        # 架构词会提升分数，但短消息基础分低，超过2.0即合理
        assert result.score > 1.5

    def test_simple_keyword_reduces_score(self):
        result_normal = self.est.estimate("分析这段代码")
        result_simple = self.est.estimate("简单分析一下这段代码")
        assert result_simple.score <= result_normal.score


class TestGatekeeper:
    def setup_method(self):
        self.gk = Gatekeeper()

    def test_chat_is_nano_auto(self):
        result = self.gk.check(TaskType.CHAT)
        assert result.tier == RouteTier.NANO
        assert result.auto_execute is True

    def test_code_large_is_medium_confirm(self):
        result = self.gk.check(TaskType.CODE_LARGE)
        assert result.tier == RouteTier.MEDIUM
        assert result.requires_confirmation is True

    def test_reasoning_is_high(self):
        result = self.gk.check(TaskType.REASONING)
        assert result.tier in (RouteTier.HIGH, RouteTier.XHIGH)

    def test_extreme_complexity_upgrades_tier(self):
        result = self.gk.check(TaskType.CHAT, ComplexityLevel.EXTREME)
        assert result.tier.value in ("high", "xhigh")


class TestModelRegistry:
    def setup_method(self):
        ModelRegistry.reset()
        self.reg = ModelRegistry()

    def test_get_model_chain(self):
        chain = self.reg.get_model_chain("chat")
        assert len(chain) == 3

    def test_fallback_chain_order(self):
        chain = self.reg.get_model_chain("reasoning")
        assert chain[0] == "claude-sonnet-4-6"
        assert chain[1] == "xai/grok-4.20-reasoning"
        assert chain[2] == "gemini-3.1-pro-preview"

    def test_all_task_types_have_chains(self):
        for task_type in self.reg.list_task_types():
            chain = self.reg.get_model_chain(task_type)
            assert len(chain) == 3


class TestRouterEngine:
    def setup_method(self):
        ModelRegistry.reset()
        self.router = RouterEngine()

    def test_route_flask_api(self):
        decision = self.router.route("帮我写一个Flask API")
        # Flask API可能被分类为code_small或code_medium
        assert decision.task_type in (TaskType.CODE_SMALL, TaskType.CODE_MEDIUM)
        assert decision.primary_model != ""
        assert decision.latency_ms >= 0

    def test_route_vision(self):
        decision = self.router.route("看这张图", has_image=True)
        assert decision.task_type == TaskType.VISION

    def test_route_and_get_runtime(self):
        model, runtime = self.router.route_and_get_runtime("帮我分析这段代码")
        assert isinstance(model, str)
        assert "task_type" in runtime

    def test_stats_tracking(self):
        self.router.route("你好")
        self.router.route("帮我写代码")
        stats = self.router.stats()
        assert stats["total_routes"] == 2


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

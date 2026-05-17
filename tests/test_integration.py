"""
tests/test_integration.py — 集成与工作流模块测试
"""
import sys, tempfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest
from integration.gateway_api import GatewayAPI
from integration.hooks import HookSystem
from integration.cron_sync import CronSync
from integration.startup import StartupManager
from integration.hermes_bridge import HermesBridge
from workflow.engine import WorkflowEngine
from workflow.step import WorkflowStep, StepStatus
from sandbox.manager import SandboxManager
from sandbox.executor import SandboxExecutor
from adapt.adapter import HermesAdapter
from adapt.scanner import HermesScanner
from adapt.compat_report import CompatReport


class TestGatewayAPI:
    def setup_method(self):
        GatewayAPI.reset()
        self.gateway = GatewayAPI()

    def test_register_platform(self):
        self.gateway.register_platform("slack", {"token": "xxx"})
        assert "slack" in self.gateway.list_platforms()

    def test_deregister_platform(self):
        self.gateway.register_platform("discord", {})
        self.gateway.deregister_platform("discord")
        assert "discord" not in self.gateway.list_platforms()

    def test_health_check_structure(self):
        health = self.gateway.health_check()
        assert "status" in health
        assert "platforms" in health

    def test_singleton(self):
        GatewayAPI.reset()
        g1 = GatewayAPI.get()
        g2 = GatewayAPI.get()
        assert g1 is g2

    def test_supported_platforms_list(self):
        platforms = self.gateway.supported_platforms()
        assert "telegram" in platforms
        assert "discord" in platforms
        assert "slack" in platforms
        assert "matrix" in platforms
        assert "webhook" in platforms

    def test_add_platform_missing_dep_returns_none(self):
        # telegram 未安装时返回 None，不抛出异常
        from integration.platforms import PlatformRegistry
        PlatformRegistry.reset()
        result = self.gateway.add_platform("telegram", {"token": "fake"})
        # 可能返回 None（未安装）或适配器实例（已安装），均可接受
        assert result is None or hasattr(result, "platform_name")


class TestPlatformRegistry:
    """测试 PlatformRegistry 核心逻辑（不依赖外部平台 SDK）。"""

    def setup_method(self):
        from integration.platforms import PlatformRegistry
        PlatformRegistry.reset()
        self.registry = PlatformRegistry()

    def test_supported_platforms(self):
        platforms = self.registry.supported_platforms()
        assert set(["telegram", "discord", "slack", "matrix", "webhook"]).issubset(set(platforms))

    def test_register_webhook_adapter(self):
        """Webhook 适配器无外部依赖，始终可注册。"""
        adapter = self.registry.register("webhook", {
            "endpoints": {"/webhook/test": {"platform": "test"}}
        })
        assert adapter is not None
        assert adapter.platform_name == "webhook"
        assert "webhook" in self.registry.list_platforms()

    def test_register_unknown_platform_returns_none(self):
        result = self.registry.register("unknown_platform_xyz", {})
        assert result is None

    def test_register_custom_adapter(self):
        from integration.platforms.base import PlatformAdapter, IncomingMessage, OutgoingMessage

        class DummyAdapter(PlatformAdapter):
            platform_name = "dummy"
            async def start(self): self._running = True
            async def stop(self): self._running = False
            async def send(self, msg): return True

        self.registry.register_platform_type("dummy", DummyAdapter)
        adapter = self.registry.register("dummy", {})
        assert adapter is not None
        assert adapter.platform_name == "dummy"

    def test_status_reflects_running_state(self):
        from integration.platforms.base import PlatformAdapter, IncomingMessage, OutgoingMessage

        class MockAdapter(PlatformAdapter):
            platform_name = "mock"
            async def start(self): self._running = True
            async def stop(self): self._running = False
            async def send(self, msg): return True

        self.registry.register_platform_type("mock", MockAdapter)
        self.registry.register("mock", {})
        status = self.registry.status()
        assert "mock" in status
        assert status["mock"]["running"] is False  # 未调用 start()

    def test_set_handler_propagates(self):
        from integration.platforms.base import PlatformAdapter, IncomingMessage, OutgoingMessage

        class MockAdapter(PlatformAdapter):
            platform_name = "mock2"
            async def start(self): pass
            async def stop(self): pass
            async def send(self, msg): return True

        self.registry.register_platform_type("mock2", MockAdapter)
        self.registry.register("mock2", {})

        async def my_handler(msg): return "pong"
        self.registry.set_handler(my_handler)
        adapter = self.registry.get_adapter("mock2")
        assert adapter._handler is my_handler


class TestIncomingOutgoingMessage:
    """测试消息数据结构。"""

    def test_incoming_defaults(self):
        from integration.platforms.base import IncomingMessage
        msg = IncomingMessage(platform="test", chat_id="123", user_id="u1", text="hello")
        assert msg.images == []
        assert msg.raw == {}
        assert msg.message_id == ""

    def test_outgoing_defaults(self):
        from integration.platforms.base import OutgoingMessage
        msg = OutgoingMessage(chat_id="123", text="hi")
        assert msg.parse_mode == "markdown"
        assert msg.disable_preview is True
        assert msg.reply_to_id == ""




class TestHookSystem:
    def setup_method(self):
        HookSystem.reset()
        self.hooks = HookSystem()

    def test_register_and_fire(self):
        calls = []
        self.hooks.register("pre_api_request", lambda **kw: calls.append(kw))
        self.hooks.fire("pre_api_request", message="hello", model="gemini-3-flash-preview")
        assert len(calls) == 1
        assert calls[0]["message"] == "hello"

    def test_multiple_hooks_for_same_event(self):
        results = []
        self.hooks.register("post_api_response", lambda **kw: results.append("h1"))
        self.hooks.register("post_api_response", lambda **kw: results.append("h2"))
        self.hooks.fire("post_api_response", response="ok", success=True)
        assert len(results) == 2

    def test_hook_exception_does_not_propagate(self):
        def bad_hook(**kw):
            raise RuntimeError("hook error")
        self.hooks.register("pre_api_request", bad_hook)
        # 不应抛出异常
        self.hooks.fire("pre_api_request", message="test")

    def test_unregister_hook(self):
        calls = []
        fn = lambda **kw: calls.append(1)
        self.hooks.register("pre_api_request", fn)
        self.hooks.unregister("pre_api_request", fn)
        self.hooks.fire("pre_api_request", message="test")
        assert len(calls) == 0

    def test_list_events(self):
        events = self.hooks.list_events()
        assert "pre_api_request" in events
        assert "post_api_response" in events


class TestCronSync:
    def test_register_and_manual_run(self):
        cron = CronSync()
        calls = []
        cron.register("test_job", lambda: calls.append(1), interval=999)
        cron.run_now("test_job")
        assert len(calls) == 1

    def test_stats(self):
        cron = CronSync()
        cron.register("job1", lambda: None, interval=100)
        stats = cron.stats()
        assert stats["jobs"][0]["name"] == "job1"

    def test_run_now_unknown_job_returns_false(self):
        cron = CronSync()
        assert not cron.run_now("nonexistent")


class TestStartupManager:
    def test_run_all_order(self):
        mgr = StartupManager()
        order = []
        mgr.register("b", lambda: order.append("b"), order=20)
        mgr.register("a", lambda: order.append("a"), order=10)
        mgr.register("c", lambda: order.append("c"), order=30)
        mgr.run_all()
        assert order == ["a", "b", "c"]

    def test_failed_task_captured_not_raised(self):
        mgr = StartupManager()
        def _fail():
            raise ValueError("deliberate fail")
        mgr.register("failing", _fail)
        results = mgr.run_all()
        assert results["failing"].startswith("error")


class TestHermesBridge:
    def test_connect_and_disconnect(self):
        bridge = HermesBridge("2.0")
        assert not bridge.is_connected
        bridge.connect()
        assert bridge.is_connected
        bridge.disconnect()
        assert not bridge.is_connected

    def test_sync_capabilities_without_connect(self):
        bridge = HermesBridge()
        result = bridge.sync_capabilities(["cap1"])
        assert "error" in result

    def test_sync_capabilities_connected(self):
        bridge = HermesBridge("2.0")
        bridge.connect()
        result = bridge.sync_capabilities(["cap1", "cap2"])
        assert result["synced"] == 2


class TestWorkflowEngine:
    def setup_method(self):
        self.engine = WorkflowEngine()

    def test_register_and_run(self):
        calls = []
        self.engine.register("echo", lambda text="": calls.append(text) or text)
        self.engine.add_step("step1", "echo", text="hello")
        results = self.engine.run()
        assert results.get("step1") == "hello"

    def test_pause_and_resume(self):
        calls = []
        self.engine.register("task", lambda n=0: calls.append(n))
        self.engine.add_step("s1", "task", n=1)
        self.engine.add_step("s2", "task", n=2)
        self.engine.pause()
        self.engine.run()
        assert len(calls) == 0  # 暂停后不执行
        self.engine.resume()
        assert len(calls) == 2

    def test_completed_step_skipped(self):
        calls = []
        self.engine.register("work", lambda: calls.append(1))
        step = self.engine.add_step("s1", "work")
        step.status = StepStatus.COMPLETED  # 预置为已完成
        self.engine.run()
        assert len(calls) == 0  # 已完成的跳过

    def test_stats(self):
        self.engine.register("noop", lambda: None)
        self.engine.add_step("s1", "noop")
        self.engine.run()
        stats = self.engine.stats()
        assert stats["completed"] == 1
        assert stats["total_steps"] == 1


class TestSandboxManager:
    def test_create_and_cleanup(self):
        mgr = SandboxManager()
        sid = mgr.create("test_sb")
        assert sid == "test_sb"
        assert len(mgr.list_sandboxes()) == 1
        assert mgr.cleanup("test_sb")
        assert len(mgr.list_sandboxes()) == 0

    def test_cleanup_nonexistent_returns_false(self):
        mgr = SandboxManager()
        assert not mgr.cleanup("ghost_sandbox")

    def test_stats_has_docker_field(self):
        mgr = SandboxManager()
        stats = mgr.stats()
        assert "docker_available" in stats
        assert "active_sandboxes" in stats


class TestSandboxExecutor:
    def setup_method(self):
        self.executor = SandboxExecutor()

    def test_safe_code_runs(self):
        result = self.executor.run_code("x = 1 + 1")
        assert result["success"]

    def test_exception_captured(self):
        result = self.executor.run_code("raise ValueError('test error')")
        assert not result["success"]
        assert "test error" in result["stderr"]

    def test_stdout_captured(self):
        result = self.executor.run_code("print('hello sandbox')")
        assert result["success"]
        assert "hello sandbox" in result["stdout"]


class TestHermesAdapter:
    def test_adapt_empty_scan(self):
        adapter = HermesAdapter()
        result = adapter.adapt({"new_features": [], "breaking_changes": []})
        assert result["status"] == "ok"
        assert result["fixed"] == []

    def test_adapt_with_features(self):
        adapter = HermesAdapter()
        result = adapter.adapt({"new_features": ["feature_a", "feature_b"]})
        assert len(result["fixed"]) == 2


class TestHermesScanner:
    def test_scan_returns_structure(self):
        scanner = HermesScanner("1.0.0")
        result = scanner.scan("2.0.0")
        assert "current_version" in result
        assert "target_version" in result
        assert "new_features" in result


class TestCompatReport:
    def test_no_issues_is_compatible(self):
        report = CompatReport()
        assert report.compatible

    def test_add_issue_marks_incompatible(self):
        report = CompatReport()
        report.add_issue("breaking change detected")
        assert not report.compatible
        assert len(report.issues) == 1

    def test_to_dict(self):
        report = CompatReport()
        d = report.to_dict()
        assert "compatible" in d
        assert "issues" in d
        assert "recommendations" in d


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

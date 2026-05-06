"""
tests/test_swarm.py — 阶段四：多智能体 Swarm 完整测试

涵盖：
- AgentProfile 数据类
- 预置角色模板
- Agent.think() 调用行为
- SwarmOrchestrator 多轮讨论编排
- SwarmResult 结构
- 终止条件检测
"""
import pytest
from swarm.agent import AgentProfile, Agent
from swarm.profiles import ARCHITECT, CODER, REVIEWER, TESTER, get_profile, BUILTIN_PROFILES
from swarm.orchestrator import SwarmOrchestrator, SwarmResult


# ─── AgentProfile 测试 ───────────────────────────────────────────────────────
class TestAgentProfile:
    def test_basic_creation(self):
        p = AgentProfile(name="test_agent", system_prompt="You are a test agent.")
        assert p.name == "test_agent"
        assert p.system_prompt == "You are a test agent."
        assert p.temperature == 0.7
        assert p.tools == []

    def test_custom_temperature(self):
        p = AgentProfile(name="strict", temperature=0.1)
        assert p.temperature == 0.1

    def test_to_dict(self):
        p = AgentProfile(name="coder", model="gpt-4", tools=["read_file"])
        d = p.to_dict()
        assert d["name"] == "coder"
        assert d["model"] == "gpt-4"
        assert "read_file" in d["tools"]

    def test_long_system_prompt_truncated_in_dict(self):
        long_prompt = "x" * 200
        p = AgentProfile(name="a", system_prompt=long_prompt)
        d = p.to_dict()
        assert len(d["system_prompt"]) <= 83  # 80 chars + "..."


# ─── 预置角色测试 ─────────────────────────────────────────────────────────────
class TestBuiltinProfiles:
    def test_all_four_profiles_exist(self):
        assert "architect" in BUILTIN_PROFILES
        assert "coder" in BUILTIN_PROFILES
        assert "reviewer" in BUILTIN_PROFILES
        assert "tester" in BUILTIN_PROFILES

    def test_architect_profile(self):
        assert ARCHITECT.name == "architect"
        assert ARCHITECT.temperature < 0.5  # 偏保守

    def test_coder_profile(self):
        assert CODER.name == "coder"
        assert CODER.temperature <= 0.3
        assert "write_file" in CODER.tools

    def test_reviewer_profile(self):
        assert REVIEWER.name == "reviewer"
        assert REVIEWER.temperature <= 0.2  # 极低温度

    def test_tester_profile(self):
        assert TESTER.name == "tester"
        assert "run_command" in TESTER.tools

    def test_get_profile(self):
        p = get_profile("architect")
        assert p is not None
        assert p.name == "architect"

    def test_get_profile_not_found(self):
        assert get_profile("nonexistent") is None


# ─── Agent.think() 测试 ──────────────────────────────────────────────────────
class _DummyPipeline:
    """测试用虚拟 Pipeline。"""
    class _Result:
        def __init__(self, resp, success=True):
            self.response = resp
            self.success = success
            self.error = None

    def execute(self, ctx):
        # 回显系统提示的前20字符 + 消息
        prefix = ctx.system_prompt[:20] if ctx.system_prompt else ""
        return self._Result(f"[{prefix}] {ctx.message[:50]}")


class TestAgent:
    def test_think_returns_string(self):
        profile = AgentProfile(name="test", system_prompt="You are helpful.")
        agent = Agent(profile=profile, pipeline=_DummyPipeline())
        result = agent.think("Write a function", [])
        assert isinstance(result, str)
        assert len(result) > 0

    def test_think_with_context(self):
        profile = AgentProfile(name="test", system_prompt="Reviewer.")
        agent = Agent(profile=profile, pipeline=_DummyPipeline())
        context = [{"role": "user", "content": "Previous discussion point"}]
        result = agent.think("Review this", context)
        assert isinstance(result, str)

    def test_agent_name(self):
        profile = AgentProfile(name="my_agent")
        agent = Agent(profile=profile, pipeline=_DummyPipeline())
        assert agent.name == "my_agent"


# ─── SwarmOrchestrator 测试 ──────────────────────────────────────────────────
def _make_agents(names: list[str]) -> list[Agent]:
    """创建一组虚拟 Agent。"""
    agents = []
    for name in names:
        profile = AgentProfile(name=name, system_prompt=f"You are {name}.")
        agents.append(Agent(profile=profile, pipeline=_DummyPipeline()))
    return agents


class TestSwarmOrchestrator:
    def test_basic_run(self):
        agents = _make_agents(["architect", "coder"])
        orch = SwarmOrchestrator(agents=agents, max_rounds=2)
        result = orch.run("Design a REST API")

        assert isinstance(result, SwarmResult)
        assert result.success is True
        assert result.final_output != ""
        assert result.rounds <= 2

    def test_discussion_recorded(self):
        agents = _make_agents(["architect", "coder"])
        orch = SwarmOrchestrator(agents=agents, max_rounds=1)
        result = orch.run("任务")

        assert len(result.discussion) == 2  # 2 agents, 1 round
        for turn in result.discussion:
            assert "name" in turn
            assert "content" in turn
            assert "round" in turn

    def test_agent_stats(self):
        agents = _make_agents(["a", "b", "c"])
        orch = SwarmOrchestrator(agents=agents, max_rounds=2)
        result = orch.run("Test task")

        assert "a" in result.agent_stats
        assert "b" in result.agent_stats
        assert "c" in result.agent_stats

    def test_termination_on_approved(self):
        """当 Reviewer 输出 APPROVED 时，应提前终止。"""
        class _ApprovalPipeline:
            class _Result:
                def __init__(self, r): self.response = r; self.success = True; self.error = None
            def execute(self, ctx):
                # reviewer 角色返回 APPROVED
                if "reviewer" in (ctx.system_prompt or "").lower():
                    return self._Result("This looks good. APPROVED.")
                return self._Result("Here is my work.")

        profiles_data = [
            AgentProfile(name="coder", system_prompt="You are coder."),
            AgentProfile(name="reviewer", system_prompt="You are reviewer."),
        ]
        agents = [Agent(p, _ApprovalPipeline()) for p in profiles_data]
        orch = SwarmOrchestrator(agents=agents, max_rounds=10)
        result = orch.run("Write code")

        assert result.termination_reason == "approved"
        assert result.rounds == 1  # 终止在第1轮

    def test_max_rounds_termination(self):
        """未达到终止条件时，应在 max_rounds 结束。"""
        agents = _make_agents(["a", "b"])
        orch = SwarmOrchestrator(agents=agents, max_rounds=2)
        result = orch.run("Never approve this")

        assert result.termination_reason == "max_rounds"
        assert result.rounds == 2

    def test_duration_is_positive(self):
        agents = _make_agents(["a"])
        orch = SwarmOrchestrator(agents=agents, max_rounds=1)
        result = orch.run("Quick task")
        assert result.duration_ms >= 0

    def test_swarm_result_to_dict(self):
        result = SwarmResult(
            success=True,
            final_output="The final answer",
            rounds=3,
            termination_reason="approved",
            agent_stats={"a": 3},
        )
        d = result.to_dict()
        assert d["success"] is True
        assert d["rounds"] == 3
        assert d["termination_reason"] == "approved"
        assert "final_output" in d


# ─── 终止条件检测 ─────────────────────────────────────────────────────────────
class TestTerminationCheck:
    def _make_orch(self):
        agents = _make_agents(["a"])
        return SwarmOrchestrator(agents=agents)

    def test_approved_keyword_triggers_termination(self):
        orch = self._make_orch()
        msgs = [{"name": "reviewer", "content": "Code looks good. APPROVED."}]
        assert orch._check_termination(msgs) is True

    def test_no_approved_does_not_terminate(self):
        orch = self._make_orch()
        msgs = [{"name": "reviewer", "content": "Needs more work."}]
        assert orch._check_termination(msgs) is False

    def test_empty_messages(self):
        orch = self._make_orch()
        assert orch._check_termination([]) is False

    def test_case_insensitive_approved(self):
        orch = self._make_orch()
        msgs = [{"name": "r", "content": "approved - all good"}]
        assert orch._check_termination(msgs) is True

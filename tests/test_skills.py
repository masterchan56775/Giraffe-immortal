"""tests/test_skills.py — Skill 相关全模块健壮性测试"""
import sys, time, tempfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
import pytest
from datetime import datetime, timedelta

# ── SkillLoader ───────────────────────────────────────────────────────────────
from executor.skill_loader import SkillLoader

class TestSkillLoader:
    def test_nonexistent_dir_returns_0(self, tmp_path):
        sl = SkillLoader(skills_dir=tmp_path / "nosuchdir")
        assert sl.load_all() == 0

    def test_loads_skill_file(self, tmp_path):
        (tmp_path / "skill_hello.py").write_text(
            'SKILL_NAME="hello"\ndef execute(x): return x.upper()\n'
        )
        sl = SkillLoader(skills_dir=tmp_path)
        count = sl.load_all()
        assert count == 1
        assert "skill_hello" in sl.list_skills()

    def test_get_skill_returns_module(self, tmp_path):
        (tmp_path / "skill_hi.py").write_text('def execute(x): return x+"!"\n')
        sl = SkillLoader(skills_dir=tmp_path)
        sl.load_all()
        mod = sl.get_skill("skill_hi")
        assert mod is not None
        assert mod.execute("hello") == "hello!"

    def test_get_nonexistent_skill_returns_none(self, tmp_path):
        sl = SkillLoader(skills_dir=tmp_path)
        assert sl.get_skill("nonexistent") is None

    def test_broken_skill_skipped(self, tmp_path):
        (tmp_path / "skill_broken.py").write_text("raise ValueError('oops')\n")
        (tmp_path / "skill_ok.py").write_text("def execute(): return 'ok'\n")
        sl = SkillLoader(skills_dir=tmp_path)
        count = sl.load_all()
        assert count == 1
        assert sl.get_skill("skill_ok") is not None

    def test_only_skill_prefix_loaded(self, tmp_path):
        (tmp_path / "helper.py").write_text("X=1\n")
        (tmp_path / "skill_real.py").write_text("X=2\n")
        sl = SkillLoader(skills_dir=tmp_path)
        assert sl.load_all() == 1

    def test_loads_builtin_example(self):
        sl = SkillLoader()
        count = sl.load_all()
        assert count >= 1
        assert "skill_example" in sl.list_skills()
        mod = sl.get_skill("skill_example")
        assert mod.execute("hello") == "HELLO"

    def test_repr(self, tmp_path):
        sl = SkillLoader(skills_dir=tmp_path)
        assert "SkillLoader" in repr(sl)


# ── SkillReviewer ─────────────────────────────────────────────────────────────
from core.skill_reviewer import SkillReviewer, Skill, SkillScore

def _make_skill(sid="s1", name="test", content="内容", usage=0, days_old=0):
    s = Skill(skill_id=sid, name=name, content=content, usage_count=usage)
    if days_old > 0:
        s.last_used_at = datetime.now() - timedelta(days=days_old)
    return s

class TestSkillScore:
    def test_total_is_sum(self):
        ss = SkillScore(skill_id="x", name="x", base_score=50, content_score=20, usage_score=10)
        assert ss.total == 80

    def test_to_dict_has_total(self):
        ss = SkillScore(skill_id="x", name="x")
        d = ss.to_dict()
        assert "total" in d

class TestSkill:
    def test_use_increments(self):
        s = _make_skill()
        s.use()
        assert s.usage_count == 1

    def test_days_since_used(self):
        s = _make_skill(days_old=5)
        assert s.days_since_used >= 5

    def test_to_dict_keys(self):
        s = _make_skill()
        d = s.to_dict()
        for k in ("skill_id","name","content","usage_count"):
            assert k in d

class TestSkillReviewer:
    def setup_method(self):
        self.r = SkillReviewer()

    def test_add_and_get(self):
        s = _make_skill("s1")
        self.r.add_skill(s)
        assert self.r.get_skill("s1") is s

    def test_remove_skill(self):
        s = _make_skill("s2")
        self.r.add_skill(s)
        assert self.r.remove_skill("s2") is True
        assert self.r.get_skill("s2") is None

    def test_remove_nonexistent(self):
        assert self.r.remove_skill("ghost") is False

    def test_score_base_score(self):
        s = _make_skill(content="短")
        score = self.r.score_skill(s)
        assert score.base_score == 50

    def test_score_long_content_higher(self):
        short = _make_skill("a", content="短")
        long  = _make_skill("b", content="x" * 300)
        assert self.r.score_skill(long).total > self.r.score_skill(short).total

    def test_score_with_examples_bonus(self):
        s = _make_skill(content="例如这样做：x=1，example: foo()")
        score = self.r.score_skill(s)
        assert score.content_score >= 10

    def test_score_with_steps_bonus(self):
        s = _make_skill(content="1. 第一步\n2. 第二步\n3. 第三步")
        score = self.r.score_skill(s)
        assert score.content_score >= 10

    def test_score_usage_count(self):
        s = _make_skill(usage=5)
        score = self.r.score_skill(s)
        assert score.usage_score == 10

    def test_score_usage_capped_at_20(self):
        s = _make_skill(usage=100)
        score = self.r.score_skill(s)
        assert score.usage_score == 20

    def test_score_all_sorted(self):
        self.r.add_skill(_make_skill("a", content="x"*300, usage=10))
        self.r.add_skill(_make_skill("b", content="y"))
        scores = self.r.score_all()
        totals = [s.total for s in scores]
        assert totals == sorted(totals, reverse=True)

    def test_find_duplicates(self):
        content = "Python is a great programming language for data science"
        self.r.add_skill(_make_skill("d1", content=content))
        self.r.add_skill(_make_skill("d2", content=content + " and AI"))
        dups = self.r.find_duplicates()
        assert len(dups) >= 1

    def test_no_duplicates_different_content(self):
        self.r.add_skill(_make_skill("x1", content="苹果香蕉橙子"))
        self.r.add_skill(_make_skill("x2", content="Python Django Flask REST"))
        dups = self.r.find_duplicates()
        assert len(dups) == 0

    def test_find_stale_skills(self):
        stale = _make_skill("st", content="短", days_old=31)
        self.r.add_skill(stale)
        dead = self.r.find_stale_skills()
        assert any(s.skill_id == "st" for s in dead)

    def test_fresh_skill_not_stale(self):
        fresh = _make_skill("fr", content="短", days_old=0)
        self.r.add_skill(fresh)
        dead = self.r.find_stale_skills()
        assert not any(s.skill_id == "fr" for s in dead)

    def test_high_score_not_stale_even_if_old(self):
        """高分技能即使30天未用也不应被截断（评分>=30）。"""
        s = _make_skill("hs", content="x"*200, usage=5, days_old=40)
        self.r.add_skill(s)
        dead = self.r.find_stale_skills()
        assert not any(sk.skill_id == "hs" for sk in dead)

    def test_prune_stale_skills(self):
        self.r.add_skill(_make_skill("pr", content="短", days_old=35))
        removed = self.r.prune_stale_skills()
        assert removed >= 1
        assert self.r.get_skill("pr") is None

    def test_generate_report_empty(self):
        report = self.r.generate_report()
        assert report["total_skills"] == 0
        assert report["average_score"] == 0

    def test_generate_report_structure(self):
        self.r.add_skill(_make_skill("r1", content="x"*100, usage=3))
        report = self.r.generate_report()
        for k in ("total_skills","average_score","max_score","min_score",
                  "duplicate_groups","stale_skill_count","top_skills"):
            assert k in report

    def test_jaccard_identical(self):
        tokens = {"a","b","c"}
        assert self.r._jaccard(tokens, tokens) == 1.0

    def test_jaccard_disjoint(self):
        assert self.r._jaccard({"a","b"}, {"c","d"}) == 0.0

    def test_jaccard_empty(self):
        assert self.r._jaccard(set(), {"a"}) == 0.0

    def test_repr(self):
        assert "SkillReviewer" in repr(self.r)


# ── ProgressiveSkillLoader ────────────────────────────────────────────────────
from executor.progressive_loader import ProgressiveSkillLoader, CachedSkill

class TestProgressiveSkillLoader:
    def test_register_and_get(self, tmp_path):
        pl = ProgressiveSkillLoader(cache_path=tmp_path/"cache.json")
        pl.register("sk1","Skill1","content")
        s = pl.get("sk1")
        assert s is not None
        assert s.name == "Skill1"

    def test_get_expired_returns_none(self, tmp_path):
        pl = ProgressiveSkillLoader(cache_path=tmp_path/"c.json", cache_duration=0.001)
        pl.register("exp","Exp","data")
        time.sleep(0.01)
        assert pl.get("exp") is None

    def test_usage_count_increments(self, tmp_path):
        pl = ProgressiveSkillLoader(cache_path=tmp_path/"c.json")
        pl.register("sk2","S","c")
        pl.get("sk2")
        pl.get("sk2")
        s = pl._skills["sk2"]
        assert s.usage_count == 2

    def test_priority_boost_on_threshold(self, tmp_path):
        pl = ProgressiveSkillLoader(cache_path=tmp_path/"c.json", priority_boost_threshold=3)
        pl.register("sk3","S","c", priority=5)
        for _ in range(3):
            pl.get("sk3")
        assert pl._skills["sk3"].priority > 5

    def test_priority_capped_at_10(self, tmp_path):
        pl = ProgressiveSkillLoader(cache_path=tmp_path/"c.json", priority_boost_threshold=1)
        pl.register("sk4","S","c", priority=9)
        for _ in range(20):
            pl.get("sk4")
        assert pl._skills["sk4"].priority <= 10

    def test_cleanup_expired(self, tmp_path):
        pl = ProgressiveSkillLoader(cache_path=tmp_path/"c.json", cache_duration=0.001)
        pl.register("exp2","E","c")
        time.sleep(0.02)
        removed = pl.cleanup()
        assert removed >= 1

    def test_cleanup_stale(self, tmp_path):
        pl = ProgressiveSkillLoader(cache_path=tmp_path/"c.json", cleanup_interval=0.001)
        pl.register("stale","S","c")
        time.sleep(0.02)
        removed = pl.cleanup()
        assert removed >= 1

    def test_top_skills_sorted(self, tmp_path):
        pl = ProgressiveSkillLoader(cache_path=tmp_path/"c.json")
        pl.register("a","A","c",priority=3)
        pl.register("b","B","c",priority=7)
        tops = pl.top_skills(2)
        assert tops[0].priority >= tops[1].priority

    def test_save_and_load_from_disk(self, tmp_path):
        path = tmp_path/"cache.json"
        pl1 = ProgressiveSkillLoader(cache_path=path)
        pl1.register("persist","P","content")
        pl1.save_to_disk()
        pl2 = ProgressiveSkillLoader(cache_path=path)
        assert "persist" in pl2._skills

    def test_broken_cache_file_handled(self, tmp_path):
        path = tmp_path/"bad.json"
        path.write_text("not json{")
        pl = ProgressiveSkillLoader(cache_path=path)
        assert len(pl._skills) == 0

    def test_stats_structure(self, tmp_path):
        pl = ProgressiveSkillLoader(cache_path=tmp_path/"c.json")
        pl.register("s","S","c")
        stats = pl.stats()
        assert "cached_skills" in stats
        assert "top_5" in stats

    def test_cached_skill_is_stale(self):
        s = CachedSkill(skill_id="x",name="x",content="c",last_used=time.time()-99999)
        assert s.is_stale(stale_threshold=1)

    def test_cached_skill_not_stale(self):
        s = CachedSkill(skill_id="x",name="x",content="c")
        assert not s.is_stale(stale_threshold=86400)


# ── DeferredToolLoader ────────────────────────────────────────────────────────
from executor.deferred_tool_loader import DeferredToolLoader, ToolInfo

class TestDeferredToolLoader:
    def test_register_and_get(self):
        dtl = DeferredToolLoader()
        dtl.register("my_tool","描述")
        assert dtl.get("my_tool") is not None

    def test_get_nonexistent(self):
        assert DeferredToolLoader().get("ghost") is None

    def test_use_triggers_loader(self):
        called = {"n": 0}
        def loader():
            called["n"] += 1
            return "loaded"
        dtl = DeferredToolLoader()
        dtl.register("t","d", loader=loader)
        result = dtl.use("t")
        assert result == "loaded"
        assert called["n"] == 1

    def test_loader_called_once_cached(self):
        called = {"n": 0}
        def loader():
            called["n"] += 1
            return object()
        dtl = DeferredToolLoader()
        dtl.register("t2","d", loader=loader)
        dtl.use("t2")
        dtl.use("t2")
        assert called["n"] == 1

    def test_usage_count_increments(self):
        dtl = DeferredToolLoader()
        dtl.register("t3","d")
        dtl.use("t3"); dtl.use("t3")
        assert dtl.get("t3").usage_count == 2

    def test_use_nonexistent_returns_none(self):
        dtl = DeferredToolLoader()
        assert dtl.use("ghost") is None

    def test_search_by_name(self):
        dtl = DeferredToolLoader()
        dtl.register("file_read","读取文件")
        results = dtl.search("file")
        assert any(t.name == "file_read" for t in results)

    def test_search_by_description(self):
        dtl = DeferredToolLoader()
        dtl.register("web_fetch","抓取网页内容", category="network")
        results = dtl.search("网页")
        assert len(results) >= 1

    def test_search_limit(self):
        dtl = DeferredToolLoader()
        for i in range(10):
            dtl.register(f"tool_{i}", f"desc_{i}")
        results = dtl.search("tool", limit=3)
        assert len(results) <= 3

    def test_list_by_category(self):
        dtl = DeferredToolLoader()
        dtl.register("io_tool","io", category="io")
        dtl.register("net_tool","net", category="network")
        io_tools = dtl.list_by_category("io")
        assert all(t.category == "io" for t in io_tools)

    def test_register_builtin_18_tools(self):
        dtl = DeferredToolLoader()
        dtl.register_builtin_tools()
        assert len(dtl._tools) == 18

    def test_top_tools_sorted_by_usage(self):
        dtl = DeferredToolLoader()
        dtl.register("a","a"); dtl.register("b","b")
        dtl.use("a"); dtl.use("a"); dtl.use("b")
        tops = dtl.top_tools(2)
        assert tops[0].name == "a"

    def test_stats_structure(self):
        dtl = DeferredToolLoader()
        dtl.register_builtin_tools()
        stats = dtl.stats()
        assert stats["registered"] == 18
        assert "loaded" in stats
        assert "top_tools" in stats

    def test_tool_is_loaded_flag(self):
        dtl = DeferredToolLoader()
        dtl.register("lazy","d", loader=lambda: "x")
        assert not dtl.get("lazy").is_loaded
        dtl.use("lazy")
        assert dtl.get("lazy").is_loaded

    def test_tool_to_dict(self):
        dtl = DeferredToolLoader()
        dtl.register("t","desc", category="io")
        d = dtl.get("t").to_dict()
        assert d["name"] == "t"
        assert d["category"] == "io"


# ── WorkflowEngine ────────────────────────────────────────────────────────────
from workflow.engine import WorkflowEngine
from workflow.step import WorkflowStep, StepStatus

class TestWorkflowStep:
    def test_run_success(self):
        step = WorkflowStep(name="s",action="a",executor=lambda: "ok")
        result = step.run()
        assert result == "ok"
        assert step.status == StepStatus.COMPLETED

    def test_run_failure(self):
        def fail(): raise RuntimeError("boom")
        step = WorkflowStep(name="s",action="a",executor=fail)
        with pytest.raises(RuntimeError):
            step.run()
        assert step.status == StepStatus.FAILED
        assert step.error == "boom"

    def test_run_no_executor_raises(self):
        step = WorkflowStep(name="s",action="a",executor=None)
        with pytest.raises(ValueError):
            step.run()

    def test_to_dict(self):
        step = WorkflowStep(name="s",action="a",executor=lambda: None)
        d = step.to_dict()
        assert d["name"] == "s"
        assert d["status"] == "pending"

class TestWorkflowEngine:
    def test_run_all_steps(self):
        wf = WorkflowEngine()
        wf.register("add", lambda x,y: x+y)
        wf.add_step("step1","add",x=1,y=2)
        results = wf.run()
        assert results["step1"] == 3

    def test_pause_stops_execution(self):
        wf = WorkflowEngine()
        executed = []
        wf.register("act", lambda n: executed.append(n))
        wf.add_step("a","act",n="a")
        wf.add_step("b","act",n="b")
        wf.pause()
        wf.run()
        assert "a" not in executed

    def test_resume_continues(self):
        wf = WorkflowEngine()
        results = []
        wf.register("act", lambda v: results.append(v))
        wf.add_step("s1","act",v=1)
        wf.add_step("s2","act",v=2)
        wf.pause()
        wf.run()
        wf.resume()
        assert 1 in results

    def test_skip_completed_steps(self):
        wf = WorkflowEngine()
        count = {"n": 0}
        def act(): count["n"] += 1
        wf.register("act", act)
        step = wf.add_step("s","act")
        step.status = StepStatus.COMPLETED
        wf.run()
        assert count["n"] == 0

    def test_checkpoint_saved(self, tmp_path):
        wf = WorkflowEngine(checkpoint_dir=tmp_path)
        wf.register("act", lambda: "done")
        wf.add_step("s","act")
        wf.run()
        files = list(tmp_path.glob("*.json"))
        assert len(files) == 1

    def test_stats_structure(self):
        wf = WorkflowEngine()
        wf.register("act", lambda: None)
        wf.add_step("s","act")
        stats = wf.stats()
        assert "total_steps" in stats
        assert "completed" in stats
        assert "paused" in stats

    def test_step_failure_stops_workflow(self):
        wf = WorkflowEngine()
        executed = []
        wf.register("fail", lambda: (_ for _ in ()).throw(RuntimeError("err")))
        wf.register("ok", lambda: executed.append("ok"))
        wf.add_step("bad","fail")
        wf.add_step("good","ok")
        wf.run()
        assert "ok" not in executed

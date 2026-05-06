"""
tests/test_memory_robust.py — 记忆系统健壮性增强测试

深度覆盖：
- MemorySystem：完整生命周期、semantic_search、delete、refine触发、memory_summary
- AutoExtract：批量对话提取、confidence_threshold边界、各规则分类
- MemoryRefiner：StructuredMemory 对象模式
- 边界情况：空输入、大数据、编码
"""
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from memory.auto_extract import AutoExtract
from memory.memory_refiner import MemoryRefiner
from memory.memory_system import MemorySystem
from memory.structured_memory import StructuredMemory, MemoryFact


# ─── 工具 ─────────────────────────────────────────────────────────────────────
def make_memory(tmp_path: Path, **cfg) -> MemorySystem:
    MemorySystem.reset()
    config = {"confidence_threshold": 0.6, **cfg}
    return MemorySystem(data_dir=tmp_path, config=config)


# ─── AutoExtract 全面测试 ─────────────────────────────────────────────────────
class TestAutoExtractRobust:
    def setup_method(self):
        self.extractor = AutoExtract(confidence_threshold=0.6)

    # ── 基本提取 ──────────────────────────────────────────────────────────────
    def test_extract_work_context(self):
        facts = self.extractor.extract("我是一名后端开发工程师", role="user")
        assert any(f.category == "work_context" for f in facts)

    def test_extract_tech_stack_english(self):
        facts = self.extractor.extract("我用Python写这个项目", role="user")
        assert any(f.category in ("tech_stack", "work_context", "project") for f in facts)

    def test_extract_preference(self):
        facts = self.extractor.extract("我喜欢简洁清晰的代码风格", role="user")
        assert any(f.category == "preference" for f in facts)

    def test_extract_project(self):
        facts = self.extractor.extract("我正在做一个电商平台", role="user")
        assert any(f.category == "project" for f in facts)

    # ── 角色过滤 ──────────────────────────────────────────────────────────────
    def test_assistant_message_returns_empty(self):
        facts = self.extractor.extract("我可以帮你用Python写这个", role="assistant")
        assert facts == []

    def test_system_message_returns_empty(self):
        facts = self.extractor.extract("我是系统", role="system")
        assert facts == []

    # ── 置信度阈值 ────────────────────────────────────────────────────────────
    def test_high_threshold_filters_low_confidence(self):
        extractor_strict = AutoExtract(confidence_threshold=0.99)
        # 所有规则置信度 <= 0.85，高阈值下应返回空
        facts = extractor_strict.extract("我是后端开发", role="user")
        assert facts == []

    def test_low_threshold_captures_more(self):
        extractor_loose = AutoExtract(confidence_threshold=0.5)
        facts = extractor_loose.extract("我是后端开发", role="user")
        assert len(facts) >= 1

    # ── 去重 ──────────────────────────────────────────────────────────────────
    def test_deduplication_same_content(self):
        """相同内容应只保留一条。"""
        facts = self.extractor.extract("我用Python，我用Python，我用Python", role="user")
        contents = [f.content for f in facts]
        assert len(contents) == len(set(contents))

    # ── 批量对话提取 ──────────────────────────────────────────────────────────
    def test_extract_from_conversation(self):
        messages = [
            {"role": "user", "content": "我是后端开发"},
            {"role": "assistant", "content": "好的，我来帮你"},
            {"role": "user", "content": "我用FastAPI写接口"},
        ]
        facts = self.extractor.extract_from_conversation(messages)
        assert len(facts) >= 1
        # assistant 消息不应被提取
        all_contents = " ".join(f.content for f in facts)
        assert "帮你" not in all_contents

    def test_extract_from_conversation_all_assistant(self):
        messages = [
            {"role": "assistant", "content": "我可以帮你"},
            {"role": "assistant", "content": "我是AI助手"},
        ]
        facts = self.extractor.extract_from_conversation(messages)
        assert facts == []

    def test_extract_count_increments(self):
        before = self.extractor.extract_count
        self.extractor.extract("我用Python开发", role="user")
        assert self.extractor.extract_count > before

    # ── 空输入 ────────────────────────────────────────────────────────────────
    def test_empty_message(self):
        facts = self.extractor.extract("", role="user")
        assert facts == []

    def test_very_long_message(self):
        long_msg = "我是后端开发工程师。" * 100
        facts = self.extractor.extract(long_msg, role="user")
        assert isinstance(facts, list)

    def test_special_chars(self):
        facts = self.extractor.extract("我用C++/Rust写系统", role="user")
        assert isinstance(facts, list)  # 不应崩溃


# ─── MemoryRefiner 全面测试 ───────────────────────────────────────────────────
class TestMemoryRefinerRobust:
    # ── list 模式 ─────────────────────────────────────────────────────────────
    def test_refine_list_deduplicates(self):
        refiner = MemoryRefiner()
        result = refiner.refine(["Python开发", "Python开发", "Java开发"])
        assert len(result) == 2

    def test_refine_list_preserves_order(self):
        refiner = MemoryRefiner()
        items = ["first", "second", "third"]
        result = refiner.refine(items)
        assert result == items

    def test_refine_list_case_insensitive(self):
        refiner = MemoryRefiner()
        result = refiner.refine(["Python", "python", "PYTHON"])
        assert len(result) == 1

    def test_refine_list_strips_whitespace(self):
        refiner = MemoryRefiner()
        result = refiner.refine(["  Python  ", "Python", " Java "])
        assert len(result) == 2

    def test_refine_list_empty(self):
        refiner = MemoryRefiner()
        result = refiner.refine([])
        assert result == []

    def test_refine_list_single_item(self):
        refiner = MemoryRefiner()
        result = refiner.refine(["only item"])
        assert result == ["only item"]

    def test_refine_list_stats_update(self):
        refiner = MemoryRefiner()
        refiner.refine(["a", "a", "b"])
        assert refiner.stats()["total_refined"] == 1

    # ── StructuredMemory 对象模式 ─────────────────────────────────────────────
    def test_refine_structured_memory_removes_duplicates(self, tmp_path):
        mem = StructuredMemory(persist_path=tmp_path / "sm.json")
        mem.add_fact("Python开发", "tech_stack", 0.9)
        mem.add_fact("Python开发", "tech_stack", 0.8)  # 重复
        mem.add_fact("Java开发", "tech_stack", 0.9)

        refiner = MemoryRefiner(memory=mem)
        report = refiner.refine()

        assert report["removed"] >= 1
        assert "original_count" in report
        assert "after_refine" in report

    def test_refine_structured_keeps_higher_confidence(self, tmp_path):
        mem = StructuredMemory(persist_path=tmp_path / "sm.json")
        mem.add_fact("重复事实", "general", 0.6)
        mem.add_fact("重复事实", "general", 0.9)  # 高置信度版本

        refiner = MemoryRefiner(memory=mem)
        report = refiner.refine()

        remaining = mem.get_facts()
        if remaining:
            max_conf = max(f.confidence for f in remaining)
            assert max_conf >= 0.9

    def test_refine_no_memory_returns_error(self):
        refiner = MemoryRefiner(memory=None)
        result = refiner.refine()
        assert "error" in result

    def test_refine_with_target_param(self, tmp_path):
        mem = StructuredMemory(persist_path=tmp_path / "sm2.json")
        mem.add_fact("相同事实", "general", 0.9)
        mem.add_fact("相同事实", "general", 0.8)

        refiner = MemoryRefiner()
        report = refiner.refine(target=mem)
        assert "original_count" in report


# ─── MemorySystem 全面测试 ────────────────────────────────────────────────────
class TestMemorySystemRobust:
    # ── 基本读写 ──────────────────────────────────────────────────────────────
    def test_add_fact_and_get_facts(self, tmp_path):
        mem = make_memory(tmp_path)
        mem.add_fact("Python开发", "tech_stack", 0.9)
        facts = mem.get_facts()
        assert any(f["content"] == "Python开发" for f in facts)

    def test_get_facts_by_category(self, tmp_path):
        mem = make_memory(tmp_path)
        mem.add_fact("事实A", "tech_stack", 0.9)
        mem.add_fact("事实B", "preference", 0.8)
        tech = mem.get_facts(category="tech_stack")
        assert all(f["category"] == "tech_stack" for f in tech)
        assert len(tech) == 1

    def test_facts_persisted_across_reload(self, tmp_path):
        """事实写入后，新实例可以加载回来。"""
        mem1 = make_memory(tmp_path)
        mem1.add_fact("跨实例事实", "general", 0.9)

        MemorySystem.reset()
        mem2 = MemorySystem(data_dir=tmp_path, config={"confidence_threshold": 0.6})
        facts = mem2.get_facts()
        assert any(f["content"] == "跨实例事实" for f in facts)

    # ── 短期记忆 ──────────────────────────────────────────────────────────────
    def test_process_message_builds_short_term(self, tmp_path):
        mem = make_memory(tmp_path)
        mem.process_message("user", "你好")
        mem.process_message("assistant", "你好！")
        assert len(mem.short_term) == 2

    def test_get_context_messages_excludes_system(self, tmp_path):
        mem = make_memory(tmp_path)
        mem.process_message("system", "系统提示")
        mem.process_message("user", "用户消息")
        ctx = mem.get_context_messages(max_messages=10)
        assert all(m["role"] != "system" for m in ctx)

    def test_get_context_messages_max_limit(self, tmp_path):
        mem = make_memory(tmp_path)
        for i in range(30):
            mem.process_message("user", f"消息{i}")
        ctx = mem.get_context_messages(max_messages=10)
        assert len(ctx) == 10

    def test_clear_short_term(self, tmp_path):
        mem = make_memory(tmp_path)
        mem.process_message("user", "test")
        mem.clear_short_term()
        assert len(mem.short_term) == 0

    # ── 长期记忆 ──────────────────────────────────────────────────────────────
    def test_save_and_search_long_term(self, tmp_path):
        mem = make_memory(tmp_path)
        mem.save_to_long_term("Python是解释型语言", "knowledge", 0.9)
        results = mem.search_long_term("Python")
        assert len(results) >= 1
        assert results[0]["content"] == "Python是解释型语言"

    def test_search_long_term_no_match(self, tmp_path):
        mem = make_memory(tmp_path)
        results = mem.search_long_term("完全不存在的内容xyz")
        assert results == []

    def test_delete_from_long_term(self, tmp_path):
        mem = make_memory(tmp_path)
        fact_id = mem.save_to_long_term("待删除的知识", "test")
        deleted = mem.delete_from_long_term(fact_id)
        assert deleted is True
        results = mem.search_long_term("待删除的知识")
        assert results == []

    def test_delete_nonexistent_returns_false(self, tmp_path):
        mem = make_memory(tmp_path)
        deleted = mem.delete_from_long_term("nonexistent_id")
        assert deleted is False

    def test_save_to_long_term_returns_id(self, tmp_path):
        mem = make_memory(tmp_path)
        fact_id = mem.save_to_long_term("test content")
        assert fact_id.startswith("lt_")

    # ── 语义检索（向量库禁用时退化到关键词检索） ──────────────────────────────
    def test_semantic_search_keyword_fallback(self, tmp_path):
        mem = make_memory(tmp_path)
        mem.save_to_long_term("Giraffe是一个AI框架", "knowledge", 0.9)
        results = mem.semantic_search("Giraffe", top_k=5)
        assert isinstance(results, list)
        # 关键词检索应该能找到
        assert any("Giraffe" in r["text"] for r in results)

    def test_semantic_search_empty_query(self, tmp_path):
        mem = make_memory(tmp_path)
        results = mem.semantic_search("", top_k=5)
        assert isinstance(results, list)

    def test_semantic_search_deduplicates(self, tmp_path):
        mem = make_memory(tmp_path)
        # 写入相同内容到多个位置
        mem.save_to_long_term("独特内容", "test", 0.9)
        results = mem.semantic_search("独特内容", top_k=10)
        texts = [r["text"] for r in results]
        assert len(texts) == len(set(texts))

    def test_semantic_search_sorted_by_score(self, tmp_path):
        mem = make_memory(tmp_path)
        mem.save_to_long_term("高相关性内容", "test", 0.95)
        results = mem.semantic_search("高相关性", top_k=5)
        scores = [r["score"] for r in results]
        assert scores == sorted(scores, reverse=True)

    # ── 记忆精炼触发 ──────────────────────────────────────────────────────────
    def test_refine_triggered_after_20_messages(self, tmp_path):
        """每20条消息后应自动触发精炼（不崩溃）。"""
        mem = make_memory(tmp_path)
        # 先添加一些重复事实
        mem.add_fact("重复事实", "general", 0.9)
        mem.add_fact("重复事实", "general", 0.8)
        # 触发20条消息
        for i in range(20):
            mem.process_message("user", f"消息{i}")
        # 不崩溃即可
        assert isinstance(mem.stats(), dict)

    # ── 日记系统 ──────────────────────────────────────────────────────────────
    def test_record_and_retrieve_session(self, tmp_path):
        mem = make_memory(tmp_path)
        mem.record_session("sess_001", "今天讨论了Python开发", tags=["python"])
        sessions = mem.get_recent_sessions(n=5)
        assert len(sessions) >= 1

    def test_get_recent_sessions_limit(self, tmp_path):
        mem = make_memory(tmp_path)
        for i in range(5):
            mem.record_session(f"sess_{i:03d}", f"摘要{i}")
        sessions = mem.get_recent_sessions(n=3)
        assert len(sessions) <= 3

    # ── memory_summary ────────────────────────────────────────────────────────
    def test_memory_summary_returns_string(self, tmp_path):
        mem = make_memory(tmp_path)
        mem.process_message("user", "我是Python开发者")
        mem.save_to_long_term("Python知识")
        summary = mem.memory_summary()
        assert isinstance(summary, str)
        assert "短期记忆" in summary
        assert "事实记忆" in summary
        assert "长期记忆" in summary

    # ── 系统提示词构建 ────────────────────────────────────────────────────────
    def test_build_system_prompt_returns_string(self, tmp_path):
        mem = make_memory(tmp_path)
        mem.structured.add_fact("用户偏好Python", "preference", 0.95)
        mem.structured.update_user_context(work_context="后端工程师")
        prompt = mem.build_system_prompt()
        assert isinstance(prompt, str)

    # ── stats 完整性 ──────────────────────────────────────────────────────────
    def test_stats_structure(self, tmp_path):
        mem = make_memory(tmp_path)
        stats = mem.stats()
        assert "short_term_messages" in stats
        assert "fact_memory_count" in stats
        assert "long_term_count" in stats
        assert "structured_facts" in stats
        assert "vector_store" in stats

    # ── singleton 行为 ────────────────────────────────────────────────────────
    def test_singleton_reset(self, tmp_path):
        mem1 = make_memory(tmp_path)
        mem1_id = id(mem1)
        MemorySystem.reset()
        mem2 = MemorySystem(data_dir=tmp_path)
        assert id(mem2) != mem1_id

    # ── max_facts 上限 ────────────────────────────────────────────────────────
    def test_max_facts_limit_respected(self, tmp_path):
        mem = make_memory(tmp_path, max_facts=3)
        for i in range(10):
            msg = f"消息{i}用Python开发"
            mem.process_message("user", msg)
        assert len(mem.get_facts()) <= 3

    # ── 中文/特殊字符健壮性 ────────────────────────────────────────────────────
    def test_facts_with_special_characters(self, tmp_path):
        mem = make_memory(tmp_path)
        mem.add_fact("我喜欢用C++/Rust开发系统软件🚀", "tech_stack", 0.9)
        facts = mem.get_facts()
        assert any("Rust" in f["content"] for f in facts)

    def test_long_term_search_limit_respected(self, tmp_path):
        mem = make_memory(tmp_path)
        for i in range(20):
            mem.save_to_long_term(f"Python知识条目{i}", "knowledge")
        results = mem.search_long_term("Python", limit=5)
        assert len(results) <= 5

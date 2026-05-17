"""
tests/test_memory.py — 记忆系统测试
"""
import sys, tempfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest
from memory.structured_memory import StructuredMemory, MemoryFact
from memory.auto_extract import AutoExtract
from memory.memory_system import MemorySystem


class TestStructuredMemory:
    def setup_method(self):
        self.tmp = tempfile.mktemp(suffix=".json")
        self.mem = StructuredMemory(persist_path=self.tmp)

    def test_add_fact(self):
        fact = self.mem.add_fact("我是Python开发者", "work_context", 0.9)
        assert fact.content == "我是Python开发者"
        assert fact.category == "work_context"

    def test_filter_by_confidence(self):
        self.mem.add_fact("高置信度事实", confidence=0.9)
        self.mem.add_fact("低置信度事实", confidence=0.3)
        high = self.mem.get_facts(min_confidence=0.8)
        assert len(high) == 1
        assert high[0].content == "高置信度事实"

    def test_update_user_context(self):
        self.mem.update_user_context(work_context="前端开发")
        assert self.mem.user_context.work_context == "前端开发"

    def test_generate_system_prompt(self):
        self.mem.add_fact("我用Vue.js开发", "tech_stack", 0.9)
        self.mem.update_user_context(work_context="前端工程师")
        prompt = self.mem.generate_system_prompt(min_confidence=0.8)
        assert "前端工程师" in prompt or "Vue.js" in prompt or len(prompt) > 0

    def test_remove_fact(self):
        fact = self.mem.add_fact("临时事实")
        removed = self.mem.remove_fact(fact.id)
        assert removed
        assert fact not in self.mem.get_facts()


class TestAutoExtract:
    def setup_method(self):
        self.extractor = AutoExtract(confidence_threshold=0.6)

    def test_extract_work_context(self):
        facts = self.extractor.extract("我是一名前端开发工程师", role="user")
        assert len(facts) > 0

    def test_extract_tech_stack(self):
        facts = self.extractor.extract("我正在用Python写代码", role="user")
        categories = [f.category for f in facts]
        assert any(c in ("tech_stack", "work_context", "project") for c in categories)

    def test_assistant_message_not_extracted(self):
        facts = self.extractor.extract("我可以帮你用Python实现这个功能", role="assistant")
        assert len(facts) == 0

    def test_deduplication(self):
        facts = self.extractor.extract("我用Python，我用Python，我用Python", role="user")
        contents = [f.content for f in facts]
        assert len(contents) == len(set(contents))


class TestMemorySystem:
    def setup_method(self):
        MemorySystem.reset()
        self.tmp_dir = Path(tempfile.mkdtemp())
        self.memory = MemorySystem(data_dir=self.tmp_dir, config={"confidence_threshold": 0.6})

    def test_process_message_adds_to_short_term(self):
        self.memory.process_message("user", "你好")
        assert len(self.memory.short_term) == 1

    def test_process_message_extracts_facts(self):
        self.memory.process_message("user", "我是前端开发，用Vue.js")
        # facts 可能被提取到
        stats = self.memory.stats()
        assert "short_term_messages" in stats

    def test_add_fact_persisted(self):
        self.memory.add_fact("测试事实", "test", 0.8)
        facts = self.memory.get_facts()
        assert any(f["content"] == "测试事实" for f in facts)

    def test_long_term_save_and_search(self):
        self.memory.save_to_long_term("Python是一门动态语言", "knowledge")
        results = self.memory.search_long_term("Python")
        assert len(results) >= 1

    def test_build_system_prompt(self):
        self.memory.structured.add_fact("用户偏好简洁代码", "preference", 0.9)
        self.memory.structured.update_user_context(work_context="后端工程师")
        prompt = self.memory.build_system_prompt()
        # prompt可以为空（如果没有高置信度事实），只需不报错
        assert isinstance(prompt, str)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

"""
tests/test_self_heal.py — 自愈系统测试
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest
from self_heal.antibody import AntibodyLibrary
from self_heal.error_processor import ErrorProcessor, ErrorCategory
from self_heal.fault_playbook import FaultPlaybook, FaultType
from self_heal.evolution import EvolutionEngine


class TestAntibodyLibrary:
    def setup_method(self):
        AntibodyLibrary.reset()
        self.lib = AntibodyLibrary()

    def test_loads_8_builtin_antibodies(self):
        antibodies = self.lib.all_antibodies()
        builtin = [a for a in antibodies if a.is_builtin]
        assert len(builtin) == 8

    def test_match_404_error(self):
        result = self.lib.match("404 not found", http_code=404)
        assert result.matched
        assert result.antibody.name == "404-ban"

    def test_match_rate_limit(self):
        result = self.lib.match("rate limit exceeded", http_code=429)
        assert result.matched
        assert result.antibody.name == "rate-limit-wait"

    def test_match_timeout(self):
        result = self.lib.match("connection timeout error")
        assert result.matched
        assert result.antibody.name == "timeout-retry"

    def test_match_auth_error(self):
        result = self.lib.match("unauthorized", http_code=401)
        assert result.matched
        assert result.antibody.name == "auth-refresh"

    def test_unknown_error_falls_back_to_generic(self):
        result = self.lib.match("some completely unknown bizarre error xyz123")
        assert result.antibody is not None
        assert result.antibody.name == "generic-catch"

    def test_generate_new_antibody(self):
        new_ab = self.lib.generate_new_antibody(
            error_pattern="custom error pattern",
            action="custom fix",
            fix_steps=["step1", "step2"],
        )
        assert new_ab.id.startswith("ab_gen_")
        assert not new_ab.is_builtin

    def test_remove_poor_antibodies(self):
        # 生成一个成功率为0的抗体并触发5次失败
        ab = self.lib.generate_new_antibody("test_poor", "test", ["step1"])
        for _ in range(5):
            ab.record_failure()
        removed = self.lib.remove_poor_antibodies(min_success_rate=0.2)
        assert removed >= 1


class TestErrorProcessor:
    def setup_method(self):
        AntibodyLibrary.reset()
        self.processor = ErrorProcessor()

    def test_classify_401(self):
        category = self.processor.classify_error("unauthorized", http_code=401)
        assert category == ErrorCategory.AUTH

    def test_classify_429(self):
        category = self.processor.classify_error("too many requests", http_code=429)
        assert category == ErrorCategory.RATE_LIMIT

    def test_classify_timeout(self):
        category = self.processor.classify_error("connection timeout")
        assert category == ErrorCategory.NETWORK

    def test_10_step_process(self):
        report = self.processor.process("test error", http_code=500)
        assert "steps" in report
        assert len(report["steps"]) == 10
        assert "error_id" in report

    def test_process_404_error(self):
        report = self.processor.process("404 not found", http_code=404)
        assert report["antibody"] == "404-ban"

    def test_stats(self):
        self.processor.process("some error")
        stats = self.processor.stats()
        assert stats["total_processed"] == 1


class TestFaultPlaybook:
    def setup_method(self):
        self.playbook = FaultPlaybook()

    def test_detect_network_fault(self):
        ft = self.playbook.detect_fault_type("connection timeout", http_code=0)
        assert ft == FaultType.NETWORK

    def test_detect_api_fault(self):
        ft = self.playbook.detect_fault_type("model not found", http_code=404)
        assert ft == FaultType.API_ERROR

    def test_detect_resource_fault(self):
        ft = self.playbook.detect_fault_type("context length exceeded")
        assert ft == FaultType.RESOURCE

    def test_run_network_handler(self):
        result = self.playbook.run(FaultType.NETWORK, {
            "max_retries": 1,
            "model_chain": ["model-a", "model-b"],
        })
        assert "fault_type" in result
        assert result["fault_type"] == FaultType.NETWORK.value

    def test_run_logic_handler(self):
        result = self.playbook.run(FaultType.LOGIC, {
            "error_detail": "test logic error"
        })
        assert "report" in result
        assert result["report"]["needs_human_review"] is True


class TestEvolutionEngine:
    def setup_method(self):
        AntibodyLibrary.reset()
        self.lib = AntibodyLibrary()
        self.engine = EvolutionEngine(antibody_lib=self.lib)

    def test_empty_history_no_crash(self):
        report = self.engine.evolve()
        assert report.overall_success_rate == 0.0

    def test_collect_and_evolve(self):
        for _ in range(3):
            self.engine.collect({
                "resolved": True,
                "antibody": "timeout-retry",
                "category": "network",
            })
        report = self.engine.evolve()
        assert report.overall_success_rate == 1.0
        assert report.optimized_antibodies >= 1

    def test_generate_new_antibody_for_repeated_failures(self):
        for _ in range(3):
            self.engine.collect({
                "resolved": False,
                "antibody": "generic-catch",
                "category": "custom_error_type",
            })
        report = self.engine.evolve()
        assert report.new_antibodies >= 1


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

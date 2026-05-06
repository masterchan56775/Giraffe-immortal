"""CompatReport — 兼容性报告"""
from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime

@dataclass
class CompatReport:
    """Hermes版本兼容性报告。"""
    generated_at: str = field(default_factory=lambda: datetime.now().isoformat())
    compatible: bool = True
    issues: list[str] = field(default_factory=list)
    recommendations: list[str] = field(default_factory=list)

    def add_issue(self, issue: str) -> None:
        self.issues.append(issue)
        self.compatible = False

    def add_recommendation(self, rec: str) -> None:
        self.recommendations.append(rec)

    def to_dict(self) -> dict:
        return {
            "generated_at": self.generated_at,
            "compatible": self.compatible,
            "issues": self.issues,
            "recommendations": self.recommendations,
        }

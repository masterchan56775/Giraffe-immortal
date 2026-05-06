"""
GuardrailMiddleware — 中间件护栏
危险命令拦截 + 密钥泄露检测 + 预算限制检查
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from enum import Enum
from typing import Callable

logger = logging.getLogger(__name__)


class GuardrailSeverity(str, Enum):
    INFO    = "info"
    WARNING = "warning"
    BLOCK   = "block"    # 阻止执行


@dataclass
class GuardrailResult:
    passed: bool
    severity: GuardrailSeverity
    guardrail_name: str
    message: str
    matched: str = ""

    @property
    def should_block(self) -> bool:
        return not self.passed and self.severity == GuardrailSeverity.BLOCK


# ─── 3个内置护栏 ────────────────────────────────────────────────────────────

# 护栏1：危险命令拦截
DANGEROUS_COMMANDS = [
    r"rm\s+-rf",
    r"curl\s+.*\|\s*(bash|sh)",
    r"wget\s+.*\|\s*(bash|sh)",
    r"format\s+[a-z]:",
    r"dd\s+if=.*of=",
    r"mkfs",
    r":\(\)\{.*\}",  # fork bomb
    r"chmod\s+777\s+/",
]

# 护栏2：密钥泄露检测
SECRET_PATTERNS = [
    r"sk-[a-zA-Z0-9]{20,}",           # OpenAI API Key
    r"[a-zA-Z0-9]{32,}\.secret",
    r"api[_-]?key\s*[=:]\s*['\"]?[a-zA-Z0-9\-_]{16,}",
    r"password\s*[=:]\s*['\"]?.{8,}",
    r"token\s*[=:]\s*['\"]?[a-zA-Z0-9\-_.]{16,}",
]


def check_no_dangerous_commands(content: str) -> GuardrailResult:
    """护栏1：拦截危险命令。"""
    for pattern in DANGEROUS_COMMANDS:
        match = re.search(pattern, content, re.I)
        if match:
            return GuardrailResult(
                passed=False,
                severity=GuardrailSeverity.BLOCK,
                guardrail_name="dangerous_command",
                message=f"检测到危险命令，已拦截",
                matched=match.group(0),
            )
    return GuardrailResult(
        passed=True,
        severity=GuardrailSeverity.INFO,
        guardrail_name="dangerous_command",
        message="无危险命令",
    )


def check_no_secrets_leak(content: str) -> GuardrailResult:
    """护栏2：密钥泄露检测。"""
    for pattern in SECRET_PATTERNS:
        match = re.search(pattern, content, re.I)
        if match:
            return GuardrailResult(
                passed=False,
                severity=GuardrailSeverity.BLOCK,
                guardrail_name="secrets_leak",
                message="检测到可能的密钥泄露，已拦截",
                matched=f"[已脱敏:{match.group(0)[:8]}...]",
            )
    return GuardrailResult(
        passed=True,
        severity=GuardrailSeverity.INFO,
        guardrail_name="secrets_leak",
        message="无密钥泄露风险",
    )


def check_budget_limit(
    current_cost: float,
    daily_limit: float = 3.3,
    monthly_limit: float = 100.0,
    daily_cost: float = 0.0,
    monthly_cost: float = 0.0,
) -> GuardrailResult:
    """护栏3：预算限制检查。"""
    if daily_cost + current_cost > daily_limit:
        return GuardrailResult(
            passed=False,
            severity=GuardrailSeverity.BLOCK,
            guardrail_name="budget_limit",
            message=f"日预算超限 (已用${daily_cost:.2f}+${current_cost:.2f} > 限额${daily_limit})",
        )
    if monthly_cost + current_cost > monthly_limit:
        return GuardrailResult(
            passed=False,
            severity=GuardrailSeverity.WARNING,
            guardrail_name="budget_limit",
            message=f"月预算接近上限 (已用${monthly_cost:.2f}+${current_cost:.2f})",
        )
    return GuardrailResult(
        passed=True,
        severity=GuardrailSeverity.INFO,
        guardrail_name="budget_limit",
        message="预算充足",
    )


class GuardrailMiddleware:
    """
    中间件护栏（可插拔）。
    内置3个护栏：危险命令拦截、密钥泄露检测、预算限制。
    支持自定义护栏扩展。
    """

    def __init__(self, config: dict | None = None) -> None:
        cfg = config or {}
        self._enabled = cfg.get("guardrails_enabled", True)
        self._daily_limit = cfg.get("max_budget_daily", 3.3)
        self._monthly_limit = cfg.get("max_budget_monthly", 100.0)
        self._custom_guardrails: list[Callable] = []
        self._block_count = 0

    def check(
        self,
        content: str,
        estimated_cost: float = 0.0,
        daily_cost: float = 0.0,
        monthly_cost: float = 0.0,
    ) -> list[GuardrailResult]:
        """
        运行所有护栏检查。
        返回所有护栏的检查结果列表。
        """
        if not self._enabled:
            return []

        results = [
            check_no_dangerous_commands(content),
            check_no_secrets_leak(content),
            check_budget_limit(
                estimated_cost, self._daily_limit, self._monthly_limit,
                daily_cost, monthly_cost,
            ),
        ]

        # 自定义护栏
        for guardrail in self._custom_guardrails:
            try:
                result = guardrail(content)
                results.append(result)
            except Exception as e:
                logger.error(f"[Guardrail] 自定义护栏错误: {e}")

        blocked = [r for r in results if r.should_block]
        if blocked:
            self._block_count += len(blocked)
            for r in blocked:
                logger.warning(f"[Guardrail] 🚫 {r.guardrail_name}: {r.message}")

        return results

    def is_blocked(self, results: list[GuardrailResult]) -> bool:
        return any(r.should_block for r in results)

    def add_guardrail(self, guardrail_func: Callable) -> None:
        """添加自定义护栏函数。"""
        self._custom_guardrails.append(guardrail_func)

    def stats(self) -> dict:
        return {
            "enabled": self._enabled,
            "block_count": self._block_count,
            "custom_guardrails": len(self._custom_guardrails),
        }

    def __repr__(self) -> str:
        return f"GuardrailMiddleware(enabled={self._enabled}, blocks={self._block_count})"

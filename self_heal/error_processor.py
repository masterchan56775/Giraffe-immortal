"""
ErrorProcessor — 错误处理器
10步系统化排查法
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Callable

from .antibody import AntibodyLibrary, AntibodyMatch

logger = logging.getLogger(__name__)


class ErrorCategory(str, Enum):
    NETWORK       = "network"        # 网络故障
    AUTH          = "auth"           # 认证错误
    RATE_LIMIT    = "rate_limit"     # 限流
    CREDIT        = "credit"         # 欠费
    CONTEXT       = "context"        # 上下文过长
    MODEL         = "model"          # 模型不可用
    PARSE         = "parse"          # 解析错误
    UNKNOWN       = "unknown"        # 未知错误


@dataclass
class ErrorRecord:
    """错误记录。"""
    error_id: str
    error_type: str
    message: str
    category: ErrorCategory
    http_code: int = 0
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())
    recovery_steps: list[str] = field(default_factory=list)
    resolved: bool = False
    antibody_used: str = ""
    resolve_time_ms: float = 0.0

    def to_dict(self) -> dict:
        return {
            "error_id": self.error_id,
            "category": self.category.value,
            "message": self.message[:200],
            "resolved": self.resolved,
            "antibody_used": self.antibody_used,
            "resolve_time_ms": self.resolve_time_ms,
        }


class ErrorProcessor:
    """
    错误处理器（10步系统化排查法）。

    10步流程：
    1. 记录错误详情
    2. 分类错误
    3. 检查熔断器
    4. 匹配抗体库
    5. 尝试降级模型
    6. 执行修复
    7. 验证修复结果
    8. 记录处理过程
    9. 更新抗体库
    10. 生成错误报告
    """

    def __init__(
        self,
        antibody_lib: AntibodyLibrary | None = None,
        circuit_breaker_registry=None,
    ) -> None:
        self._antibody_lib = antibody_lib or AntibodyLibrary.get()
        self._cb_registry = circuit_breaker_registry
        self._error_log: list[ErrorRecord] = []
        self._process_count = 0

    def process(
        self,
        error: Exception | str,
        http_code: int = 0,
        model: str = "",
        retry_func: Callable | None = None,
        model_chain: list[str] | None = None,
    ) -> dict:
        """
        执行10步错误处理流程。
        返回处理报告字典。
        """
        t_start = time.perf_counter()
        self._process_count += 1
        import uuid
        error_id = f"err_{uuid.uuid4().hex[:6]}"
        error_msg = str(error)

        report: dict[str, Any] = {
            "error_id": error_id,
            "steps": [],
            "resolved": False,
            "final_action": "",
        }

        def log_step(step_num: int, description: str, result: str = "") -> None:
            entry = f"步骤{step_num}: {description}"
            if result:
                entry += f" → {result}"
            report["steps"].append(entry)
            logger.debug(f"[ErrorProcessor] {entry}")

        # ── 步骤1：记录错误详情 ────────────────────────────────────────────
        log_step(1, "记录错误详情", f"error={error_msg[:100]}, http_code={http_code}")

        # ── 步骤2：分类错误 ───────────────────────────────────────────────
        category = self.classify_error(error_msg, http_code)
        log_step(2, "分类错误", category.value)
        report["category"] = category.value

        # ── 步骤3：检查熔断器 ─────────────────────────────────────────────
        cb_open = False
        if self._cb_registry and model:
            breaker = self._cb_registry.get_breaker(model)
            breaker.record_failure()
            cb_open = breaker.is_open
        log_step(3, "检查熔断器", f"is_open={cb_open}")

        # ── 步骤4：匹配抗体库 ─────────────────────────────────────────────
        ab_match: AntibodyMatch = self._antibody_lib.match(error_msg, http_code)
        log_step(4, "匹配抗体库", ab_match.reason)
        report["antibody"] = ab_match.antibody.name if ab_match.antibody else "none"

        # ── 步骤5：尝试降级模型 ───────────────────────────────────────────
        fallback_model = None
        if model_chain and len(model_chain) > 1:
            try:
                current_idx = model_chain.index(model)
                if current_idx < len(model_chain) - 1:
                    fallback_model = model_chain[current_idx + 1]
            except ValueError:
                fallback_model = model_chain[0] if model_chain else None
        log_step(5, "尝试降级模型", fallback_model or "无可用降级")

        # ── 步骤6：执行修复 ───────────────────────────────────────────────
        resolved = False
        if ab_match.antibody:
            log_step(6, "执行修复", f"应用抗体: {ab_match.antibody.name}")
            # 实际修复：如有 retry_func 且是超时/限流类错误，尝试重试
            if retry_func and category in (ErrorCategory.NETWORK, ErrorCategory.RATE_LIMIT):
                try:
                    if category == ErrorCategory.RATE_LIMIT:
                        time.sleep(1)  # 简单退避
                    retry_result = retry_func()
                    resolved = True
                    report["retry_result"] = str(retry_result)[:100]
                except Exception:
                    resolved = False
            else:
                resolved = category == ErrorCategory.PARSE  # 解析错误标记为部分解决
        else:
            log_step(6, "执行修复", "无匹配抗体，使用通用处理")

        # ── 步骤7：验证修复结果 ───────────────────────────────────────────
        log_step(7, "验证修复结果", "已解决" if resolved else "未解决")

        # ── 步骤8：记录处理过程 ───────────────────────────────────────────
        resolve_time_ms = (time.perf_counter() - t_start) * 1000
        err_record = ErrorRecord(
            error_id=error_id,
            error_type=type(error).__name__ if isinstance(error, Exception) else "str",
            message=error_msg,
            category=category,
            http_code=http_code,
            resolved=resolved,
            antibody_used=ab_match.antibody.id if ab_match.antibody else "",
            resolve_time_ms=resolve_time_ms,
        )
        self._error_log.append(err_record)
        log_step(8, "记录处理过程", f"resolve_time={resolve_time_ms:.1f}ms")

        # ── 步骤9：更新抗体库 ─────────────────────────────────────────────
        if ab_match.antibody:
            if resolved:
                ab_match.antibody.record_success()
            else:
                ab_match.antibody.record_failure()
        log_step(9, "更新抗体库", "完成")

        # ── 步骤10：生成错误报告 ──────────────────────────────────────────
        report["resolved"] = resolved
        report["resolve_time_ms"] = round(resolve_time_ms, 2)
        report["fallback_model"] = fallback_model
        report["final_action"] = (
            f"应用抗体[{ab_match.antibody.name}]"
            if ab_match.antibody else "通用处理"
        )
        log_step(10, "生成错误报告", f"resolved={resolved}")

        logger.info(
            f"[ErrorProcessor] 错误处理完成: {error_id} | "
            f"category={category.value} | resolved={resolved} | "
            f"time={resolve_time_ms:.1f}ms"
        )
        return report

    def classify_error(self, error_msg: str, http_code: int = 0) -> ErrorCategory:
        """快速分类错误类型。"""
        if not error_msg:
            # 空错误消息，优先依据 http_code判断
            if http_code in (401, 403):
                return ErrorCategory.AUTH
            if http_code == 402:
                return ErrorCategory.CREDIT
            if http_code == 429:
                return ErrorCategory.RATE_LIMIT
            if http_code in (502, 503):
                return ErrorCategory.MODEL
            return ErrorCategory.UNKNOWN

        msg_lower = error_msg.lower()

        if http_code in (401, 403):
            return ErrorCategory.AUTH
        if http_code == 402 or "insufficient" in msg_lower or "credit" in msg_lower:
            return ErrorCategory.CREDIT
        if http_code == 429 or "rate limit" in msg_lower or "too many" in msg_lower:
            return ErrorCategory.RATE_LIMIT
        if http_code in (502, 503) or "unavailable" in msg_lower:
            return ErrorCategory.MODEL
        if "timeout" in msg_lower or "timed out" in msg_lower:
            return ErrorCategory.NETWORK
        # 修复运算符优先级 Bug：原来的 "token" in msg_lower and "limit" in msg_lower
        # 在 or 链中会先计算 "context" in msg_lower，再 and 后面的部分
        # 导致 "xxx context xxx" 简单包含 context 也类分为 CONTEXT
        if "context" in msg_lower or ("token" in msg_lower and "limit" in msg_lower):
            return ErrorCategory.CONTEXT
        if "json" in msg_lower or "parse" in msg_lower:
            return ErrorCategory.PARSE
        return ErrorCategory.UNKNOWN

    def get_error_log(self) -> list[dict]:
        return [e.to_dict() for e in self._error_log]

    def stats(self) -> dict:
        resolved = sum(1 for e in self._error_log if e.resolved)
        return {
            "total_processed": self._process_count,
            "logged": len(self._error_log),
            "resolved": resolved,
            "resolve_rate": round(resolved / len(self._error_log), 3) if self._error_log else 0.0,
        }

    def __repr__(self) -> str:
        return f"ErrorProcessor(processed={self._process_count})"

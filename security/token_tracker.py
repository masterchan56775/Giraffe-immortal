"""
TokenTracker — Token消耗追踪
记录每次API调用的token消耗，按模型/日期/会话统计，支持预算告警
"""
from __future__ import annotations

import logging
from collections import defaultdict
from datetime import datetime

logger = logging.getLogger(__name__)

# 估算每1000 token成本（USD）—— 仅用于预算估算
MODEL_COST_PER_1K: dict[str, float] = {
    # Gemini 系列
    "gemini-3-flash-preview":    0.0005,
    "gemini-3.1-pro-preview":    0.001,
    "gemini-3.1-flash-lite":     0.0002,
    # Claude 系列（连字符格式，新命名规范）
    "claude-sonnet-4-6":         0.003,
    "claude-haiku-4-5":          0.00025,
    "claude-opus-4-6":           0.015,
    # Grok
    "xai/grok-4.20-reasoning":   0.005,
    # 兼容旧名称（点号格式）
    "claude-sonnet-4.6":         0.003,
    "claude-haiku-4.5":          0.00025,
    "opus-4.7":                  0.015,
    "gpt-5.5":                   0.01,
    "default":                   0.001,
}


class TokenRecord:
    __slots__ = ("model", "prompt_tokens", "completion_tokens", "timestamp", "session_id")

    def __init__(self, model: str, prompt: int, completion: int, session_id: str = "") -> None:
        self.model = model
        self.prompt_tokens = prompt
        self.completion_tokens = completion
        self.timestamp = datetime.now()
        self.session_id = session_id

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens

    @property
    def estimated_cost(self) -> float:
        rate = MODEL_COST_PER_1K.get(self.model, MODEL_COST_PER_1K["default"])
        return self.total_tokens / 1000 * rate

    @property
    def date_str(self) -> str:
        return self.timestamp.strftime("%Y-%m-%d")


class TokenTracker:
    """
    Token消耗追踪器（单例）。
    - 记录每次API调用
    - 按模型/日期/会话聚合
    - 预算告警（月$100 / 日$3.3）
    """

    _instance: TokenTracker | None = None

    def __init__(self, daily_limit: float = 3.3, monthly_limit: float = 100.0) -> None:
        self._daily_limit = daily_limit
        self._monthly_limit = monthly_limit
        self._records: list[TokenRecord] = []
        self._alerts: list[str] = []

    @classmethod
    def get(cls) -> "TokenTracker":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    @classmethod
    def reset(cls) -> None:
        cls._instance = None

    def configure(self, daily_limit: float, monthly_limit: float) -> None:
        """
        设置预算限额。

        Args:
            daily_limit:   日预算上限（USD），必须 > 0。
            monthly_limit: 月预算上限（USD），必须 >= daily_limit。

        Raises:
            ValueError: 传入无效限额时（非正数或月限额 < 日限额）。
        """
        if daily_limit <= 0:
            raise ValueError(
                f"[TokenTracker] daily_limit 必须 > 0，得到 {daily_limit}。"
            )
        if monthly_limit <= 0:
            raise ValueError(
                f"[TokenTracker] monthly_limit 必须 > 0，得到 {monthly_limit}。"
            )
        if monthly_limit < daily_limit:
            raise ValueError(
                f"[TokenTracker] monthly_limit ({monthly_limit}) 不得小于 daily_limit ({daily_limit})。"
            )
        self._daily_limit = daily_limit
        self._monthly_limit = monthly_limit

    def record(
        self,
        model: str,
        prompt_tokens: int,
        completion_tokens: int,
        session_id: str = "",
    ) -> float:
        """记录一次API调用，返回本次估算成本。"""
        record = TokenRecord(model, prompt_tokens, completion_tokens, session_id)
        self._records.append(record)
        cost = record.estimated_cost

        # 预算告警
        self._check_budget_alerts()
        return cost

    def _check_budget_alerts(self) -> None:
        today = datetime.now().strftime("%Y-%m-%d")
        month = datetime.now().strftime("%Y-%m")

        daily_cost = sum(
            r.estimated_cost for r in self._records
            if r.date_str == today
        )
        monthly_cost = sum(
            r.estimated_cost for r in self._records
            if r.timestamp.strftime("%Y-%m") == month
        )

        if daily_cost > self._daily_limit * 0.8:
            msg = f"⚠️ 日预算已用 ${daily_cost:.2f} / ${self._daily_limit} ({daily_cost/self._daily_limit:.0%})"
            if msg not in self._alerts:
                self._alerts.append(msg)
                logger.warning(f"[TokenTracker] {msg}")

        if monthly_cost > self._monthly_limit * 0.8:
            msg = f"⚠️ 月预算已用 ${monthly_cost:.2f} / ${self._monthly_limit}"
            if msg not in self._alerts:
                self._alerts.append(msg)
                logger.warning(f"[TokenTracker] {msg}")

    # ─── 统计 ─────────────────────────────────────────────────────────────────
    def daily_cost(self, date: str | None = None) -> float:
        d = date or datetime.now().strftime("%Y-%m-%d")
        return sum(r.estimated_cost for r in self._records if r.date_str == d)

    def monthly_cost(self, month: str | None = None) -> float:
        m = month or datetime.now().strftime("%Y-%m")
        return sum(r.estimated_cost for r in self._records
                   if r.timestamp.strftime("%Y-%m") == m)

    def by_model(self) -> dict[str, dict]:
        result: dict[str, dict] = defaultdict(lambda: {"calls": 0, "tokens": 0, "cost": 0.0})
        for r in self._records:
            result[r.model]["calls"] += 1
            result[r.model]["tokens"] += r.total_tokens
            result[r.model]["cost"] += r.estimated_cost
        return dict(result)

    def total_stats(self) -> dict:
        return {
            "total_calls": len(self._records),
            "total_tokens": sum(r.total_tokens for r in self._records),
            "total_cost_usd": round(sum(r.estimated_cost for r in self._records), 4),
            "daily_cost": round(self.daily_cost(), 4),
            "monthly_cost": round(self.monthly_cost(), 4),
            "daily_limit": self._daily_limit,
            "monthly_limit": self._monthly_limit,
            "recent_alerts": self._alerts[-5:],
        }

    def __repr__(self) -> str:
        return f"TokenTracker(calls={len(self._records)}, cost=${sum(r.estimated_cost for r in self._records):.4f})"

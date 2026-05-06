"""
CreditMonitor — 信用监控模块
实时监控第三方API账户余额，欠费时自动切换到兜底模型，充值后自动切回
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)


class CreditStatus(str, Enum):
    ACTIVE = "active"          # 正常使用
    EXHAUSTED = "exhausted"    # 已欠费/耗尽
    FALLBACK = "fallback"      # 已切换到兜底模型
    UNKNOWN = "unknown"        # 状态未知


@dataclass
class CreditEvent:
    """信用状态变更事件记录。"""
    timestamp: datetime = field(default_factory=datetime.now)
    event_type: str = ""  # exhausted / fallback / recovered
    detail: str = ""
    provider: str = ""


class CreditMonitor:
    """
    信用监控器（单例）。

    工作流：
      正常 → 使用三方API
      API调用 → 检查响应
      200 OK → 继续使用
      401/402/403 → is_exhausted=True → should_fallback()=True
      → get_primary_model_config() → 自动切换兜底模型
      → get_notification() → 通知用户
      用户充值 → confirm_topup() → is_exhausted=False → 切回三方API
    """

    _instance: CreditMonitor | None = None

    def __init__(self, config: dict | None = None) -> None:
        self._cfg = config or {}
        self._enabled: bool = self._cfg.get("enabled", True)
        self._is_exhausted: bool = False
        self._current_status: CreditStatus = CreditStatus.ACTIVE
        self._events: list[CreditEvent] = []
        self._fallback_model_cfg: dict = {}
        self._exhausted_provider: str = ""

    @classmethod
    def get(cls, config: dict | None = None) -> "CreditMonitor":
        if cls._instance is None:
            cls._instance = cls(config)
        return cls._instance

    @classmethod
    def reset(cls) -> None:
        cls._instance = None

    # ─── 核心检查 ──────────────────────────────────────────────────────────────
    def check_credit(self, response_status: int, provider: str = "") -> bool:
        """
        根据API响应状态码判断信用状态。
        返回 True 表示正常，False 表示需要切换。
        """
        if not self._enabled:
            return True

        if response_status in (401, 402, 403):
            self._mark_exhausted(provider)
            return False
        elif response_status == 200 and self._is_exhausted:
            logger.info(f"[CreditMonitor] 检测到200响应，当前处于兜底模式，等待用户确认充值")
        return True

    def _mark_exhausted(self, provider: str = "") -> None:
        """标记三方API已欠费。"""
        if not self._is_exhausted:
            self._is_exhausted = True
            self._current_status = CreditStatus.EXHAUSTED
            self._exhausted_provider = provider
            event = CreditEvent(
                event_type="exhausted",
                detail=f"Provider {provider} 响应401/402/403，判定为欠费",
                provider=provider,
            )
            self._events.append(event)
            logger.warning(f"[CreditMonitor] ⚠️  三方API欠费: {provider}")

    # ─── 状态查询 ──────────────────────────────────────────────────────────────
    @property
    def is_exhausted(self) -> bool:
        return self._is_exhausted

    def should_fallback(self) -> bool:
        """是否应该切换到兜底模型。"""
        return (
            self._enabled
            and self._is_exhausted
            and self._cfg.get("auto_fallback_to_primary", True)
        )

    @property
    def status(self) -> CreditStatus:
        return self._current_status

    # ─── 兜底模型 ─────────────────────────────────────────────────────────────
    def set_primary_model_config(self, config: dict) -> None:
        """设置兜底模型配置（由 GiraffeConfig 在初始化时调用）。"""
        self._fallback_model_cfg = config

    def get_primary_model_config(self) -> dict:
        """获取兜底模型配置。"""
        return self._fallback_model_cfg

    def activate_fallback(self) -> dict:
        """激活兜底模式，返回兜底模型配置。"""
        self._current_status = CreditStatus.FALLBACK
        event = CreditEvent(
            event_type="fallback",
            detail="已切换到兜底模型",
            provider=self._exhausted_provider,
        )
        self._events.append(event)
        logger.info("[CreditMonitor] 🔄 已切换到兜底模型")
        return self._fallback_model_cfg

    # ─── 充值恢复 ─────────────────────────────────────────────────────────────
    def confirm_topup(self) -> bool:
        """
        用户确认已充值后调用。
        若 auto_recover_on_topup=True，自动切回三方API。
        """
        if not self._cfg.get("auto_recover_on_topup", True):
            return False
        self._is_exhausted = False
        self._current_status = CreditStatus.ACTIVE
        event = CreditEvent(
            event_type="recovered",
            detail="用户确认充值，已切回三方API",
            provider=self._exhausted_provider,
        )
        self._events.append(event)
        logger.info("[CreditMonitor] ✅ 已切回三方API")
        return True

    # ─── 通知 ────────────────────────────────────────────────────────────────
    def get_notification(self) -> str | None:
        """获取当前需要向用户展示的通知信息。"""
        if self._current_status == CreditStatus.EXHAUSTED:
            return f"⚠️  三方API ({self._exhausted_provider}) 已欠费，正在自动切换到兜底模型..."
        if self._current_status == CreditStatus.FALLBACK:
            return f"🔄 当前使用兜底模型（三方API {self._exhausted_provider} 欠费中）。请充值后运行 confirm_topup() 切回。"
        return None

    # ─── 历史记录 ─────────────────────────────────────────────────────────────
    def get_events(self) -> list[dict]:
        return [
            {
                "timestamp": e.timestamp.isoformat(),
                "type": e.event_type,
                "detail": e.detail,
                "provider": e.provider,
            }
            for e in self._events
        ]

    def summary(self) -> dict:
        return {
            "enabled": self._enabled,
            "status": self._current_status.value,
            "is_exhausted": self._is_exhausted,
            "exhausted_provider": self._exhausted_provider,
            "event_count": len(self._events),
            "fallback_model": self._fallback_model_cfg.get("model", "N/A"),
        }

    def __repr__(self) -> str:
        return f"CreditMonitor(status={self._current_status.value})"

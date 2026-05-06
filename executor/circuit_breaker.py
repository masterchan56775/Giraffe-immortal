"""
CircuitBreaker — 熔断器
连续3次失败 → 熔断(open) → 60秒冷却 → 半开(half-open) → 成功 → 恢复(closed)
"""
from __future__ import annotations

import logging
import time
from enum import Enum
from typing import Callable, Any

logger = logging.getLogger(__name__)


class CircuitState(str, Enum):
    CLOSED    = "closed"      # 正常
    OPEN      = "open"        # 熔断中
    HALF_OPEN = "half_open"   # 试探恢复


class CircuitBreaker:
    """
    熔断器实现。
    状态机：CLOSED → (连续失败≥threshold) → OPEN → (冷却) → HALF_OPEN → (成功) → CLOSED
    """

    def __init__(
        self,
        name: str = "default",
        failure_threshold: int = 3,
        cooldown_seconds: float = 60.0,
        half_open_max_calls: int = 1,
    ) -> None:
        self.name = name
        self._failure_threshold = failure_threshold
        self._cooldown_seconds = cooldown_seconds
        self._half_open_max_calls = half_open_max_calls

        self._state: CircuitState = CircuitState.CLOSED
        self._failure_count: int = 0
        self._success_count: int = 0
        self._last_failure_time: float = 0.0
        self._half_open_calls: int = 0

    # ─── 核心调用 ─────────────────────────────────────────────────────────────
    def call(self, func: Callable, *args, **kwargs) -> Any:
        """
        通过熔断器调用函数。
        熔断中时抛出 CircuitOpenError。
        """
        self._check_state_transition()

        if self._state == CircuitState.OPEN:
            raise CircuitOpenError(
                f"熔断器[{self.name}]处于OPEN状态，冷却剩余: "
                f"{self._remaining_cooldown():.1f}s"
            )

        if self._state == CircuitState.HALF_OPEN:
            if self._half_open_calls >= self._half_open_max_calls:
                raise CircuitOpenError(f"熔断器[{self.name}]半开状态已达最大试探次数")
            self._half_open_calls += 1

        try:
            result = func(*args, **kwargs)
            self.record_success()
            return result
        except Exception as e:
            self.record_failure()
            raise

    def record_success(self) -> None:
        """记录一次成功调用。"""
        self._success_count += 1
        if self._state == CircuitState.HALF_OPEN:
            logger.info(f"[CircuitBreaker:{self.name}] HALF_OPEN → CLOSED（恢复正常）")
            self._reset()
        elif self._state == CircuitState.CLOSED:
            self._failure_count = 0  # 成功时重置失败计数

    def record_failure(self) -> None:
        """记录一次失败调用。"""
        self._failure_count += 1
        self._last_failure_time = time.time()

        if self._state == CircuitState.HALF_OPEN:
            logger.warning(f"[CircuitBreaker:{self.name}] HALF_OPEN → OPEN（试探失败）")
            self._trip()
        elif self._state == CircuitState.CLOSED:
            if self._failure_count >= self._failure_threshold:
                logger.error(
                    f"[CircuitBreaker:{self.name}] CLOSED → OPEN "
                    f"（连续失败{self._failure_count}次）"
                )
                self._trip()

    # ─── 状态控制 ─────────────────────────────────────────────────────────────
    def _trip(self) -> None:
        """触发熔断。"""
        self._state = CircuitState.OPEN
        self._half_open_calls = 0

    def _reset(self) -> None:
        """恢复正常。"""
        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._half_open_calls = 0

    def _check_state_transition(self) -> None:
        """检查是否需要从OPEN转换到HALF_OPEN。"""
        if self._state == CircuitState.OPEN:
            if self._remaining_cooldown() <= 0:
                logger.info(f"[CircuitBreaker:{self.name}] OPEN → HALF_OPEN（冷却完成）")
                self._state = CircuitState.HALF_OPEN
                self._half_open_calls = 0

    def _remaining_cooldown(self) -> float:
        return max(0.0, self._cooldown_seconds - (time.time() - self._last_failure_time))

    # ─── 状态查询 ─────────────────────────────────────────────────────────────
    @property
    def state(self) -> CircuitState:
        self._check_state_transition()
        return self._state

    @property
    def is_open(self) -> bool:
        return self.state == CircuitState.OPEN

    @property
    def failure_count(self) -> int:
        return self._failure_count

    def stats(self) -> dict:
        return {
            "name": self.name,
            "state": self._state.value,
            "failure_count": self._failure_count,
            "success_count": self._success_count,
            "remaining_cooldown_s": round(self._remaining_cooldown(), 1),
        }

    def __repr__(self) -> str:
        return f"CircuitBreaker(name={self.name}, state={self._state.value})"


class CircuitOpenError(Exception):
    """熔断器处于OPEN状态时抛出的异常。"""
    pass


class CircuitBreakerRegistry:
    """熔断器注册表，按provider/model分别管理熔断器。"""

    _instance: CircuitBreakerRegistry | None = None

    def __init__(self) -> None:
        self._breakers: dict[str, CircuitBreaker] = {}
        self._default_cfg: dict = {
            "failure_threshold": 3,
            "cooldown_seconds": 60.0,
            "half_open_max_calls": 1,
        }

    @classmethod
    def get(cls) -> "CircuitBreakerRegistry":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def configure(self, cfg: dict) -> None:
        """从配置文件更新默认参数。"""
        self._default_cfg.update(cfg)

    def get_breaker(self, name: str) -> CircuitBreaker:
        """获取或创建命名熔断器。"""
        if name not in self._breakers:
            self._breakers[name] = CircuitBreaker(name=name, **self._default_cfg)
        return self._breakers[name]

    def all_stats(self) -> list[dict]:
        return [b.stats() for b in self._breakers.values()]

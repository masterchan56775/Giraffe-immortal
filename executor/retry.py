"""
指数退避重试 — 
区分前台/后台查询，前台重试，后台快速失败。
"""
from __future__ import annotations

import logging
import random
import time
from typing import Callable, Literal, TypeVar

logger = logging.getLogger("retry")

T = TypeVar("T")

QuerySource = Literal[
    "main",        # 主对话（前台，用户等待）
    "agent",       # Agent 循环（前台）
    "compact",     # 压缩（前台）
    "side_query",  # 后台辅助查询（不重试）
    "classifier",  # 分类器（不重试）
    "title",       # 标题生成（不重试）
    "memory",      # 记忆评分（不重试）
]

# 前台查询：用户在等待结果，需要重试
_FOREGROUND_SOURCES: set[str] = {"main", "agent", "compact"}

# 重试配置
DEFAULT_MAX_RETRIES = 10
MAX_529_RETRIES = 3      # 速率限制最多重试次数
BASE_DELAY_MS = 500      # 基础延迟 ms
MAX_DELAY_MS = 30_000    # 最大延迟 ms

def _is_rate_limit_error(e: Exception) -> bool:
    """检测 429/529 速率限制错误。"""
    msg = str(e).lower()
    code = getattr(e, "status_code", None) or getattr(e, "status", None)
    return (
        code in (429, 529)
        or "rate limit" in msg
        or "429" in msg
        or "529" in msg
        or "overloaded" in msg
        or "too many requests" in msg
    )

def _is_transient_error(e: Exception) -> bool:
    """检测可重试的瞬时错误（连接超时、重置等）。"""
    msg = str(e).lower()
    code = getattr(e, "status_code", None) or getattr(e, "status", None)
    return (
        code in (500, 502, 503, 504)
        or "connection" in msg
        or "timeout" in msg
        or "econnreset" in msg
        or "epipe" in msg
        or "network" in msg
    )

def _is_auth_error(e: Exception) -> bool:
    """检测认证错误（需刷新 token）。"""
    code = getattr(e, "status_code", None) or getattr(e, "status", None)
    return code == 401

def _calc_delay(attempt: int, base_ms: int = BASE_DELAY_MS) -> float:
    """指数退避 + jitter，单位秒。"""
    delay_ms = min(base_ms * (2 ** attempt), MAX_DELAY_MS)
    # 加 ±25% jitter
    jitter = delay_ms * 0.25 * (random.random() * 2 - 1)
    return max((delay_ms + jitter) / 1000.0, 0.1)

def with_retry(
    fn: Callable[[], T],
    max_retries: int = DEFAULT_MAX_RETRIES,
    query_source: QuerySource = "main",
    on_retry: Callable[[int, Exception], None] | None = None,
) -> T:
    """
    同步重试包装器。

    策略：
    - 前台（main/agent/compact）：速率限制最多重试 MAX_529_RETRIES 次，其他错误最多 max_retries 次
    - 后台（side_query/classifier/title）：任何错误立即放弃（避免级联放大）
    - 401：立即放弃（认证失败无法自动修复，需用户介入）
    """
    is_foreground = query_source in _FOREGROUND_SOURCES
    rate_limit_count = 0

    last_err: Exception | None = None

    for attempt in range(max_retries + 1):
        try:
            return fn()
        except Exception as e:
            last_err = e

            # 后台查询：立即放弃
            if not is_foreground:
                logger.debug(f"[Retry:{query_source}] 后台查询失败，放弃: {e}")
                raise

            # 认证错误：立即放弃
            if _is_auth_error(e):
                logger.warning(f"[Retry] 认证失败 (401)，放弃: {e}")
                raise

            # 速率限制
            if _is_rate_limit_error(e):
                rate_limit_count += 1
                if rate_limit_count > MAX_529_RETRIES:
                    logger.warning(f"[Retry] 速率限制超过 {MAX_529_RETRIES} 次，放弃")
                    raise

            # 非瞬时错误（如参数错误）：立即放弃
            elif not _is_transient_error(e):
                logger.debug(f"[Retry] 非瞬时错误，放弃: {e}")
                raise

            # 已用完重试次数
            if attempt >= max_retries:
                break

            delay = _calc_delay(attempt)
            logger.info(
                f"[Retry:{query_source}] attempt={attempt+1}/{max_retries} "
                f"delay={delay:.1f}s error={type(e).__name__}: {str(e)[:80]}"
            )
            if on_retry:
                on_retry(attempt + 1, e)
            time.sleep(delay)

    assert last_err is not None
    raise last_err

async def with_retry_async(
    fn: Callable[[], "Awaitable[T]"],
    max_retries: int = DEFAULT_MAX_RETRIES,
    query_source: QuerySource = "main",
    on_retry: Callable[[int, Exception], None] | None = None,
) -> T:
    """async 版本。"""
    import asyncio
    is_foreground = query_source in _FOREGROUND_SOURCES
    rate_limit_count = 0
    last_err: Exception | None = None

    for attempt in range(max_retries + 1):
        try:
            return await fn()
        except Exception as e:
            last_err = e
            if not is_foreground:
                raise
            if _is_auth_error(e):
                raise
            if _is_rate_limit_error(e):
                rate_limit_count += 1
                if rate_limit_count > MAX_529_RETRIES:
                    raise
            elif not _is_transient_error(e):
                raise
            if attempt >= max_retries:
                break
            delay = _calc_delay(attempt)
            logger.info(f"[Retry:{query_source}] attempt={attempt+1} delay={delay:.1f}s")
            if on_retry:
                on_retry(attempt + 1, e)
            await asyncio.sleep(delay)

    raise last_err

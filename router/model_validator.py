"""
Model Validator — 
使用 SideQuery 对未知模型发起最小化 API 验证（max_tokens=1）。
缓存验证结果，避免重复调用。
"""
from __future__ import annotations

import logging
import os
from typing import TypedDict

from router.model_aliases import (
    MODEL_ALIASES,
    get_api_provider,
    get_canonical_name,
    get_default_sonnet_model,
    is_model_allowed,
    get_3p_fallback_suggestion,
)

logger = logging.getLogger("model_validator")

# 结果缓存（内存级别，进程内有效）
_valid_model_cache: set[str] = set()
_invalid_model_cache: dict[str, str] = {}   # model → error_msg

class ValidationResult(TypedDict):
    valid: bool
    error: str | None

def _check_allowlist(model: str) -> ValidationResult | None:
    """先走允许名单，快速拒绝。"""
    allowlist_env = os.environ.get("GIRAFFE_AVAILABLE_MODELS")
    if not allowlist_env:
        return None
    allowlist = [m.strip() for m in allowlist_env.split(",") if m.strip()]
    if not is_model_allowed(model, allowlist):
        return ValidationResult(
            valid=False,
            error=f"模型 '{model}' 不在允许名单中（GIRAFFE_AVAILABLE_MODELS）"
        )
    return None

async def validate_model_async(model: str) -> ValidationResult:
    """
    异步验证模型是否可用。
    。

    优先级：
    1. 空字符串 → 立即拒绝
    2. allowlist 检查
    3. 已知别名 → 直接通过（不调 API）
    4. 自定义模型环境变量 → 直接通过
    5. 缓存命中
    6. SideQuery 最小化 API 调用验证
    """
    normalized = model.strip()
    if not normalized:
        return ValidationResult(valid=False, error="模型名称不能为空")

    # allowlist
    result = _check_allowlist(normalized)
    if result is not None:
        return result

    # 已知别名（直接通过，parse_model_alias 会处理）
    if normalized.lower().split("[")[0].strip() in MODEL_ALIASES:
        return ValidationResult(valid=True, error=None)

    # 自定义模型环境变量
    if normalized == os.environ.get("ANTHROPIC_CUSTOM_MODEL_OPTION"):
        return ValidationResult(valid=True, error=None)

    # 缓存命中
    if normalized in _valid_model_cache:
        return ValidationResult(valid=True, error=None)
    if normalized in _invalid_model_cache:
        return ValidationResult(valid=False, error=_invalid_model_cache[normalized])

    # SideQuery 最小验证
    try:
        from executor.side_query import get_side_query
        sq = get_side_query()
        result_sq = await sq.query(
            messages=[{"role": "user", "content": "Hi"}],
            model=normalized,
            max_tokens=1,
        )
        if result_sq.ok:
            _valid_model_cache.add(normalized)
            return ValidationResult(valid=True, error=None)
        else:
            err = _make_error_msg(normalized, result_sq.error or "未知错误")
            _invalid_model_cache[normalized] = err
            return ValidationResult(valid=False, error=err)
    except Exception as e:
        err = _make_error_msg(normalized, str(e))
        _invalid_model_cache[normalized] = err
        return ValidationResult(valid=False, error=err)

def validate_model_sync(model: str) -> ValidationResult:
    """同步版本（用于初始化阶段）。"""
    normalized = model.strip()
    if not normalized:
        return ValidationResult(valid=False, error="模型名称不能为空")

    result = _check_allowlist(normalized)
    if result is not None:
        return result

    if normalized.lower().split("[")[0].strip() in MODEL_ALIASES:
        return ValidationResult(valid=True, error=None)

    if normalized == os.environ.get("ANTHROPIC_CUSTOM_MODEL_OPTION"):
        return ValidationResult(valid=True, error=None)

    if normalized in _valid_model_cache:
        return ValidationResult(valid=True, error=None)

    # 同步：跳过 API 验证，假定合法（后续调用时若失败由 retry 处理）
    logger.debug(f"[ModelValidator] 无法同步验证 '{normalized}'，假定合法")
    return ValidationResult(valid=True, error=None)

def _make_error_msg(model: str, raw_error: str) -> str:
    """生成友好错误提示，包含 3P 降级建议。"""
    provider = get_api_provider()
    fallback = get_3p_fallback_suggestion(model, provider)
    if "not found" in raw_error.lower() or "404" in raw_error:
        suggestion = f"，建议改用 '{fallback}'" if fallback else ""
        return f"模型 '{model}' 不存在{suggestion}"
    if "auth" in raw_error.lower() or "401" in raw_error:
        return "认证失败，请检查 API Key 配置"
    if "connection" in raw_error.lower() or "network" in raw_error.lower():
        return "网络连接失败，请检查网络设置"
    return f"模型验证失败：{raw_error}"

def mark_model_valid(model: str) -> None:
    """手动标记模型为有效（用于启动时预验证）。"""
    _valid_model_cache.add(model.strip())

def clear_validation_cache() -> None:
    """清除验证缓存（测试用）。"""
    _valid_model_cache.clear()
    _invalid_model_cache.clear()

"""
模型别名系统 — 
支持 haiku/sonnet/opus/flash/grok 别名，[1m]/[2m] 上下文标记，
以及 Provider 感知的版本分发。
"""
from __future__ import annotations

import os
from typing import Literal

# ── Provider 类型 ─────────────────────────────────────────────────────────────
APIProvider = Literal["firstParty", "vertex", "bedrock", "foundry"]

def get_api_provider() -> APIProvider:
    """
    检测当前使用的 API Provider。
    优先级：环境变量 > 默认 firstParty。
    。
    """
    if os.environ.get("GIRAFFE_USE_VERTEX") or os.environ.get("CLAUDE_CODE_USE_VERTEX"):
        return "vertex"
    if os.environ.get("GIRAFFE_USE_BEDROCK") or os.environ.get("CLAUDE_CODE_USE_BEDROCK"):
        return "bedrock"
    if os.environ.get("GIRAFFE_USE_FOUNDRY") or os.environ.get("CLAUDE_CODE_USE_FOUNDRY"):
        return "foundry"
    return "firstParty"

# ── 别名定义 ──────────────────────────────────────────────────────────────────

# 族别名（匹配整个家族）
MODEL_FAMILY_ALIASES = {"opus", "sonnet", "haiku", "flash", "grok", "lite"}

# 特殊别名（需要特殊解析逻辑）
MODEL_SPECIAL_ALIASES = {"opusplan", "best", "default"}

# 全部别名
MODEL_ALIASES = MODEL_FAMILY_ALIASES | MODEL_SPECIAL_ALIASES

def is_model_alias(name: str) -> bool:
    return name.lower().rstrip("[1m][2m]").strip() in MODEL_ALIASES

def is_family_alias(name: str) -> bool:
    return name.lower().rstrip("[1m][2m]").strip() in MODEL_FAMILY_ALIASES

def has_1m_context(model: str) -> bool:
    """检测是否带 [1m] 标记。"""
    return "[1m]" in model.lower()

def has_2m_context(model: str) -> bool:
    return "[2m]" in model.lower()

def strip_context_tag(model: str) -> str:
    """移除 [1m]/[2m] 标记。"""
    return model.lower().replace("[1m]", "").replace("[2m]", "").strip()

# ── 具体版本映射 ───────────────────────────────────────────────────────────────

# 对应 src modelStrings + DEFAULT_MODEL_MATRIX
# firstParty 列表（Anthropic 直连 / Vertex AI 原生）
_CLAUDE_MODELS_FIRSTPARTY = {
    "opus":    "claude-opus-4-6",
    "sonnet":  "claude-sonnet-4-6",
    "haiku":   "claude-haiku-4-5",
}

# Bedrock 使用带 AWS 前缀的模型 ID
_CLAUDE_MODELS_BEDROCK = {
    "opus":    "us.anthropic.claude-opus-4-6-v1:0",
    "sonnet":  "us.anthropic.claude-sonnet-4-6-v1:0",
    "haiku":   "us.anthropic.claude-haiku-4-5-v1:0",
}

# Gemini 模型（Vertex AI / Google AI）
_GEMINI_MODELS = {
    "flash":   "gemini-3-flash-preview",
    "pro":     "gemini-3.1-pro-preview",
    "lite":    "gemini-3.1-flash-lite",
}

# Grok 模型（xAI / Vertex AI）
_GROK_MODELS = {
    "grok":    "xai/grok-4.20-reasoning",
}

# 旧版 Opus 映射（1P 不再支持，自动升级）
_LEGACY_OPUS_FIRSTPARTY = {
    "claude-opus-4-20250514",
    "claude-opus-4-1-20250805",
    "claude-opus-4-0",
    "claude-opus-4-1",
}

def get_default_opus_model(provider: APIProvider | None = None) -> str:
    """获取最新 Opus 模型名。"""
    p = provider or get_api_provider()
    env = os.environ.get("ANTHROPIC_DEFAULT_OPUS_MODEL")
    if env:
        return env
    if p == "bedrock":
        return _CLAUDE_MODELS_BEDROCK["opus"]
    return _CLAUDE_MODELS_FIRSTPARTY["opus"]

def get_default_sonnet_model(provider: APIProvider | None = None) -> str:
    """获取最新 Sonnet 模型名。"""
    p = provider or get_api_provider()
    env = os.environ.get("ANTHROPIC_DEFAULT_SONNET_MODEL")
    if env:
        return env
    if p == "bedrock":
        return _CLAUDE_MODELS_BEDROCK["sonnet"]
    return _CLAUDE_MODELS_FIRSTPARTY["sonnet"]

def get_default_haiku_model(provider: APIProvider | None = None) -> str:
    """获取最新 Haiku 模型名。"""
    p = provider or get_api_provider()
    env = os.environ.get("ANTHROPIC_DEFAULT_HAIKU_MODEL")
    if env:
        return env
    if p == "bedrock":
        return _CLAUDE_MODELS_BEDROCK["haiku"]
    return _CLAUDE_MODELS_FIRSTPARTY["haiku"]

def get_small_fast_model() -> str:
    """小型快速模型（用于 side_query、分类等辅助场景）。。"""
    return os.environ.get("ANTHROPIC_SMALL_FAST_MODEL") or get_default_haiku_model()

def parse_model_alias(model_input: str, provider: APIProvider | None = None) -> str:
    """
    将别名/简写解析为完整模型名。
    支持 [1m] 后缀透传（携带到目标模型名）。
    。

    优先级：
    1. 环境变量 ANTHROPIC_MODEL（覆盖所有别名）
    2. 别名解析（haiku/sonnet/opus/flash/grok/lite...）
    3. 旧版 Opus 自动升级（firstParty）
    4. 原样返回（自定义模型名）
    """
    p = provider or get_api_provider()
    raw = model_input.strip()
    normalized = raw.lower()

    tag_1m = has_1m_context(normalized)
    tag_2m = has_2m_context(normalized)
    base = strip_context_tag(normalized)

    suffix = "[1m]" if tag_1m else ("[2m]" if tag_2m else "")

    # 特殊别名
    if base == "opusplan":
        # plan 模式用 Opus，默认 Sonnet（让 pipeline 处理 plan-mode 切换）
        return get_default_sonnet_model(p) + suffix
    if base in ("best", "opus"):
        return get_default_opus_model(p) + suffix
    if base == "sonnet":
        return get_default_sonnet_model(p) + suffix
    if base == "haiku":
        return get_default_haiku_model(p) + suffix
    if base in ("flash", "gemini-flash"):
        return _GEMINI_MODELS["flash"] + suffix
    if base in ("pro", "gemini-pro"):
        return _GEMINI_MODELS["pro"] + suffix
    if base == "lite":
        return _GEMINI_MODELS["lite"] + suffix
    if base in ("grok",):
        return _GROK_MODELS["grok"] + suffix
    if base == "default":
        return get_default_sonnet_model(p) + suffix

    # 旧版 Opus 自动升级（firstParty）
    if p == "firstParty" and base in _LEGACY_OPUS_FIRSTPARTY:
        return get_default_opus_model(p) + suffix

    # 自定义模型名（透传）
    return raw

def get_canonical_name(full_model_name: str) -> str:
    """
    将任意模型名标准化为规范短名（跨 Provider 统一）。
     / firstPartyNameToCanonical()。
    用于：allowlist 匹配、成本计算、显示名称。
    """
    name = full_model_name.lower()
    # 去除 [1m] 后缀
    name = strip_context_tag(name)
    # Bedrock ARN 格式 → 去前缀
    if ":" in name:
        name = name.split(":")[0]
    # AWS 地区前缀
    for region in ("us.", "eu.", "ap."):
        if name.startswith(region):
            name = name[len(region):]
    # 规范 Claude 型号匹配（最长优先）
    canon_map = [
        ("claude-opus-4-6",    "claude-opus-4-6"),
        ("claude-opus-4-5",    "claude-opus-4-5"),
        ("claude-opus-4-1",    "claude-opus-4-1"),
        ("claude-opus-4",      "claude-opus-4"),
        ("claude-sonnet-4-6",  "claude-sonnet-4-6"),
        ("claude-sonnet-4-5",  "claude-sonnet-4-5"),
        ("claude-sonnet-4",    "claude-sonnet-4"),
        ("claude-haiku-4-5",   "claude-haiku-4-5"),
        ("claude-3-7-sonnet",  "claude-3-7-sonnet"),
        ("claude-3-5-sonnet",  "claude-3-5-sonnet"),
        ("claude-3-5-haiku",   "claude-3-5-haiku"),
        ("claude-3-opus",      "claude-3-opus"),
        ("claude-3-haiku",     "claude-3-haiku"),
    ]
    for pattern, canon in canon_map:
        if pattern in name:
            return canon
    return name

def model_belongs_to_family(model: str, family: str) -> bool:
    """检查模型是否属于某一族（opus/sonnet/haiku/gemini/grok）。"""
    canonical = get_canonical_name(model)
    return family.lower() in canonical

# ── 模型允许名单 ──────────────────────────────────────────────────────────────

def is_model_allowed(model: str, allowlist: list[str] | None) -> bool:
    """
    检查模型是否在允许名单中。
    。
    allowlist=None 表示无限制。
    支持：族别名（sonnet=所有Sonnet）、版本前缀（sonnet-4-6）、精确匹配。
    """
    if not allowlist:
        return True
    if len(allowlist) == 0:
        return False

    normalized = get_canonical_name(model)
    norm_list = [get_canonical_name(e) for e in allowlist]

    # 精确匹配
    if normalized in norm_list:
        return True

    # 族别名匹配：allowlist 中有 "opus" → 允许所有 opus
    for entry in norm_list:
        if entry in MODEL_FAMILY_ALIASES and model_belongs_to_family(normalized, entry):
            # 但如果有更具体的条目，则以具体条目为准
            has_specific = any(
                e for e in norm_list
                if e not in MODEL_FAMILY_ALIASES and entry in e
            )
            if not has_specific:
                return True

    # 版本前缀匹配："claude-sonnet-4-6" 匹配 "claude-sonnet-4-6-20250515"
    for entry in norm_list:
        if entry not in MODEL_FAMILY_ALIASES and normalized.startswith(entry):
            rest = normalized[len(entry):]
            if not rest or rest.startswith("-"):
                return True

    return False

# ── 3P 降级建议 ───────────────────────────────────────────────────────────────

def get_3p_fallback_suggestion(model: str, provider: APIProvider) -> str | None:
    """
    。
    当 3P Provider 不支持最新模型时，建议降级版本。
    """
    if provider == "firstParty":
        return None
    name = model.lower()
    if "opus-4-6" in name:
        return get_default_sonnet_model(provider)  # 3P 没有 opus-4-6 时降到 sonnet
    if "sonnet-4-6" in name:
        return _CLAUDE_MODELS_FIRSTPARTY["sonnet"].replace("4-6", "4-5")
    return None

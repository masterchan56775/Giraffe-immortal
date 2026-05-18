"""
工具系统基础类 — 
"""
from __future__ import annotations

import abc
import json
from dataclasses import dataclass, field
from typing import Any

# ─── 数据结构 ───────────────────────────────────────────────────────────────

@dataclass
class ToolResult:
    """工具执行结果，对应 ToolResultBlockParam。"""
    content: str | list[dict]          # 文本 or 结构化内容块列表
    is_error: bool = False
    tool_use_id: str = ""              # 填充后由 AgenticLoop 使用
    tool_name: str = ""                # 工具名称，供持久化存储使用

    def to_api_block(self) -> dict:
        """转为 Anthropic/OpenAI tool_result 格式。"""
        return {
            "type": "tool_result",
            "tool_use_id": self.tool_use_id,
            "content": self.content,
            "is_error": self.is_error,
        }

@dataclass
class PermissionResult:
    """权限检查结果。"""
    behavior: str          # 'allow' | 'deny' | 'ask'
    message: str = ""      # 拒绝原因或确认提示

@dataclass
class ToolContext:
    """工具执行上下文，对应 ToolUseContext（简化版）。"""
    cwd: str = "."
    model: str = ""
    session_id: str = ""
    abort: bool = False                # abort 信号
    extra: dict = field(default_factory=dict)   # 扩展字段

@dataclass
class ValidationResult:
    ok: bool
    message: str = ""
    error_code: int = 0

# ─── BaseTool ───────────────────────────────────────────────────────────────

class BaseTool(abc.ABC):
    """
    所有工具的基类，。

    子类必须设置：
      name         : str   — 工具名称（传给 LLM）
      description  : str   — 工具描述
      input_schema : dict  — JSON Schema (type=object)

    子类可选覆写：
      is_read_only     : bool  — 只读工具可并发执行
      is_destructive   : bool  — 危险工具需要用户确认
      max_result_size  : int   — 结果超出则截断
    """

    name: str = ""
    description: str = ""
    input_schema: dict = {}
    is_read_only: bool = False
    is_destructive: bool = False
    max_result_size_chars: int = 100_000

    # ── 必须实现 ────────────────────────────────────────────────────────────

    @abc.abstractmethod
    def execute(self, args: dict, ctx: ToolContext) -> ToolResult:
        """执行工具，返回结果。同步（后续可扩展为 async）。"""
        ...

    # ── 可选覆写 ────────────────────────────────────────────────────────────

    def validate(self, args: dict) -> ValidationResult:
        """入参校验，在 execute 前调用。默认不校验。"""
        return ValidationResult(ok=True)

    def check_permission(self, args: dict, ctx: ToolContext) -> PermissionResult:
        """
        权限检查。危险工具应覆写此方法返回 behavior='ask'，
        由 AgenticLoop 弹出确认提示。
        """
        if self.is_destructive:
            return PermissionResult(behavior="ask",
                                    message=f"工具 {self.name} 是危险操作，确认执行？")
        return PermissionResult(behavior="allow")

    def is_concurrency_safe(self, args: dict) -> bool:
        """是否可与其他工具并发执行（只读工具默认安全）。"""
        return self.is_read_only

    def user_facing_name(self, args: dict) -> str:
        return self.name

    # ── API schema ──────────────────────────────────────────────────────────

    def to_anthropic_schema(self) -> dict:
        """生成 Anthropic tool schema。"""
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": self.input_schema,
        }

    def to_openai_schema(self) -> dict:
        """生成 OpenAI/Grok 兼容 tool schema。"""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.input_schema,
            },
        }

    def to_gemini_schema(self) -> dict:
        """生成 Gemini function_declaration schema。"""
        return {
            "name": self.name,
            "description": self.description,
            "parameters": self.input_schema,
        }

    # ── 结果后处理 ───────────────────────────────────────────────────────────

    def truncate_result(self, result: ToolResult) -> ToolResult:
        """结果超出 max_result_size_chars 时截断。"""
        if isinstance(result.content, str) and \
                len(result.content) > self.max_result_size_chars:
            truncated = result.content[:self.max_result_size_chars]
            notice = f"\n\n[结果已截断，超出 {self.max_result_size_chars} 字符限制]"
            result.content = truncated + notice
        return result

    def __repr__(self) -> str:
        return f"<Tool:{self.name}>"

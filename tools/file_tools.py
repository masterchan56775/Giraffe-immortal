"""
文件操作工具集
"""
from __future__ import annotations

import difflib
import os
from pathlib import Path

from tools.base import BaseTool, PermissionResult, ToolContext, ToolResult

_MAX_FILE_BYTES = 5 * 1024 * 1024   # 5MB 上限
_MAX_OUTPUT_CHARS = 80_000

def _resolve_path(path: str, cwd: str) -> Path:
    p = Path(path)
    if not p.is_absolute():
        p = Path(cwd) / p
    return p.resolve()

def _add_line_numbers(text: str) -> str:
    """给文本加行号，。"""
    lines = text.splitlines(keepends=True)
    width = len(str(len(lines)))
    return "".join(f"{i+1:>{width}} | {line}" for i, line in enumerate(lines))

# ─── FileReadTool ─────────────────────────────────────────────────────────────

class FileReadTool(BaseTool):
    """
    读取文件内容（带行号），。
    支持指定行范围。
    """

    name = "read_file"
    description = (
        "读取文件内容，默认加行号方便引用。"
        "可指定 start_line/end_line 读取特定范围。"
    )
    input_schema = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "文件路径（绝对或相对于 cwd）"},
            "start_line": {"type": "integer", "description": "起始行（1-indexed，可选）"},
            "end_line": {"type": "integer", "description": "结束行（含，可选）"},
            "show_line_numbers": {
                "type": "boolean",
                "description": "是否显示行号（默认 true）",
                "default": True,
            },
        },
        "required": ["path"],
    }
    is_read_only = True

    def execute(self, args: dict, ctx: ToolContext) -> ToolResult:
        path = _resolve_path(args["path"], ctx.cwd)
        start = args.get("start_line")
        end = args.get("end_line")
        show_nums = args.get("show_line_numbers", True)

        if not path.exists():
            return ToolResult(content=f"文件不存在：{path}", is_error=True)
        if not path.is_file():
            return ToolResult(content=f"不是文件：{path}", is_error=True)
        if path.stat().st_size > _MAX_FILE_BYTES:
            return ToolResult(
                content=f"文件过大（>{_MAX_FILE_BYTES//1024//1024}MB）：{path}",
                is_error=True,
            )

        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except Exception as e:
            return ToolResult(content=f"读取失败：{e}", is_error=True)

        lines = text.splitlines(keepends=True)
        total = len(lines)

        # 行范围切片
        s = (start - 1) if start else 0
        e = end if end else total
        s = max(0, s)
        e = min(total, e)
        selected = lines[s:e]
        content = "".join(selected)

        if show_nums:
            # 重新加行号，起始为 s+1
            width = len(str(e))
            content = "".join(
                f"{s+i+1:>{width}} | {line}"
                for i, line in enumerate(selected)
            )

        # 截断
        if len(content) > _MAX_OUTPUT_CHARS:
            content = content[:_MAX_OUTPUT_CHARS] + "\n...[内容截断]"

        header = f"文件：{path}  ({total} 行)\n"
        if start or end:
            header += f"显示行：{s+1}–{e}\n"
        return ToolResult(content=header + content)

    def is_concurrency_safe(self, args: dict) -> bool:
        return True

# ─── FileEditTool ─────────────────────────────────────────────────────────────

class FileEditTool(BaseTool):
    """
    精确编辑文件（str_replace 模式）。
    找到 old_string 并替换为 new_string，返回 diff。
    """

    name = "edit_file"
    description = (
        "精确替换文件中的字符串片段（str_replace）。"
        "old_string 必须在文件中唯一存在（否则报错）。"
        "返回 unified diff 供确认。"
    )
    input_schema = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "要编辑的文件路径"},
            "old_string": {
                "type": "string",
                "description": "要被替换的原始文本（必须完全匹配，包括缩进和换行）",
            },
            "new_string": {
                "type": "string",
                "description": "替换后的新文本",
            },
        },
        "required": ["path", "old_string", "new_string"],
    }
    is_read_only = False

    def execute(self, args: dict, ctx: ToolContext) -> ToolResult:
        path = _resolve_path(args["path"], ctx.cwd)
        old_str: str = args["old_string"]
        new_str: str = args["new_string"]

        if not path.exists():
            return ToolResult(content=f"文件不存在：{path}", is_error=True)
        if not path.is_file():
            return ToolResult(content=f"不是文件：{path}", is_error=True)

        try:
            original = path.read_text(encoding="utf-8")
        except Exception as e:
            return ToolResult(content=f"读取失败：{e}", is_error=True)

        count = original.count(old_str)
        if count == 0:
            # 尝试给出提示
            hint = ""
            if old_str.strip() in original:
                hint = "\n提示：内容存在但空白/缩进不匹配，请检查原始格式。"
            return ToolResult(
                content=f"未找到目标字符串（0 处匹配）：{old_str!r}{hint}",
                is_error=True,
            )
        if count > 1:
            return ToolResult(
                content=f"目标字符串不唯一（{count} 处匹配），请提供更多上下文以精确定位。",
                is_error=True,
            )

        modified = original.replace(old_str, new_str, 1)

        try:
            path.write_text(modified, encoding="utf-8")
        except Exception as e:
            return ToolResult(content=f"写入失败：{e}", is_error=True)

        # 生成 diff
        diff_lines = list(difflib.unified_diff(
            original.splitlines(keepends=True),
            modified.splitlines(keepends=True),
            fromfile=f"a/{path.name}",
            tofile=f"b/{path.name}",
            lineterm="",
        ))
        diff_text = "".join(diff_lines[:200])   # 最多 200 行 diff
        if len(diff_lines) > 200:
            diff_text += f"\n...[diff 截断，共 {len(diff_lines)} 行]"

        return ToolResult(content=f"✅ 已编辑 {path}\n\n```diff\n{diff_text}\n```")

# ─── FileWriteTool ────────────────────────────────────────────────────────────

class FileWriteTool(BaseTool):
    """
    新建或覆写文件。
    如果文件已存在且内容不同，需用户确认（通过 is_destructive）。
    """

    name = "write_file"
    description = (
        "将内容写入文件（新建或覆写）。"
        "文件不存在时自动创建（含父目录）。"
        "覆写已存在文件时会提示确认。"
    )
    input_schema = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "文件路径"},
            "content": {"type": "string", "description": "要写入的完整文件内容"},
            "encoding": {
                "type": "string",
                "description": "编码（默认 utf-8）",
                "default": "utf-8",
            },
        },
        "required": ["path", "content"],
    }
    is_read_only = False
    is_destructive = False  # 动态判断（已存在文件才是 destructive）

    def check_permission(self, args: dict, ctx: ToolContext) -> PermissionResult:
        path = _resolve_path(args["path"], ctx.cwd)
        if path.exists():
            return PermissionResult(
                behavior="ask",
                message=f"文件已存在，确认覆写？\n  {path}",
            )
        return PermissionResult(behavior="allow")

    def execute(self, args: dict, ctx: ToolContext) -> ToolResult:
        path = _resolve_path(args["path"], ctx.cwd)
        content: str = args["content"]
        encoding: str = args.get("encoding", "utf-8")

        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding=encoding)
        except Exception as e:
            return ToolResult(content=f"写入失败：{e}", is_error=True)

        lines = content.count("\n") + 1
        return ToolResult(content=f"✅ 已写入 {path}（{lines} 行，{len(content)} 字符）")

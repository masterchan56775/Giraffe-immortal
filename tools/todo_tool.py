"""
TodoWriteTool
会话级任务清单，帮助 Agent 跟踪执行进度。
"""
from __future__ import annotations

import json
import threading
from typing import Literal

from tools.base import BaseTool, ToolContext, ToolResult

TodoStatus = Literal["pending", "in_progress", "done", "failed"]

# 全局存储（key=session_id，value=todo list）
_todo_store: dict[str, list[dict]] = {}
_lock = threading.Lock()

def _get_todos(session_id: str) -> list[dict]:
    with _lock:
        return list(_todo_store.get(session_id, []))

def _set_todos(session_id: str, todos: list[dict]) -> None:
    with _lock:
        _todo_store[session_id] = list(todos)

STATUS_ICON = {
    "pending":     "⬜",
    "in_progress": "🔄",
    "done":        "✅",
    "failed":      "❌",
}

def _format_todos(todos: list[dict]) -> str:
    if not todos:
        return "(任务清单为空)"
    lines = []
    for t in todos:
        icon = STATUS_ICON.get(t.get("status", "pending"), "•")
        priority = t.get("priority", "")
        priority_tag = f"[{priority}] " if priority else ""
        lines.append(f"{icon} {priority_tag}{t.get('content', '?')}  (id={t.get('id', '?')})")
    return "\n".join(lines)

class TodoWriteTool(BaseTool):
    """
    写入/更新会话任务清单，。
    
    Agent 应主动维护 TODO 列表以便跟踪进度：
    - 开始任务时标记 in_progress
    - 完成时标记 done
    - 失败时标记 failed
    """

    name = "todo_write"
    description = (
        "管理当前会话的任务清单（TODO list）。"
        "提交完整的 todos 列表替换现有清单。"
        "状态：pending（未开始）/ in_progress（进行中）/ done（完成）/ failed（失败）。"
        "建议：每次开始新任务前更新状态。"
    )
    input_schema = {
        "type": "object",
        "properties": {
            "todos": {
                "type": "array",
                "description": "完整的任务列表（全量替换）",
                "items": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "string", "description": "任务 ID（建议唯一）"},
                        "content": {"type": "string", "description": "任务描述"},
                        "status": {
                            "type": "string",
                            "enum": ["pending", "in_progress", "done", "failed"],
                            "description": "任务状态",
                        },
                        "priority": {
                            "type": "string",
                            "enum": ["high", "medium", "low"],
                            "description": "优先级（可选）",
                        },
                    },
                    "required": ["id", "content", "status"],
                },
            }
        },
        "required": ["todos"],
    }
    is_read_only = False

    def execute(self, args: dict, ctx: ToolContext) -> ToolResult:
        todos: list[dict] = args.get("todos", [])
        session_id = ctx.session_id or "default"

        old_todos = _get_todos(session_id)
        _set_todos(session_id, todos)

        # 统计变化
        old_map = {t["id"]: t for t in old_todos}
        changes = []
        for t in todos:
            old = old_map.get(t["id"])
            if old is None:
                changes.append(f"  + 新增: {t['content']!r}")
            elif old.get("status") != t.get("status"):
                changes.append(
                    f"  ✎ {t['content']!r}: {old.get('status')} → {t.get('status')}"
                )

        change_text = "\n".join(changes) if changes else "  (无变更)"
        todo_text = _format_todos(todos)

        return ToolResult(
            content=(
                f"✅ 任务清单已更新（{len(todos)} 项）\n\n"
                f"变更：\n{change_text}\n\n"
                f"当前清单：\n{todo_text}"
            )
        )

class TodoReadTool(BaseTool):
    """读取当前任务清单（只读）。"""

    name = "todo_read"
    description = "读取当前会话的任务清单（不修改）。"
    input_schema = {
        "type": "object",
        "properties": {},
    }
    is_read_only = True

    def execute(self, args: dict, ctx: ToolContext) -> ToolResult:
        session_id = ctx.session_id or "default"
        todos = _get_todos(session_id)
        return ToolResult(
            content=f"任务清单（{len(todos)} 项）：\n\n{_format_todos(todos)}"
        )

    def is_concurrency_safe(self, args: dict) -> bool:
        return True

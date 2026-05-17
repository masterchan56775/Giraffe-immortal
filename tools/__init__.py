"""
工具注册中心 — 
"""
from __future__ import annotations

from tools.base import BaseTool
from tools.bash_tool import BashTool
from tools.file_tools import FileEditTool, FileReadTool, FileWriteTool
from tools.search_tools import GlobTool, GrepTool
from tools.todo_tool import TodoReadTool, TodoWriteTool
from tools.web_tools import WebFetchTool

# 所有可用工具（按 category 分组，方便按需启用）
_TOOL_CLASSES: list[type[BaseTool]] = [
    # Shell
    BashTool,
    # File
    FileReadTool,
    FileEditTool,
    FileWriteTool,
    # Search
    GrepTool,
    GlobTool,
    # Web
    WebFetchTool,
    # Task management
    TodoWriteTool,
    TodoReadTool,
]

def build_tool_registry(enabled: list[str] | None = None) -> dict[str, BaseTool]:
    """
    构建工具注册表 {name: tool_instance}。
    enabled=None 启用所有工具；否则只启用指定名称的工具。
    """
    registry: dict[str, BaseTool] = {}
    for cls in _TOOL_CLASSES:
        tool = cls()
        if enabled is None or tool.name in enabled:
            registry[tool.name] = tool
    return registry

def get_default_registry() -> dict[str, BaseTool]:
    """返回默认工具注册表（全部启用）。"""
    return build_tool_registry()

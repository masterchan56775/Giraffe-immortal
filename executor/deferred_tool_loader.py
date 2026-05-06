"""
DeferredToolLoader — 延迟工具加载器
工具注册但不立即加载（节省启动时间），按需搜索匹配，使用频率排序
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any, Callable

logger = logging.getLogger(__name__)


@dataclass
class ToolInfo:
    """工具元信息。"""
    name: str
    description: str
    loader: Callable | None = None    # 延迟加载函数
    category: str = "general"
    usage_count: int = 0
    _loaded_instance: Any = field(default=None, repr=False)

    def load(self) -> Any:
        """按需加载工具。"""
        if self._loaded_instance is None and self.loader:
            self._loaded_instance = self.loader()
            logger.debug(f"[DeferredLoader] 加载工具: {self.name}")
        return self._loaded_instance

    def use(self) -> Any:
        """使用工具（计数+1）。"""
        self.usage_count += 1
        return self.load()

    @property
    def is_loaded(self) -> bool:
        return self._loaded_instance is not None

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "description": self.description,
            "category": self.category,
            "usage_count": self.usage_count,
            "is_loaded": self.is_loaded,
        }


class DeferredToolLoader:
    """
    延迟工具加载器。
    - 工具注册：只存元信息，不执行加载逻辑
    - 按需搜索：按名称/描述关键词匹配
    - 频率排序：常用工具优先加载
    """

    def __init__(self) -> None:
        self._tools: dict[str, ToolInfo] = {}

    # ─── 注册 ────────────────────────────────────────────────────────────────
    def register(
        self,
        name: str,
        description: str,
        loader: Callable | None = None,
        category: str = "general",
    ) -> ToolInfo:
        """注册工具（不立即加载）。"""
        tool = ToolInfo(name=name, description=description, loader=loader, category=category)
        self._tools[name] = tool
        logger.debug(f"[DeferredLoader] 注册工具: {name}")
        return tool

    def register_builtin_tools(self) -> None:
        """注册内置的18个工具（懒加载占位）。"""
        builtins = [
            ("file_read",     "读取文件内容",          "io"),
            ("file_write",    "写入文件",              "io"),
            ("file_edit",     "编辑文件（增删改）",    "io"),
            ("file_search",   "搜索文件",              "io"),
            ("terminal_exec", "执行终端命令",          "system"),
            ("web_search",    "网络搜索",              "network"),
            ("web_fetch",     "抓取网页内容",          "network"),
            ("code_execute",  "代码执行（沙箱内）",    "system"),
            ("git_operation", "Git操作",               "vcs"),
            ("http_request",  "HTTP请求",              "network"),
            ("json_parse",    "JSON解析和处理",        "data"),
            ("regex_match",   "正则表达式匹配",        "data"),
            ("diff_compare",  "文件差异对比",          "io"),
            ("archive_zip",   "压缩/解压文件",         "io"),
            ("process_manager","进程管理",             "system"),
            ("env_manager",   "环境变量管理",          "system"),
            ("package_manager","包管理(pip/npm等)",    "system"),
            ("db_query",      "数据库查询",            "data"),
        ]
        for name, desc, cat in builtins:
            self.register(name, desc, category=cat)

    # ─── 查找 / 加载 ─────────────────────────────────────────────────────────
    def search(self, query: str, limit: int = 5) -> list[ToolInfo]:
        """
        按关键词搜索工具（名称+描述匹配）。
        按使用频率降序返回。
        """
        query_lower = query.lower()
        matches = []
        for tool in self._tools.values():
            if (query_lower in tool.name.lower()
                    or query_lower in tool.description.lower()):
                matches.append(tool)
        return sorted(matches, key=lambda t: t.usage_count, reverse=True)[:limit]

    def get(self, name: str) -> ToolInfo | None:
        """获取工具（不触发加载）。"""
        return self._tools.get(name)

    def use(self, name: str) -> Any | None:
        """获取并使用工具（触发延迟加载）。"""
        tool = self._tools.get(name)
        if tool:
            return tool.use()
        logger.warning(f"[DeferredLoader] 工具不存在: {name}")
        return None

    def list_by_category(self, category: str) -> list[ToolInfo]:
        return [t for t in self._tools.values() if t.category == category]

    def top_tools(self, n: int = 5) -> list[ToolInfo]:
        """最常用的工具。"""
        return sorted(self._tools.values(), key=lambda t: t.usage_count, reverse=True)[:n]

    def stats(self) -> dict:
        loaded = sum(1 for t in self._tools.values() if t.is_loaded)
        return {
            "registered": len(self._tools),
            "loaded": loaded,
            "unloaded": len(self._tools) - loaded,
            "top_tools": [t.to_dict() for t in self.top_tools(3)],
        }

    def __repr__(self) -> str:
        return f"DeferredToolLoader(registered={len(self._tools)})"

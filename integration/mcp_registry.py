"""
integration/mcp_registry.py — MCP Server 注册与管理器

管理多个 MCP Server 的连接池，聚合工具列表，路由调用请求。
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any

from .mcp_client import MCPClient

logger = logging.getLogger(__name__)


class MCPRegistry:
    """
    MCP Server 注册与管理器（单例）。

    职责：
    - 从 config.json 的 mcp.servers 段加载所有 Server 配置
    - 管理各 Server 的连接生命周期
    - 聚合所有 Server 的工具列表
    - 路由工具调用到对应的 Server
    """

    _instance: MCPRegistry | None = None

    def __init__(self) -> None:
        self._clients: dict[str, MCPClient] = {}

    @classmethod
    def get(cls) -> MCPRegistry:
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    @classmethod
    def reset(cls) -> None:
        cls._instance = None

    def load_from_config(self, servers_config: dict) -> None:
        """
        从配置字典加载 MCP Server。

        Args:
            servers_config: config.json 中 mcp.servers 段的内容，格式如：
                {
                    "filesystem": {"command": "npx", "args": ["mcp-server-filesystem", "./"]},
                    "git": {"command": "npx", "args": ["mcp-server-git"]},
                    "remote": {"url": "http://localhost:3000/sse", "transport": "sse"}
                }
        """
        for name, cfg in servers_config.items():
            client = MCPClient(
                server_name=name,
                command=cfg.get("command", ""),
                args=cfg.get("args", []),
                url=cfg.get("url", ""),
                transport=cfg.get("transport", "stdio"),
            )
            self._clients[name] = client
            logger.info(f"[MCPRegistry] 已注册 Server: {name}")

    async def connect_all(self) -> dict[str, bool]:
        """
        连接所有已注册的 MCP Server。

        Returns:
            {server_name: connected_status}
        """
        results = {}
        for name, client in self._clients.items():
            try:
                success = await client.connect()
                results[name] = success
            except Exception as e:
                logger.error(f"[MCPRegistry] 连接 {name} 失败: {e}")
                results[name] = False
        return results

    def connect_all_sync(self) -> dict[str, bool]:
        """同步版本的 connect_all()，用于非异步上下文。"""
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                # 已有事件循环运行中，创建任务
                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor() as pool:
                    future = pool.submit(asyncio.run, self.connect_all())
                    return future.result(timeout=30)
            else:
                return loop.run_until_complete(self.connect_all())
        except RuntimeError:
            return asyncio.run(self.connect_all())

    async def get_all_tools(self) -> list[dict]:
        """
        聚合所有已连接 Server 的工具列表。

        Returns:
            [{"server": "...", "name": "...", "description": "...", ...}, ...]
        """
        all_tools = []
        for name, client in self._clients.items():
            if client.connected:
                tools = await client.list_tools()
                for tool in tools:
                    tool["server"] = name
                    all_tools.append(tool)
        return all_tools

    def get_all_tools_sync(self) -> list[dict]:
        """同步版本的 get_all_tools()。"""
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                return []  # 无法在运行中的循环里同步等待
            return loop.run_until_complete(self.get_all_tools())
        except RuntimeError:
            return asyncio.run(self.get_all_tools())

    async def call(self, server_name: str, tool_name: str, arguments: dict) -> Any:
        """
        路由工具调用到指定的 MCP Server。
        """
        client = self._clients.get(server_name)
        if not client:
            return {"error": f"未知的 MCP Server: {server_name}"}
        if not client.connected:
            return {"error": f"MCP Server {server_name} 未连接"}
        return await client.call_tool(tool_name, arguments)

    async def disconnect_all(self) -> None:
        """断开所有 Server 连接。"""
        for client in self._clients.values():
            await client.disconnect()

    @property
    def server_names(self) -> list[str]:
        return list(self._clients.keys())

    @property
    def connected_count(self) -> int:
        return sum(1 for c in self._clients.values() if c.connected)

    def health(self) -> dict:
        return {
            "total_servers": len(self._clients),
            "connected": self.connected_count,
            "servers": {
                name: client.health()
                for name, client in self._clients.items()
            },
        }

    def stats(self) -> dict:
        return self.health()

"""
integration/mcp_client.py — MCP (Model Context Protocol) 客户端

封装对单个 MCP Server 的连接管理与工具调用。
当 mcp 包未安装时，自动降级为禁用状态。
"""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

# MCP SDK 为可选依赖
_MCP_AVAILABLE = False
try:
    import mcp

    _MCP_AVAILABLE = True
except ImportError:
    mcp = None  # type: ignore


class MCPClient:
    """
    封装对单个 MCP Server 的连接管理。

    支持两种连接模式：
    - stdio: 通过子进程 stdin/stdout 通信
    - sse: 通过 HTTP SSE 端点通信

    当 mcp 包未安装时，所有方法安全返回空值。
    """

    def __init__(
        self,
        server_name: str,
        command: str = "",
        args: list[str] | None = None,
        url: str = "",
        transport: str = "stdio",
    ) -> None:
        self.server_name = server_name
        self._command = command
        self._args = args or []
        self._url = url
        self._transport = transport
        self._connected = False
        self._tools: list[dict] = []
        self._session = None
        self._process = None

    @property
    def connected(self) -> bool:
        return self._connected

    async def connect(self) -> bool:
        """
        连接到 MCP Server。

        Returns:
            是否连接成功
        """
        if not _MCP_AVAILABLE:
            logger.info(
                f"[MCPClient:{self.server_name}] mcp 包未安装，跳过连接"
            )
            return False

        try:
            if self._transport == "stdio" and self._command:

                pass
                # 注意：实际连接需要在 async context manager 中保持活跃
                # 这里先标记为已配置，实际调用时再建立连接
                self._connected = True
                logger.info(
                    f"[MCPClient:{self.server_name}] 已配置 stdio 连接: "
                    f"{self._command} {' '.join(self._args)}"
                )
            elif self._transport == "sse" and self._url:
                self._connected = True
                logger.info(
                    f"[MCPClient:{self.server_name}] 已配置 SSE 连接: {self._url}"
                )
            else:
                logger.warning(
                    f"[MCPClient:{self.server_name}] 无效的连接配置"
                )
                return False

            return True
        except Exception as e:
            logger.error(f"[MCPClient:{self.server_name}] 连接失败: {e}")
            return False

    async def list_tools(self) -> list[dict]:
        """
        获取 Server 提供的工具清单。

        Returns:
            [{"name": "...", "description": "...", "parameters": {...}}, ...]
        """
        if not self._connected:
            return []

        # MCP 实际连接需要在运行时建立
        # 这里返回已缓存的工具列表
        return self._tools

    async def call_tool(self, tool_name: str, arguments: dict) -> Any:
        """
        调用 MCP Server 上的工具。

        Args:
            tool_name: 工具名称
            arguments: 工具参数

        Returns:
            工具执行结果
        """
        if not self._connected:
            return {"error": f"MCP Server {self.server_name} 未连接"}

        logger.info(
            f"[MCPClient:{self.server_name}] 调用工具: {tool_name}({arguments})"
        )

        # MCP 实际调用逻辑（需要活跃的 session）
        # 当前返回占位结果，实际实现需要在 async context 中运行
        return {
            "server": self.server_name,
            "tool": tool_name,
            "status": "not_implemented",
            "message": "MCP 工具调用需要活跃的 Server 进程",
        }

    async def disconnect(self) -> None:
        """断开连接并清理资源。"""
        if self._process:
            try:
                self._process.terminate()
            except Exception:
                pass
        self._connected = False
        self._session = None
        logger.info(f"[MCPClient:{self.server_name}] 已断开连接")

    def health(self) -> dict:
        return {
            "server_name": self.server_name,
            "connected": self._connected,
            "transport": self._transport,
            "tools_count": len(self._tools),
        }

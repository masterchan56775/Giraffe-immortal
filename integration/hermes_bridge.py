"""HermesBridge — Hermes桥接器（兼容层）

原有的 Hermes 桥接逻辑已升级为通过 MCPRegistry 进行标准化工具管理。
此类保留向下兼容接口。
"""
from __future__ import annotations
import logging
logger = logging.getLogger(__name__)

class HermesBridge:
    """连接Giraffe与外部框架的桥接器（兼容层）。"""
    def __init__(self, hermes_version: str = "unknown") -> None:
        self._version = hermes_version
        self._connected = False
        self._mcp_registry = None

    def set_mcp_registry(self, registry) -> None:
        """注入 MCPRegistry 实例。"""
        self._mcp_registry = registry

    def connect(self) -> bool:
        logger.info(f"[HermesBridge] 连接 v{self._version}")
        self._connected = True
        return True

    def disconnect(self) -> None:
        self._connected = False

    def sync_capabilities(self, capabilities: list[str]) -> dict:
        if not self._connected:
            return {"error": "未连接"}

        # 如果有 MCPRegistry，优先获取 MCP 工具列表
        mcp_tools = []
        if self._mcp_registry:
            mcp_tools = self._mcp_registry.get_all_tools_sync()

        logger.info(
            f"[HermesBridge] 同步 {len(capabilities)} 个能力, "
            f"{len(mcp_tools)} 个 MCP 工具"
        )
        return {
            "synced": len(capabilities),
            "mcp_tools": len(mcp_tools),
            "version": self._version,
        }

    @property
    def is_connected(self) -> bool:
        return self._connected


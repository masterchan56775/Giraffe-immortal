"""
integration/platforms/__init__.py — 平台适配器注册中心 (PlatformRegistry)

统一管理所有平台适配器的注册、启动、停止和消息分发。
GatewayAPI 通过此注册中心与各平台交互。

用法：
    from integration.platforms import PlatformRegistry

    registry = PlatformRegistry(message_handler=my_handler)
    registry.register("telegram", {"token": "xxx"})
    await registry.start_all()
    ...
    await registry.stop_all()
"""
from __future__ import annotations

import asyncio
import logging
from typing import Callable, Awaitable

from .base import PlatformAdapter, IncomingMessage, OutgoingMessage

logger = logging.getLogger(__name__)

# ── 平台 → 适配器类映射 ────────────────────────────────────────────────────────
_ADAPTER_MAP: dict[str, str] = {
    "telegram": "integration.platforms.telegram.TelegramAdapter",
    "discord":  "integration.platforms.discord.DiscordAdapter",
    "slack":    "integration.platforms.slack.SlackAdapter",
    "matrix":   "integration.platforms.matrix.MatrixAdapter",
    "webhook":  "integration.platforms.webhook.WebhookAdapter",
}

MessageHandler = Callable[[IncomingMessage], Awaitable[str | None]]


def _load_adapter_class(dotted_path: str):
    """动态导入适配器类（避免未安装依赖时全局报错）。"""
    module_path, cls_name = dotted_path.rsplit(".", 1)
    import importlib
    module = importlib.import_module(module_path)
    return getattr(module, cls_name)


class PlatformRegistry:
    """
    平台适配器注册中心（单例可选）。

    职责：
    - 管理多个平台适配器的生命周期
    - 将入站消息统一路由到 message_handler
    - 提供统一的出站发送接口
    """

    _instance: "PlatformRegistry | None" = None

    def __init__(self, message_handler: MessageHandler | None = None) -> None:
        self._adapters: dict[str, PlatformAdapter] = {}
        self._handler = message_handler
        self._custom_types: dict[str, type] = {}

    @classmethod
    def get(cls) -> "PlatformRegistry":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    @classmethod
    def reset(cls) -> None:
        cls._instance = None

    def set_handler(self, handler: MessageHandler) -> None:
        """设置全局消息处理回调（接收来自所有平台的消息）。"""
        self._handler = handler
        for adapter in self._adapters.values():
            adapter.set_handler(handler)

    def register_platform_type(self, name: str, cls: type) -> None:
        """注册自定义平台适配器类型。"""
        self._custom_types[name] = cls
        logger.info(f"[PlatformRegistry] 注册自定义适配器类型: {name}")

    def register(self, platform: str, config: dict) -> PlatformAdapter | None:
        """
        注册并实例化一个平台适配器。

        Args:
            platform: 平台名称（"telegram"/"discord"/"slack"/"matrix"/"webhook"）
            config:   平台配置字典

        Returns:
            成功返回适配器实例，依赖缺失时返回 None 并记录错误。
        """
        if platform in self._adapters:
            logger.warning(f"[PlatformRegistry] 平台已注册，跳过: {platform}")
            return self._adapters[platform]

        # 优先查找自定义类型
        if platform in self._custom_types:
            cls = self._custom_types[platform]
        elif platform in _ADAPTER_MAP:
            try:
                cls = _load_adapter_class(_ADAPTER_MAP[platform])
            except ImportError as e:
                logger.error(f"[PlatformRegistry] {platform} 依赖未安装: {e}")
                return None
        else:
            logger.error(f"[PlatformRegistry] 未知平台: {platform}。"
                         f"支持: {list(_ADAPTER_MAP.keys())}")
            return None

        try:
            adapter = cls(config)
        except ImportError as e:
            logger.error(f"[PlatformRegistry] {platform} 初始化失败（缺少依赖）: {e}")
            return None
        except Exception as e:
            logger.error(f"[PlatformRegistry] {platform} 初始化失败: {e}")
            return None

        if self._handler:
            adapter.set_handler(self._handler)

        self._adapters[platform] = adapter
        logger.info(f"[PlatformRegistry] 注册平台: {platform}")
        return adapter

    async def start(self, platform: str) -> bool:
        """启动指定平台适配器。"""
        adapter = self._adapters.get(platform)
        if not adapter:
            logger.error(f"[PlatformRegistry] 平台未注册: {platform}")
            return False
        try:
            await adapter.start()
            return True
        except Exception as e:
            logger.error(f"[PlatformRegistry] {platform} 启动失败: {e}")
            return False

    async def start_all(self) -> dict[str, bool]:
        """并行启动所有已注册的平台。"""
        results = await asyncio.gather(
            *[self.start(name) for name in self._adapters],
            return_exceptions=True,
        )
        return {
            name: (r is True)
            for name, r in zip(self._adapters.keys(), results)
        }

    async def stop(self, platform: str) -> None:
        """停止指定平台适配器。"""
        if adapter := self._adapters.get(platform):
            await adapter.stop()

    async def stop_all(self) -> None:
        """并行停止所有平台。"""
        await asyncio.gather(
            *[adapter.stop() for adapter in self._adapters.values()],
            return_exceptions=True,
        )
        logger.info("[PlatformRegistry] 所有平台已停止")

    async def send(self, platform: str, msg: OutgoingMessage) -> bool:
        """向指定平台发送消息。"""
        adapter = self._adapters.get(platform)
        if not adapter:
            logger.warning(f"[PlatformRegistry] 平台未注册: {platform}")
            return False
        return await adapter.send(msg)

    async def broadcast(self, msg: OutgoingMessage, platforms: list[str] | None = None) -> dict[str, bool]:
        """向多个平台广播同一条消息。"""
        targets = platforms or list(self._adapters.keys())
        results = await asyncio.gather(
            *[self.send(p, msg) for p in targets],
            return_exceptions=True,
        )
        return {p: (r is True) for p, r in zip(targets, results)}

    def get_adapter(self, platform: str) -> PlatformAdapter | None:
        return self._adapters.get(platform)

    def list_platforms(self) -> list[str]:
        return list(self._adapters.keys())

    def status(self) -> dict[str, dict]:
        """返回所有平台的运行状态。"""
        return {
            name: {
                "running": adapter.is_running(),
                "platform": adapter.platform_name,
            }
            for name, adapter in self._adapters.items()
        }

    def supported_platforms(self) -> list[str]:
        """返回所有支持的平台名称列表。"""
        return sorted(list(_ADAPTER_MAP.keys()) + list(self._custom_types.keys()))

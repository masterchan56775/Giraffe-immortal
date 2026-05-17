"""
integration/gateway_api.py — 统一网关（单例）
统一管理所有接入渠道（CLI / Web / API / 平台适配器）的消息收发。
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Callable

logger = logging.getLogger(__name__)


class GatewayAPI:
    """
    统一网关（单例模式）。
    统一管理所有接入渠道（CLI / Web / API）的消息收发，
    并通过 PlatformRegistry 对接各平台适配器。
    """

    _instance: GatewayAPI | None = None

    def __init__(self) -> None:
        self._platforms: dict[str, dict] = {}   # 旧版兼容（保留简单平台注册）
        self._message_handlers: list[Callable] = []
        self._healthy = True
        self._router = None
        self._executor = None
        self._event_bus = None
        self._platform_registry = None          # PlatformRegistry（懒加载）

    @classmethod
    def get(cls) -> "GatewayAPI":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    @classmethod
    def reset(cls) -> None:
        cls._instance = None

    # ─── 初始化 ───────────────────────────────────────────────────────────────
    def initialize(self, router=None, executor=None) -> None:
        """注入路由引擎和执行管道，并挂载 EventBus。"""
        self._router = router
        self._executor = executor
        from integration.event_stream import EventBus
        self._event_bus = EventBus.get()
        logger.info("[GatewayAPI] 初始化完成")

    # ─── PlatformRegistry 集成 ────────────────────────────────────────────────
    def get_platform_registry(self):
        """懒加载 PlatformRegistry 单例。"""
        if self._platform_registry is None:
            from integration.platforms import PlatformRegistry
            self._platform_registry = PlatformRegistry.get()
            # 将消息处理器桥接到 Registry
            if self._message_handlers:
                self._platform_registry.set_handler(self._make_async_handler())
        return self._platform_registry

    def _make_async_handler(self):
        """将同步 message_handlers 包装为 async handler 供 PlatformRegistry 使用。"""
        from integration.platforms.base import IncomingMessage

        async def _handler(msg: IncomingMessage) -> str | None:
            loop = asyncio.get_event_loop()
            for h in self._message_handlers:
                try:
                    result = await loop.run_in_executor(
                        None, lambda: h(msg.text, msg.platform)
                    )
                    if result:
                        return result
                except Exception as e:
                    logger.error(f"[GatewayAPI] 处理器错误: {e}")
            return None

        return _handler

    def add_platform(self, platform: str, config: dict):
        """
        注册并启动一个平台适配器（推荐的现代接口）。

        返回适配器实例（或 None，若依赖未安装）。
        """
        registry = self.get_platform_registry()
        return registry.register(platform, config)

    async def start_platform(self, platform: str) -> bool:
        """异步启动指定平台适配器。"""
        registry = self.get_platform_registry()
        return await registry.start(platform)

    async def stop_platform(self, platform: str) -> None:
        """停止指定平台适配器。"""
        registry = self.get_platform_registry()
        await registry.stop(platform)

    async def start_all_platforms(self) -> dict[str, bool]:
        """并行启动所有已注册平台。"""
        return await self.get_platform_registry().start_all()

    async def stop_all_platforms(self) -> None:
        """并行停止所有平台。"""
        await self.get_platform_registry().stop_all()

    def platform_status(self) -> dict:
        """返回所有平台适配器的运行状态。"""
        return self.get_platform_registry().status()

    def supported_platforms(self) -> list[str]:
        """返回系统支持的所有平台列表。"""
        from integration.platforms import PlatformRegistry
        return PlatformRegistry.get().supported_platforms()

    # ─── 旧版简单平台注册接口（保留兼容）────────────────────────────────────
    def register_platform(self, name: str, config: dict) -> None:
        """注册一个平台配置（简单 KV，不启动适配器）。"""
        self._platforms[name] = config
        logger.info(f"[GatewayAPI] 注册平台: {name}")

    def deregister_platform(self, name: str) -> bool:
        if name in self._platforms:
            del self._platforms[name]
            logger.info(f"[GatewayAPI] 注销平台: {name}")
            return True
        return False

    def list_platforms(self) -> list[str]:
        """列出所有已注册平台（简单 + 适配器）。"""
        simple = list(self._platforms.keys())
        if self._platform_registry:
            return list(set(simple + self._platform_registry.list_platforms()))
        return simple

    def get_platform_config(self, name: str) -> dict:
        return self._platforms.get(name, {})

    # ─── 消息处理 ─────────────────────────────────────────────────────────────
    def route_and_get_runtime(self, message: str, has_image: bool = False) -> tuple[str, dict]:
        """一次调用返回模型+运行时配置。"""
        if self._router:
            return self._router.route_and_get_runtime(message, has_image)
        return "gemini-3-flash-preview", {"task_type": "chat", "auto_execute": True}

    def send_message(self, platform: str, content: str, **kwargs) -> bool:
        """向指定平台发送消息（同步接口，适用于 CLI 上下文）。"""
        if platform not in self._platforms:
            logger.warning(f"[GatewayAPI] 平台未注册: {platform}")
            return False
        logger.info(f"[GatewayAPI] → {platform}: {content[:50]}...")
        return True

    def on_message(self, handler: Callable) -> None:
        """注册消息处理器（兼容旧版）。"""
        self._message_handlers.append(handler)
        if self._platform_registry:
            self._platform_registry.set_handler(self._make_async_handler())

    def dispatch(self, message: str, platform: str = "cli") -> Any:
        """分发消息到所有注册的处理器，通过 EventBus 发布事件。"""
        if self._event_bus:
            self._event_bus.emit("dispatch_start", message=message[:100], platform=platform)

        result = None
        for handler in self._message_handlers:
            try:
                result = handler(message, platform)
                if self._event_bus:
                    self._event_bus.emit("dispatch_end", platform=platform, success=True)
                return result
            except Exception as e:
                logger.error(f"[GatewayAPI] 处理器错误: {e}")
                if self._event_bus:
                    self._event_bus.emit("dispatch_error", platform=platform, error=str(e))

        return result

    # ─── Web 服务 ─────────────────────────────────────────────────────────────
    def start_web_server(self, host: str = "0.0.0.0", port: int = 8000) -> None:
        """启动 FastAPI Web 服务（阻塞模式）。"""
        try:
            import uvicorn
            from integration.web_server import create_app
        except ImportError:
            logger.error(
                "[GatewayAPI] 缺少依赖: uvicorn 或 fastapi。"
                "请运行: pip install fastapi uvicorn"
            )
            return

        app = create_app()

        # 挂载 Webhook 适配器端点（如已注册）
        if self._platform_registry:
            webhook = self._platform_registry.get_adapter("webhook")
            if webhook and hasattr(webhook, "mount_to_app"):
                webhook.mount_to_app(app)

        logger.info(f"[GatewayAPI] 启动 Web 服务: http://{host}:{port}")
        uvicorn.run(app, host=host, port=port, log_level="warning")

    # ─── 健康检查 ─────────────────────────────────────────────────────────────
    def health_check(self) -> dict:
        """系统健康检查。"""
        status = "healthy" if self._healthy else "degraded"
        result = {
            "status": status,
            "healthy": self._healthy,
            "platforms": self.list_platforms(),
            "handlers": len(self._message_handlers),
            "router": self._router is not None,
            "executor": self._executor is not None,
        }
        if self._platform_registry:
            result["platform_status"] = self._platform_registry.status()
        return result

    def reset_state(self) -> None:
        """重置状态（出问题时快速恢复）。"""
        self._message_handlers.clear()
        self._healthy = True
        logger.info("[GatewayAPI] 状态已重置")

    def __repr__(self) -> str:
        return f"GatewayAPI(platforms={self.list_platforms()})"

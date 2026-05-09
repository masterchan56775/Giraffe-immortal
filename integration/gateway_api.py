"""
integration/gateway_api.py — 统一网关（单例）
统一管理所有平台的消息收发，集成 EventBus 实现事件驱动。
"""
from __future__ import annotations

import logging
from typing import Any, Callable

logger = logging.getLogger(__name__)


class GatewayAPI:
    """
    统一网关（单例模式）。
    一个入口管理所有平台（飞书/微信/企业微信/CLI/TUI）的消息收发。
    """

    _instance: GatewayAPI | None = None

    def __init__(self) -> None:
        self._platforms: dict[str, dict] = {}
        self._message_handlers: list[Callable] = []
        self._healthy = True
        self._router = None
        self._executor = None
        self._event_bus = None   # 在 initialize() 中注入

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

    def register_platform(self, name: str, config: dict) -> None:
        """注册一个新平台。"""
        self._platforms[name] = config
        logger.info(f"[GatewayAPI] 注册平台: {name}")

    def deregister_platform(self, name: str) -> bool:
        """注销一个平台。"""
        if name in self._platforms:
            del self._platforms[name]
            logger.info(f"[GatewayAPI] 注销平台: {name}")
            return True
        return False

    def list_platforms(self) -> list[str]:
        return list(self._platforms.keys())

    def get_platform_config(self, name: str) -> dict:
        return self._platforms.get(name, {})

    # ─── 消息处理 ─────────────────────────────────────────────────────────────
    def route_and_get_runtime(self, message: str, has_image: bool = False) -> tuple[str, dict]:
        """一次调用返回模型+运行时配置。"""
        if self._router:
            return self._router.route_and_get_runtime(message, has_image)
        return "gemini-3-flash-preview", {"task_type": "chat", "auto_execute": True}

    def send_message(self, platform: str, content: str, **kwargs) -> bool:
        """向指定平台发送消息。"""
        if platform not in self._platforms:
            logger.warning(f"[GatewayAPI] 平台未注册: {platform}")
            return False
        logger.info(f"[GatewayAPI] → {platform}: {content[:50]}...")
        return True

    def on_message(self, handler: Callable) -> None:
        """注册消息处理器。"""
        self._message_handlers.append(handler)

    def dispatch(self, message: str, platform: str = "cli") -> Any:
        """分发消息到所有注册的处理器，每个关键阶段通过 EventBus 发布事件。"""
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
        """
        启动 FastAPI Web 服务（阻塞模式）。
        包含 REST、SSE 和 WebSocket 端点。
        """
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
        logger.info(f"[GatewayAPI] 启动 Web 服务: http://{host}:{port}")
        uvicorn.run(app, host=host, port=port, log_level="info")

    # ─── 健康检查 ─────────────────────────────────────────────────────────────
    def health_check(self) -> dict:
        """系统健康检查。"""
        status = "healthy" if self._healthy else "degraded"
        return {
            "status": status,
            "healthy": self._healthy,
            "platforms": list(self._platforms.keys()),
            "handlers": len(self._message_handlers),
            "router": self._router is not None,
            "executor": self._executor is not None,
        }

    def reset_state(self) -> None:
        """重置状态（出问题时快速恢复）。"""
        self._message_handlers.clear()
        self._healthy = True
        logger.info("[GatewayAPI] 状态已重置")

    def __repr__(self) -> str:
        return f"GatewayAPI(platforms={list(self._platforms.keys())})"

"""
integration/platforms/slack.py — Slack 平台适配器

支持 Socket Mode（推荐，无需公网）和 Events API（需 HTTPS）。

依赖（可选安装）：
    pip install slack-bolt

配置示例（config.json）：
    "slack": {
        "bot_token":  "xoxb-...",      # Bot OAuth Token
        "app_token":  "xapp-...",      # App-Level Token（Socket Mode 必需）
        "mode":       "socket",        # "socket" | "events_api"
        "port":       3000             # events_api 模式的监听端口
    }
"""
from __future__ import annotations

import asyncio
import base64
import logging

from .base import PlatformAdapter, IncomingMessage, OutgoingMessage

logger = logging.getLogger(__name__)

_SLACK_AVAILABLE = False
try:
    from slack_bolt import App
    from slack_bolt.adapter.socket_mode import SocketModeHandler
    _SLACK_AVAILABLE = True
except ImportError:
    pass


class SlackAdapter(PlatformAdapter):
    """
    Slack Bot 适配器。

    config 参数：
        bot_token   (必需) Bot OAuth Token（xoxb-...）
        app_token   Socket Mode 必需（xapp-...）
        mode        "socket"（默认）| "events_api"
        port        events_api 模式端口（默认 3000）
        signing_secret  events_api 模式需要
    """

    platform_name = "slack"

    def __init__(self, config: dict) -> None:
        super().__init__(config)
        if not _SLACK_AVAILABLE:
            raise ImportError(
                "slack-bolt 未安装。\n"
                "请运行: pip install slack-bolt"
            )
        self._bot_token: str = config["bot_token"]
        self._app_token: str = config.get("app_token", "")
        self._mode: str = config.get("mode", "socket")
        self._slack_app: App | None = None
        self._handler = None
        self._loop: asyncio.AbstractEventLoop | None = None

    async def start(self) -> None:
        self._loop = asyncio.get_event_loop()
        self._slack_app = App(token=self._bot_token)

        # 注册事件监听
        @self._slack_app.event("message")
        def on_message(event, say, client):
            self._loop.call_soon_threadsafe(
                asyncio.ensure_future,
                self._handle_slack_event(event, say, client),
            )

        self._running = True

        if self._mode == "socket":
            if not self._app_token:
                raise ValueError("[Slack] Socket Mode 需要提供 app_token")
            # SocketModeHandler 是阻塞的，在线程池中运行
            import concurrent.futures
            executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
            self._loop.run_in_executor(
                executor,
                lambda: SocketModeHandler(self._slack_app, self._app_token).start(),
            )
            logger.info("[Slack] 以 Socket Mode 启动")
        else:
            port = self._config.get("port", 3000)
            executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
            self._loop.run_in_executor(
                executor,
                lambda: self._slack_app.start(port=port),
            )
            logger.info(f"[Slack] 以 Events API 模式启动，端口 {port}")

    async def stop(self) -> None:
        self._running = False
        logger.info("[Slack] 已停止")

    async def send(self, msg: OutgoingMessage) -> bool:
        if not self._slack_app:
            return False
        try:
            self._slack_app.client.chat_postMessage(
                channel=msg.chat_id,
                text=msg.text,
                **msg.extra,
            )
            return True
        except Exception as e:
            logger.error(f"[Slack] 发送失败: {e}")
            return False

    async def send_blocks(self, channel: str, blocks: list[dict]) -> bool:
        """发送 Block Kit 格式消息（富文本/交互组件）。"""
        if not self._slack_app:
            return False
        try:
            self._slack_app.client.chat_postMessage(
                channel=channel,
                blocks=blocks,
            )
            return True
        except Exception as e:
            logger.error(f"[Slack] Block Kit 发送失败: {e}")
            return False

    async def _handle_slack_event(self, event: dict, say, client) -> None:
        user_id = event.get("user", "")
        text = event.get("text", "")
        channel = event.get("channel", "")
        ts = event.get("ts", "")

        # 忽略 bot 自身消息
        if event.get("bot_id"):
            return

        incoming = IncomingMessage(
            platform=self.platform_name,
            chat_id=channel,
            user_id=user_id,
            text=text,
            message_id=ts,
        )
        reply = await self._dispatch(incoming)
        if reply:
            out = OutgoingMessage(chat_id=channel, text=reply, reply_to_id=ts)
            await self.send(out)

"""
integration/platforms/telegram.py — Telegram 平台适配器

支持两种工作模式：
1. Polling（默认）— 无需公网服务器，直接拉取消息
2. Webhook — 需要 HTTPS 域名，消息实时推送

依赖（可选安装）：
    pip install python-telegram-bot

不安装时，实例化会抛出 ImportError（由 PlatformRegistry 优雅处理）。
"""
from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

from .base import PlatformAdapter, IncomingMessage, OutgoingMessage

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)

_TELEGRAM_AVAILABLE = False
try:
    import telegram
    from telegram import Update, Bot
    from telegram.ext import (
        Application, CommandHandler, MessageHandler as TGMessageHandler,
        filters, ContextTypes,
    )
    _TELEGRAM_AVAILABLE = True
except ImportError:
    pass


class TelegramAdapter(PlatformAdapter):
    """
    Telegram Bot 适配器。

    config 参数：
        token        (必需) Bot Token，从 @BotFather 获取
        mode         "polling"（默认）| "webhook"
        webhook_url  webhook 模式下的 HTTPS URL
        webhook_port webhook 监听端口（默认 8443）
        allowed_updates 监听的事件类型列表
        timeout      polling 超时秒数（默认 30）
    """

    platform_name = "telegram"

    def __init__(self, config: dict) -> None:
        super().__init__(config)
        if not _TELEGRAM_AVAILABLE:
            raise ImportError(
                "python-telegram-bot 未安装。\n"
                "请运行: pip install python-telegram-bot"
            )
        self._token: str = config["token"]
        self._mode: str = config.get("mode", "polling")
        self._app: Application | None = None

    async def start(self) -> None:
        """启动 Bot（polling 或 webhook）。"""
        self._app = (
            Application.builder()
            .token(self._token)
            .build()
        )

        # 注册消息处理器
        self._app.add_handler(
            TGMessageHandler(filters.TEXT & ~filters.COMMAND, self._on_text)
        )
        self._app.add_handler(
            TGMessageHandler(filters.PHOTO, self._on_photo)
        )
        self._app.add_handler(
            CommandHandler("start", self._on_start_cmd)
        )
        self._app.add_handler(
            CommandHandler("help", self._on_help_cmd)
        )

        self._running = True
        logger.info(f"[Telegram] 启动 ({self._mode} 模式)")

        if self._mode == "webhook":
            webhook_url = self._config.get("webhook_url")
            port = self._config.get("webhook_port", 8443)
            if not webhook_url:
                raise ValueError("[Telegram] webhook 模式需要提供 webhook_url")
            await self._app.initialize()
            await self._app.start()
            await self._app.bot.set_webhook(webhook_url)
            # webhook 模式下 web_server 由外部 FastAPI 接管，此处不启动额外监听
        else:
            # Polling 模式（开发/无公网场景推荐）
            await self._app.initialize()
            await self._app.start()
            await self._app.updater.start_polling(
                timeout=self._config.get("timeout", 30),
                allowed_updates=self._config.get("allowed_updates", ["message"]),
            )

    async def stop(self) -> None:
        """停止 Bot。"""
        self._running = False
        if self._app:
            if self._mode == "polling":
                await self._app.updater.stop()
            await self._app.stop()
            await self._app.shutdown()
            logger.info("[Telegram] 已停止")

    async def send(self, msg: OutgoingMessage) -> bool:
        """发送消息到 Telegram 聊天。"""
        if not self._app:
            logger.warning("[Telegram] 尚未启动，无法发送消息")
            return False
        try:
            parse_mode_map = {
                "markdown": telegram.constants.ParseMode.MARKDOWN_V2,
                "html":     telegram.constants.ParseMode.HTML,
                "plain":    None,
            }
            pm = parse_mode_map.get(msg.parse_mode)
            text = _escape_markdown(msg.text) if pm == telegram.constants.ParseMode.MARKDOWN_V2 else msg.text

            kwargs: dict = {
                "chat_id": msg.chat_id,
                "text": text,
                "disable_web_page_preview": msg.disable_preview,
            }
            if pm:
                kwargs["parse_mode"] = pm
            if msg.reply_to_id:
                kwargs["reply_to_message_id"] = msg.reply_to_id

            await self._app.bot.send_message(**kwargs)
            return True
        except Exception as e:
            logger.error(f"[Telegram] 发送失败: {e}")
            return False

    async def send_photo(self, chat_id: str, photo_url_or_bytes: str | bytes,
                         caption: str = "") -> bool:
        """发送图片到 Telegram 聊天。"""
        if not self._app:
            return False
        try:
            await self._app.bot.send_photo(
                chat_id=chat_id,
                photo=photo_url_or_bytes,
                caption=caption,
            )
            return True
        except Exception as e:
            logger.error(f"[Telegram] 发送图片失败: {e}")
            return False

    # ── 内部事件处理 ──────────────────────────────────────────────────────────

    async def _on_text(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        msg = update.message
        if not msg or not msg.text:
            return
        incoming = IncomingMessage(
            platform=self.platform_name,
            chat_id=str(msg.chat_id),
            user_id=str(msg.from_user.id) if msg.from_user else "",
            username=msg.from_user.username or "" if msg.from_user else "",
            text=msg.text,
            message_id=str(msg.message_id),
        )
        reply = await self._dispatch(incoming)
        if reply:
            out = OutgoingMessage(
                chat_id=str(msg.chat_id),
                text=reply,
                reply_to_id=str(msg.message_id),
            )
            await self.send(out)

    async def _on_photo(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        msg = update.message
        if not msg:
            return
        # 下载最大尺寸的图片
        photo = msg.photo[-1] if msg.photo else None
        images = []
        if photo:
            try:
                file = await ctx.bot.get_file(photo.file_id)
                import io
                import base64
                buf = io.BytesIO()
                await file.download_to_memory(buf)
                images = [f"data:image/jpeg;base64,{base64.b64encode(buf.getvalue()).decode()}"]
            except Exception as e:
                logger.warning(f"[Telegram] 图片下载失败: {e}")

        incoming = IncomingMessage(
            platform=self.platform_name,
            chat_id=str(msg.chat_id),
            user_id=str(msg.from_user.id) if msg.from_user else "",
            text=msg.caption or "",
            message_id=str(msg.message_id),
            images=images,
        )
        reply = await self._dispatch(incoming)
        if reply:
            out = OutgoingMessage(chat_id=str(msg.chat_id), text=reply, reply_to_id=str(msg.message_id))
            await self.send(out)

    async def _on_start_cmd(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        if update.message:
            await update.message.reply_text("👋 你好！我是 Giraffe AI 助手，有什么可以帮你？")

    async def _on_help_cmd(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        if update.message:
            await update.message.reply_text(
                "📋 *使用说明*\n\n"
                "直接发送文字即可与我对话。\n"
                "可以发送图片，我会分析图片内容。\n\n"
                "命令：\n"
                "/start — 开始\n"
                "/help — 帮助",
                parse_mode="Markdown",
            )


def _escape_markdown(text: str) -> str:
    """为 MarkdownV2 转义特殊字符。"""
    special = r"\_*[]()~`>#+-=|{}.!"
    return "".join(f"\\{c}" if c in special else c for c in text)

"""
integration/platforms/discord.py — Discord 平台适配器

依赖（可选安装）：
    pip install discord.py

支持：文字消息、图片附件、斜杠命令（/chat）、Embed 格式回复。
"""
from __future__ import annotations

import asyncio
import base64
import io
import logging
from typing import TYPE_CHECKING

from .base import PlatformAdapter, IncomingMessage, OutgoingMessage

logger = logging.getLogger(__name__)

_DISCORD_AVAILABLE = False
try:
    import discord
    from discord.ext import commands
    _DISCORD_AVAILABLE = True
except ImportError:
    pass


class DiscordAdapter(PlatformAdapter):
    """
    Discord Bot 适配器。

    config 参数：
        token          (必需) Bot Token，从 Discord Developer Portal 获取
        command_prefix 命令前缀（默认 "!"）
        intents        需要的权限列表（默认 message_content + guilds）
        use_embed      是否使用 Embed 格式回复（默认 True）
        max_length     单条消息最大长度（Discord 限制 2000，默认自动分割）
    """

    platform_name = "discord"

    def __init__(self, config: dict) -> None:
        super().__init__(config)
        if not _DISCORD_AVAILABLE:
            raise ImportError(
                "discord.py 未安装。\n"
                "请运行: pip install discord.py"
            )
        self._token: str = config["token"]
        self._client: discord.Client | None = None
        self._use_embed: bool = config.get("use_embed", True)
        self._max_length: int = config.get("max_length", 1900)

    async def start(self) -> None:
        """启动 Discord Bot。"""
        intents = discord.Intents.default()
        intents.message_content = True

        self._client = discord.Client(intents=intents)

        @self._client.event
        async def on_ready():
            logger.info(f"[Discord] 已登录: {self._client.user} (id={self._client.user.id})")
            self._running = True

        @self._client.event
        async def on_message(message: discord.Message):
            # 忽略自身消息
            if message.author == self._client.user:
                return
            await self._handle_message(message)

        logger.info("[Discord] 正在连接...")
        # 在后台启动（非阻塞）
        asyncio.create_task(self._client.start(self._token))

    async def stop(self) -> None:
        """关闭 Discord 连接。"""
        self._running = False
        if self._client:
            await self._client.close()
            logger.info("[Discord] 已断开")

    async def send(self, msg: OutgoingMessage) -> bool:
        """发送消息到 Discord 频道。"""
        if not self._client:
            return False
        try:
            channel = self._client.get_channel(int(msg.chat_id))
            if channel is None:
                channel = await self._client.fetch_channel(int(msg.chat_id))

            chunks = _split_text(msg.text, self._max_length)
            for i, chunk in enumerate(chunks):
                if self._use_embed and i == len(chunks) - 1:
                    embed = discord.Embed(description=chunk, color=0x5865F2)
                    await channel.send(embed=embed)
                else:
                    await channel.send(chunk)
            return True
        except Exception as e:
            logger.error(f"[Discord] 发送失败: {e}")
            return False

    async def _handle_message(self, message: discord.Message) -> None:
        # 提取图片附件
        images = []
        for att in message.attachments:
            if att.content_type and att.content_type.startswith("image/"):
                try:
                    data = await att.read()
                    b64 = base64.b64encode(data).decode()
                    images.append(f"data:{att.content_type};base64,{b64}")
                except Exception as e:
                    logger.warning(f"[Discord] 附件读取失败: {e}")

        incoming = IncomingMessage(
            platform=self.platform_name,
            chat_id=str(message.channel.id),
            user_id=str(message.author.id),
            username=str(message.author.name),
            text=message.content,
            message_id=str(message.id),
            images=images,
        )
        reply = await self._dispatch(incoming)
        if reply:
            out = OutgoingMessage(chat_id=str(message.channel.id), text=reply)
            await self.send(out)


def _split_text(text: str, max_len: int) -> list[str]:
    """将长文本按段落分割，不超过 max_len。"""
    if len(text) <= max_len:
        return [text]
    chunks, current = [], ""
    for para in text.split("\n"):
        if len(current) + len(para) + 1 <= max_len:
            current += ("" if not current else "\n") + para
        else:
            if current:
                chunks.append(current)
            current = para[:max_len]
    if current:
        chunks.append(current)
    return chunks or [text[:max_len]]

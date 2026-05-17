"""
integration/platforms/base.py — 平台适配器基类

所有平台适配器（Telegram、Discord、Slack、Matrix 等）均继承此基类。
"""
from __future__ import annotations

import asyncio
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Callable, Awaitable

logger = logging.getLogger(__name__)


# ── 通用消息数据结构 ──────────────────────────────────────────────────────────

@dataclass
class IncomingMessage:
    """标准化的入站消息（从平台接收）。"""
    platform: str            # 平台名称，如 "telegram"
    chat_id: str             # 会话/频道 ID
    user_id: str             # 发送者 ID
    text: str                # 消息文本
    message_id: str = ""     # 平台原始消息 ID（用于回复/引用）
    username: str = ""       # 发送者用户名（可选）
    images: list[str] = field(default_factory=list)   # base64 编码图片
    raw: dict = field(default_factory=dict)            # 平台原始 payload


@dataclass
class OutgoingMessage:
    """标准化的出站消息（发送到平台）。"""
    chat_id: str
    text: str
    reply_to_id: str = ""        # 引用回复的消息 ID
    parse_mode: str = "markdown" # markdown / html / plain
    disable_preview: bool = True
    extra: dict = field(default_factory=dict)  # 平台特有参数


# ── 平台适配器抽象基类 ────────────────────────────────────────────────────────

MessageHandler = Callable[[IncomingMessage], Awaitable[str | None]]


class PlatformAdapter(ABC):
    """
    平台适配器基类。

    子类需实现：
    - start()      启动监听（polling / webhook）
    - stop()       停止监听
    - send()       发送消息到平台
    - platform_name  平台名称属性
    """

    def __init__(self, config: dict) -> None:
        self._config = config
        self._handler: MessageHandler | None = None
        self._running = False

    @property
    @abstractmethod
    def platform_name(self) -> str:
        """平台标识符，如 'telegram'、'discord'。"""

    @abstractmethod
    async def start(self) -> None:
        """启动消息监听（polling 或 webhook 模式）。"""

    @abstractmethod
    async def stop(self) -> None:
        """优雅停止监听。"""

    @abstractmethod
    async def send(self, msg: OutgoingMessage) -> bool:
        """发送消息到平台，成功返回 True。"""

    def set_handler(self, handler: MessageHandler) -> None:
        """注册消息处理回调。"""
        self._handler = handler

    async def _dispatch(self, msg: IncomingMessage) -> str | None:
        """内部调用：将入站消息转发给处理器。"""
        if self._handler:
            try:
                return await self._handler(msg)
            except Exception as e:
                logger.error(f"[{self.platform_name}] 消息处理器异常: {e}", exc_info=True)
        return None

    def is_running(self) -> bool:
        return self._running

    def get_config(self, key: str, default: Any = None) -> Any:
        return self._config.get(key, default)

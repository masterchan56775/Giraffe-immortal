"""
integration/platforms/matrix.py — Matrix 平台适配器

Matrix 是去中心化的开放通讯协议，Element/Beeper 等客户端均支持。

依赖（可选安装）：
    pip install matrix-nio

配置示例：
    "matrix": {
        "homeserver": "https://matrix.org",
        "user_id":    "@bot:matrix.org",
        "password":   "...",         # 密码登录
        "access_token": "...",       # 或直接用 access_token
        "device_name": "giraffe-bot",
        "store_path":  "~/.giraffe/matrix_store"
    }
"""
from __future__ import annotations

import asyncio
import logging

from .base import PlatformAdapter, IncomingMessage, OutgoingMessage

logger = logging.getLogger(__name__)

_MATRIX_AVAILABLE = False
try:
    from nio import AsyncClient, MatrixRoom, RoomMessageText, LoginResponse
    _MATRIX_AVAILABLE = True
except ImportError:
    pass


class MatrixAdapter(PlatformAdapter):
    """
    Matrix Bot 适配器（基于 matrix-nio）。

    config 参数：
        homeserver   (必需) 矩阵服务器 URL
        user_id      (必需) Bot 的 Matrix ID
        password     密码登录（与 access_token 二选一）
        access_token Token 登录（推荐）
        device_name  设备名称（默认 "giraffe"）
        store_path   本地加密状态存储路径
    """

    platform_name = "matrix"

    def __init__(self, config: dict) -> None:
        super().__init__(config)
        if not _MATRIX_AVAILABLE:
            raise ImportError(
                "matrix-nio 未安装。\n"
                "请运行: pip install matrix-nio"
            )
        self._homeserver: str = config["homeserver"]
        self._user_id: str = config["user_id"]
        self._client: AsyncClient | None = None

    async def start(self) -> None:
        import os
        store_path = os.path.expanduser(self._config.get("store_path", "~/.giraffe/matrix_store"))
        os.makedirs(store_path, exist_ok=True)

        self._client = AsyncClient(
            self._homeserver,
            self._user_id,
            store_path=store_path,
        )

        # 登录
        if token := self._config.get("access_token"):
            self._client.access_token = token
            self._client.user_id = self._user_id
            logger.info("[Matrix] 使用 access_token 登录")
        elif pwd := self._config.get("password"):
            resp = await self._client.login(
                pwd, device_name=self._config.get("device_name", "giraffe")
            )
            if not isinstance(resp, LoginResponse):
                raise RuntimeError(f"[Matrix] 登录失败: {resp}")
            logger.info("[Matrix] 密码登录成功")
        else:
            raise ValueError("[Matrix] 需要提供 access_token 或 password")

        # 注册事件回调
        self._client.add_event_callback(self._on_message, RoomMessageText)

        self._running = True
        logger.info(f"[Matrix] 开始同步: {self._user_id}@{self._homeserver}")
        # 持续同步（阻塞，在独立 Task 中运行）
        asyncio.create_task(self._sync_loop())

    async def stop(self) -> None:
        self._running = False
        if self._client:
            await self._client.close()
            logger.info("[Matrix] 已断开")

    async def send(self, msg: OutgoingMessage) -> bool:
        if not self._client:
            return False
        try:
            content = {
                "msgtype": "m.text",
                "body": msg.text,
            }
            if msg.parse_mode == "markdown":
                import re
                html = _simple_md_to_html(msg.text)
                content["format"] = "org.matrix.custom.html"
                content["formatted_body"] = html

            await self._client.room_send(
                room_id=msg.chat_id,
                message_type="m.room.message",
                content=content,
            )
            return True
        except Exception as e:
            logger.error(f"[Matrix] 发送失败: {e}")
            return False

    async def _sync_loop(self) -> None:
        while self._running and self._client:
            try:
                await self._client.sync(timeout=30000)
            except Exception as e:
                logger.warning(f"[Matrix] 同步错误: {e}")
                await asyncio.sleep(5)

    async def _on_message(self, room: MatrixRoom, event: RoomMessageText) -> None:
        # 忽略自身消息
        if event.sender == self._user_id:
            return
        incoming = IncomingMessage(
            platform=self.platform_name,
            chat_id=room.room_id,
            user_id=event.sender,
            text=event.body,
            message_id=event.event_id,
        )
        reply = await self._dispatch(incoming)
        if reply:
            out = OutgoingMessage(chat_id=room.room_id, text=reply)
            await self.send(out)


def _simple_md_to_html(text: str) -> str:
    """简单 Markdown → HTML 转换（供 Matrix 富文本使用）。"""
    import re
    text = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', text)
    text = re.sub(r'\*(.+?)\*', r'<em>\1</em>', text)
    text = re.sub(r'`(.+?)`', r'<code>\1</code>', text)
    text = text.replace('\n', '<br/>')
    return text

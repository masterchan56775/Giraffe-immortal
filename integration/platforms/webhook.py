"""
integration/platforms/webhook.py — 通用 Webhook 适配器

适用于任意支持 HTTP Webhook 的平台（GitHub、Linear、Notion、自定义系统等）。
同时作为 Telegram/Discord webhook 模式的接收端。

特性：
- 多端点支持：每个平台可注册独立路径
- HMAC 签名验证（可选）
- 支持出站 HTTP 推送（主动 Webhook 回调）
"""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
from typing import Callable, Awaitable

import urllib.request
import urllib.parse

from .base import PlatformAdapter, IncomingMessage, OutgoingMessage

logger = logging.getLogger(__name__)

_FASTAPI_AVAILABLE = False
try:
    from fastapi import FastAPI, Request, HTTPException
    _FASTAPI_AVAILABLE = True
except ImportError:
    pass


WebhookHandler = Callable[[dict, str], Awaitable[str | None]]


class WebhookAdapter(PlatformAdapter):
    """
    通用 Webhook 接收器 + 出站推送适配器。

    config 参数：
        endpoints    dict[path → {"secret": str, "platform": str}]
                     注册的 webhook 路径，如 {"/webhook/github": {"secret": "abc"}}
        callback_url 出站推送的目标 URL（可选）
        callback_method  "POST"（默认）| "GET"
        secret       全局 HMAC 签名密钥（各端点可独立覆盖）
        timeout      出站请求超时（默认 10s）

    使用方式：
        将此适配器挂载到 FastAPI app 上（需调用 mount_to_app()）。
    """

    platform_name = "webhook"

    def __init__(self, config: dict) -> None:
        super().__init__(config)
        self._endpoints: dict[str, dict] = config.get("endpoints", {})
        self._callback_url: str = config.get("callback_url", "")
        self._timeout: int = config.get("timeout", 10)
        self._custom_handlers: dict[str, WebhookHandler] = {}

    async def start(self) -> None:
        self._running = True
        logger.info(f"[Webhook] 已就绪，注册路径: {list(self._endpoints.keys())}")

    async def stop(self) -> None:
        self._running = False
        logger.info("[Webhook] 已停止")

    async def send(self, msg: OutgoingMessage) -> bool:
        """向 callback_url 推送出站消息（HTTP POST）。"""
        url = msg.extra.get("callback_url") or self._callback_url
        if not url:
            logger.warning("[Webhook] 未配置 callback_url，无法发送")
            return False
        try:
            payload = json.dumps({
                "chat_id": msg.chat_id,
                "text": msg.text,
                "reply_to": msg.reply_to_id,
                **msg.extra,
            }).encode()
            req = urllib.request.Request(
                url, data=payload,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, urllib.request.urlopen, req)
            return True
        except Exception as e:
            logger.error(f"[Webhook] 出站推送失败: {e}")
            return False

    def register_handler(self, path: str, handler: WebhookHandler) -> None:
        """为特定路径注册自定义处理函数（覆盖默认分发）。"""
        self._custom_handlers[path] = handler
        logger.info(f"[Webhook] 注册自定义处理器: {path}")

    def mount_to_app(self, app) -> None:
        """将 Webhook 端点挂载到现有 FastAPI app。"""
        if not _FASTAPI_AVAILABLE:
            logger.warning("[Webhook] FastAPI 未安装，无法挂载")
            return

        for path, endpoint_cfg in self._endpoints.items():
            secret = endpoint_cfg.get("secret", self._config.get("secret", ""))
            platform = endpoint_cfg.get("platform", "webhook")

            # 闭包捕获变量
            def make_handler(p=path, s=secret, pl=platform):
                async def webhook_handler(request: Request):
                    body = await request.body()
                    # HMAC 签名验证
                    if s:
                        sig_header = request.headers.get(
                            "X-Hub-Signature-256",
                            request.headers.get("X-Signature", ""),
                        )
                        if not _verify_hmac(body, s, sig_header):
                            raise HTTPException(status_code=403, detail="签名验证失败")

                    try:
                        payload = json.loads(body)
                    except Exception:
                        payload = {"raw": body.decode(errors="replace")}

                    # 优先用自定义处理器
                    if p in self._custom_handlers:
                        result = await self._custom_handlers[p](payload, pl)
                        return {"status": "ok", "result": result}

                    # 标准入站消息分发
                    text = (
                        payload.get("text") or
                        payload.get("message") or
                        payload.get("content") or
                        json.dumps(payload, ensure_ascii=False)[:500]
                    )
                    incoming = IncomingMessage(
                        platform=pl,
                        chat_id=payload.get("chat_id", p),
                        user_id=payload.get("user_id", "webhook"),
                        text=text,
                        raw=payload,
                    )
                    reply = await self._dispatch(incoming)
                    return {"status": "ok", "reply": reply}

                return webhook_handler

            app.add_api_route(path, make_handler(), methods=["POST"])
            logger.info(f"[Webhook] 挂载端点: POST {path}")


def _verify_hmac(body: bytes, secret: str, signature: str) -> bool:
    """验证 HMAC-SHA256 签名。"""
    if not signature:
        return False
    expected = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)

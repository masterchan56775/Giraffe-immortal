"""
integration/web_server.py — FastAPI Web 服务

提供 REST、SSE 和 WebSocket 端点：
- POST /api/chat       — 接收消息，返回 SSE 流（支持 multipart 文件上传）
- GET  /api/events     — SSE 订阅端点
- WS   /ws/chat        — WebSocket 双工端点
- GET  /api/health     — 系统健康检查
"""
from __future__ import annotations

import asyncio
import base64
import logging
from typing import Optional

logger = logging.getLogger(__name__)

_FASTAPI_AVAILABLE = False
try:
    from fastapi import FastAPI, WebSocket, WebSocketDisconnect, UploadFile, File, Form
    from fastapi.responses import StreamingResponse, JSONResponse
    from fastapi.middleware.cors import CORSMiddleware
    _FASTAPI_AVAILABLE = True
except ImportError:
    pass


def create_app():
    """
    创建并返回 FastAPI 应用实例。
    所有路由在此注册。
    """
    if not _FASTAPI_AVAILABLE:
        raise ImportError(
            "FastAPI 未安装。请运行: pip install fastapi uvicorn python-multipart"
        )

    from integration.event_stream import EventBus

    app = FastAPI(
        title="Giraffe API Gateway",
        description="Giraffe AI 系统的 REST/SSE/WebSocket 网关",
        version="1.0.0",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # ── 延迟获取 Giraffe 实例 ──────────────────────────────────────────────────
    def get_giraffe():
        """延迟导入，避免循环依赖。"""
        import sys
        for obj in list(sys.modules.values()):
            if hasattr(obj, "_giraffe_instance"):
                return obj._giraffe_instance
        return None

    # ── POST /api/chat — SSE 流式响应 ─────────────────────────────────────────
    @app.post("/api/chat")
    async def chat_endpoint(
        message: str = Form(...),
        images: list[UploadFile] = File(default=[]),
    ):
        """
        接收用户消息，支持图片文件上传，以 SSE 流形式返回实时响应。

        Form fields:
            message: 用户消息文本
            images: 可选的图片文件列表（multipart/form-data）
        """
        bus = EventBus.get()

        # 处理上传图片
        encoded_images: list[str] = []
        for img_file in images:
            try:
                content = await img_file.read()
                b64 = base64.b64encode(content).decode("utf-8")
                mime = img_file.content_type or "image/png"
                encoded_images.append(f"data:{mime};base64,{b64}")
            except Exception as e:
                logger.warning(f"[WebServer] 图片读取失败: {e}")

        async def event_generator():
            # 通知客户端请求已接收
            yield f"event: accepted\ndata: {{\"message\": \"{message[:50]}\"}}\n\n"

            # 在后台线程中执行 chat() (因为它是同步阻塞的)
            loop = asyncio.get_event_loop()
            giraffe = get_giraffe()

            if giraffe is None:
                yield "event: error\ndata: {\"error\": \"Giraffe 实例未就绪\"}\n\n"
                return

            try:
                response = await loop.run_in_executor(
                    None,
                    lambda: giraffe.chat(message, images=encoded_images),
                )
                payload = response.replace('"', '\\"').replace('\n', '\\n')
                yield f"event: response\ndata: {{\"text\": \"{payload}\"}}\n\n"
            except Exception as e:
                yield f"event: error\ndata: {{\"error\": \"{str(e)}\"}}\n\n"
            finally:
                yield "event: done\ndata: {}\n\n"

        return StreamingResponse(
            event_generator(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
            },
        )

    # ── GET /api/events — SSE 订阅 ────────────────────────────────────────────
    @app.get("/api/events")
    async def events_endpoint(replay: bool = False):
        """
        订阅系统内部事件流（pipeline stage、token chunk、错误等）。

        Query params:
            replay: 是否回放最近历史事件（默认 false）
        """
        bus = EventBus.get()

        return StreamingResponse(
            bus.subscribe(replay_history=replay),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
            },
        )

    # ── WS /ws/chat — WebSocket 双工 ─────────────────────────────────────────
    @app.websocket("/ws/chat")
    async def websocket_chat(websocket: WebSocket):
        """
        WebSocket 端点，支持双向通信：
        - 客户端发送 JSON: {"message": "...", "images": [...]}
        - 服务端实时返回中间状态和最终响应
        """
        await websocket.accept()
        bus = EventBus.get()
        giraffe = get_giraffe()

        if giraffe is None:
            await websocket.send_json({"type": "error", "error": "Giraffe 实例未就绪"})
            await websocket.close()
            return

        try:
            while True:
                data = await websocket.receive_json()
                message = data.get("message", "")
                images = data.get("images", [])

                if not message:
                    await websocket.send_json({"type": "error", "error": "消息不能为空"})
                    continue

                await websocket.send_json({"type": "accepted", "message": message[:50]})

                # 转发 EventBus 事件给 WebSocket（异步监听）
                async def forward_events(ws: WebSocket, bus: EventBus):
                    async for sse_text in bus.subscribe():
                        try:
                            await ws.send_text(sse_text)
                        except Exception:
                            break

                # 在后台执行 chat
                loop = asyncio.get_event_loop()

                fwd_task = asyncio.create_task(forward_events(websocket, bus))

                try:
                    response = await loop.run_in_executor(
                        None,
                        lambda: giraffe.chat(message, images=images),
                    )
                    await websocket.send_json({"type": "response", "text": response})
                except Exception as e:
                    await websocket.send_json({"type": "error", "error": str(e)})
                finally:
                    fwd_task.cancel()
                    await websocket.send_json({"type": "done"})

        except WebSocketDisconnect:
            logger.info("[WebServer] WebSocket 客户端断开")

    # ── GET /api/health ───────────────────────────────────────────────────────
    @app.get("/api/health")
    async def health_endpoint():
        """返回系统健康状态，复用 Giraffe.health()。"""
        giraffe = get_giraffe()
        if giraffe is None:
            return JSONResponse(
                content={"status": "not_ready", "error": "Giraffe 实例未就绪"},
                status_code=503,
            )
        return JSONResponse(content=giraffe.health())

    return app

"""
integration/event_stream.py — 进程内事件总线

基于 asyncio.Queue 实现的事件总线，支持：
- emit(): 同步发布事件（线程安全）
- subscribe(): 返回 SSE 格式的异步事件流生成器
- 历史缓冲区，供新订阅者获取最近事件
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import dataclass, field
from typing import AsyncGenerator

logger = logging.getLogger(__name__)


@dataclass
class Event:
    """单个事件数据结构。"""
    event_type: str
    data: dict = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)

    def to_sse(self) -> str:
        """格式化为 SSE（Server-Sent Events）文本格式。"""
        payload = json.dumps(
            {"type": self.event_type, "ts": self.timestamp, **self.data},
            ensure_ascii=False,
        )
        return f"event: {self.event_type}\ndata: {payload}\n\n"

    def to_dict(self) -> dict:
        return {"type": self.event_type, "data": self.data, "timestamp": self.timestamp}


class EventBus:
    """
    进程内事件总线（单例）。

    设计要点：
    - emit() 是同步方法，可在任意线程安全调用。
    - subscribe() 是异步生成器，供 FastAPI SSE 端点使用。
    - 每个订阅者持有独立的 asyncio.Queue，互相隔离。
    - max_history 条最近事件缓存，供新订阅者回放。
    """

    _instance: EventBus | None = None

    def __init__(self, max_history: int = 200) -> None:
        self._max_history = max_history
        self._history: list[dict] = []
        self._queues: list[asyncio.Queue] = []
        self._loop: asyncio.AbstractEventLoop | None = None

    @classmethod
    def get(cls) -> EventBus:
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    @classmethod
    def reset(cls) -> None:
        cls._instance = None

    # ─── 发布 ─────────────────────────────────────────────────────────────────
    def emit(self, event_type: str, **data) -> None:
        """
        发布一个事件（同步，线程安全）。

        Args:
            event_type: 事件类型（如 "token_chunk", "stage_start", "stage_end"）
            **data: 事件附带的数据
        """
        event = Event(event_type=event_type, data=data)
        record = {"type": event_type, "data": data, "timestamp": event.timestamp}

        # 写入历史缓冲
        self._history.append(record)
        if len(self._history) > self._max_history:
            self._history = self._history[-self._max_history:]

        # 推入所有活跃队列
        dead_queues = []
        for q in self._queues:
            try:
                # 非阻塞放入，若队列满则跳过
                q.put_nowait(event)
            except asyncio.QueueFull:
                pass
            except RuntimeError:
                dead_queues.append(q)

        # 清理已关闭的队列
        for dq in dead_queues:
            self._queues.remove(dq)

    # ─── 订阅（异步生成器） ────────────────────────────────────────────────────
    async def subscribe(
        self,
        replay_history: bool = False,
        max_queue_size: int = 100,
    ) -> AsyncGenerator[str, None]:
        """
        订阅事件流，返回 SSE 格式字符串的异步生成器。

        Args:
            replay_history: 是否在连接时回放最近的历史事件
            max_queue_size: 当前订阅者的队列最大容量

        Yields:
            SSE 格式字符串（"event: ...\ndata: ...\n\n"）
        """
        queue: asyncio.Queue[Event] = asyncio.Queue(maxsize=max_queue_size)
        self._queues.append(queue)

        try:
            # 回放历史事件
            if replay_history:
                for record in list(self._history):
                    event = Event(
                        event_type=record["type"],
                        data=record.get("data", {}),
                        timestamp=record.get("timestamp", time.time()),
                    )
                    yield event.to_sse()

            # 实时推流
            while True:
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=30.0)
                    yield event.to_sse()
                    queue.task_done()
                except asyncio.TimeoutError:
                    # 发送心跳保持连接
                    yield ": heartbeat\n\n"
        finally:
            if queue in self._queues:
                self._queues.remove(queue)

    # ─── 工具方法 ─────────────────────────────────────────────────────────────
    def recent_events(self, n: int = 50) -> list[dict]:
        """返回最近 n 条事件记录。"""
        return list(self._history[-n:])

    @property
    def subscriber_count(self) -> int:
        return len(self._queues)

    def stats(self) -> dict:
        return {
            "history_size": len(self._history),
            "subscribers": self.subscriber_count,
            "max_history": self._max_history,
        }

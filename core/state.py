"""
AppState — 应用状态管理
负责当前会话状态、运行状态的维护与查询
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any


class RunState(str, Enum):
    """系统运行状态枚举。"""
    IDLE = "idle"
    RUNNING = "running"
    PAUSED = "paused"
    ERROR = "error"
    SHUTDOWN = "shutdown"


@dataclass
class SessionInfo:
    """单次会话的元信息。"""
    session_id: str = field(default_factory=lambda: f"sess_{uuid.uuid4().hex[:8]}")
    created_at: datetime = field(default_factory=datetime.now)
    message_count: int = 0
    total_tokens: int = 0
    last_model_used: str = ""
    last_task_type: str = ""

    def increment_message(self, tokens: int = 0, model: str = "", task_type: str = "") -> None:
        self.message_count += 1
        self.total_tokens += tokens
        if model:
            self.last_model_used = model
        if task_type:
            self.last_task_type = task_type


class AppState:
    """
    应用状态管理器（单例）。
    维护当前会话、系统运行状态及全局键值状态存储。
    """

    _instance: AppState | None = None

    def __init__(self) -> None:
        self._run_state: RunState = RunState.IDLE
        self._session: SessionInfo = SessionInfo()
        self._kv: dict[str, Any] = {}
        self._start_time: datetime = datetime.now()

    # ─── 单例 ─────────────────────────────────────────────────────────────────
    @classmethod
    def get(cls) -> "AppState":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    @classmethod
    def reset(cls) -> None:
        cls._instance = None

    # ─── 初始化 / 重置 ────────────────────────────────────────────────────────
    def initialize(self) -> str:
        """初始化一个新会话，返回 session_id。"""
        self._session = SessionInfo()
        self._run_state = RunState.IDLE
        return self._session.session_id

    def new_session(self) -> str:
        """开启新会话（保留系统状态）。"""
        return self.initialize()

    # ─── 状态控制 ─────────────────────────────────────────────────────────────
    @property
    def run_state(self) -> RunState:
        return self._run_state

    def set_running(self) -> None:
        self._run_state = RunState.RUNNING

    def set_idle(self) -> None:
        self._run_state = RunState.IDLE

    def set_paused(self) -> None:
        self._run_state = RunState.PAUSED

    def set_error(self) -> None:
        self._run_state = RunState.ERROR

    def set_shutdown(self) -> None:
        self._run_state = RunState.SHUTDOWN

    # ─── 会话信息 ─────────────────────────────────────────────────────────────
    @property
    def session(self) -> SessionInfo:
        return self._session

    @property
    def session_id(self) -> str:
        return self._session.session_id

    def record_api_call(self, tokens: int = 0, model: str = "", task_type: str = "") -> None:
        """记录一次API调用到当前会话统计。"""
        self._session.increment_message(tokens, model, task_type)

    # ─── 键值存储 ─────────────────────────────────────────────────────────────
    def set(self, key: str, value: Any) -> None:
        self._kv[key] = value

    def get_kv(self, key: str, default: Any = None) -> Any:
        return self._kv.get(key, default)

    def delete(self, key: str) -> None:
        self._kv.pop(key, None)

    # ─── 系统信息 ─────────────────────────────────────────────────────────────
    @property
    def uptime_seconds(self) -> float:
        return (datetime.now() - self._start_time).total_seconds()

    def summary(self) -> dict:
        return {
            "session_id": self.session_id,
            "run_state": self._run_state.value,
            "message_count": self._session.message_count,
            "total_tokens": self._session.total_tokens,
            "last_model": self._session.last_model_used,
            "uptime_seconds": round(self.uptime_seconds, 1),
        }

    def __repr__(self) -> str:
        return f"AppState(session={self.session_id}, state={self._run_state.value})"

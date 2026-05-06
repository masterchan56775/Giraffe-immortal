"""
Diary — 日记系统
记录每次会话的摘要，形成时间线式的对话日志
"""
from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class DiaryEntry:
    """日记条目。"""
    date: str = field(default_factory=lambda: datetime.now().strftime("%Y-%m-%d"))
    session_id: str = ""
    summary: str = ""
    key_topics: list[str] = field(default_factory=list)
    models_used: list[str] = field(default_factory=list)
    message_count: int = 0
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())

    def to_dict(self) -> dict:
        return asdict(self)


class Diary:
    """会话日记系统。记录每次会话摘要，支持按日期查询。"""

    def __init__(self, diary_path: Path | str | None = None) -> None:
        self._path = Path(diary_path) if diary_path else None
        self._entries: list[DiaryEntry] = []
        self._load()

    def write(self, session_id: str, summary: str, key_topics: list[str] = None,
              models_used: list[str] = None, message_count: int = 0) -> DiaryEntry:
        """写入一条日记。"""
        entry = DiaryEntry(
            session_id=session_id,
            summary=summary,
            key_topics=key_topics or [],
            models_used=models_used or [],
            message_count=message_count,
        )
        self._entries.append(entry)
        self._save()
        logger.info(f"[Diary] 记录会话日记: {session_id}")
        return entry

    # record 是 write 的别名，供 MemorySystem 调用
    def record(self, session_id: str, summary: str, tags: list[str] = None,
               message_count: int = 0) -> DiaryEntry:
        return self.write(session_id=session_id, summary=summary,
                         key_topics=tags or [], message_count=message_count)

    def recent(self, n: int = 5) -> list[dict]:
        """返回最近N条日记（dict格式）。"""
        return [e.to_dict() for e in self._entries[-n:]]

    def get_recent(self, days: int = 7) -> list[DiaryEntry]:
        """获取最近N天的日记。"""
        from datetime import timedelta
        cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
        return [e for e in self._entries if e.date >= cutoff]

    def _save(self) -> None:
        if not self._path:
            return
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with open(self._path, "w", encoding="utf-8") as fp:
            json.dump([e.to_dict() for e in self._entries], fp, ensure_ascii=False, indent=2)

    def _load(self) -> None:
        if not self._path or not self._path.exists():
            return
        try:
            with open(self._path, encoding="utf-8") as fp:
                data = json.load(fp)
            self._entries = [DiaryEntry(**d) for d in data]
        except Exception as e:
            logger.warning(f"[Diary] 加载失败: {e}")

    def __repr__(self) -> str:
        return f"Diary(entries={len(self._entries)})"

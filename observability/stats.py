"""
Stats / 使用统计 — 
JSONL 格式，追踪每日活跃度、连续使用天数、按模型的 token 用量。
"""
from __future__ import annotations

import json
import logging
import threading
import time
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from pathlib import Path

logger = logging.getLogger("stats")

_STATS_DIR = Path.home() / ".giraffe" / "stats"
_STATS_FILE = _STATS_DIR / "usage.jsonl"
_CACHE_FILE = _STATS_DIR / "cache.json"
_lock = threading.Lock()

@dataclass
class SessionEntry:
    """单次会话记录（追加写入 JSONL）。"""
    session_id: str
    timestamp: str                  # ISO 格式
    date: str                       # YYYY-MM-DD
    duration_ms: int
    message_count: int
    tool_call_count: int
    model_tokens: dict[str, dict]   # model → {input, output, cost}

@dataclass
class DailyActivity:
    date: str
    message_count: int = 0
    session_count: int = 0
    tool_call_count: int = 0

@dataclass
class StreakInfo:
    current_streak: int = 0
    longest_streak: int = 0
    current_streak_start: str | None = None
    longest_streak_start: str | None = None
    longest_streak_end: str | None = None

@dataclass
class GiraffeStats:
    total_sessions: int = 0
    total_messages: int = 0
    total_tool_calls: int = 0
    active_days: int = 0
    streaks: StreakInfo = field(default_factory=StreakInfo)
    daily_activity: list[DailyActivity] = field(default_factory=list)
    model_usage: dict[str, dict] = field(default_factory=dict)   # model → {input, output, cost}
    first_session_date: str | None = None
    last_session_date: str | None = None
    peak_activity_day: str | None = None
    peak_activity_hour: int | None = None
    longest_session_ms: int = 0

class StatsTracker:
    """
    会话统计追踪器，对应 src stats.ts。
    线程安全，JSONL 追加写入。
    """

    def __init__(self, stats_dir: Path | None = None):
        self._dir = stats_dir or _STATS_DIR
        self._file = self._dir / "usage.jsonl"
        self._cache_file = self._dir / "cache.json"
        self._dir.mkdir(parents=True, exist_ok=True)
        # 当前会话统计
        self._session_id: str = ""
        self._session_start: float = 0
        self._message_count: int = 0
        self._tool_call_count: int = 0
        self._model_tokens: dict[str, dict] = defaultdict(
            lambda: {"input": 0, "output": 0, "cost": 0.0}
        )

    def start_session(self, session_id: str) -> None:
        self._session_id = session_id
        self._session_start = time.time()
        self._message_count = 0
        self._tool_call_count = 0
        self._model_tokens = defaultdict(lambda: {"input": 0, "output": 0, "cost": 0.0})
        logger.debug(f"[Stats] 开始会话: {session_id}")

    def record_message(self, model: str, input_tokens: int = 0,
                       output_tokens: int = 0, cost: float = 0.0) -> None:
        self._message_count += 1
        m = self._model_tokens[model]
        m["input"] += input_tokens
        m["output"] += output_tokens
        m["cost"] += cost

    def record_tool_call(self, tool_name: str = "") -> None:
        self._tool_call_count += 1

    def flush_session(self) -> None:
        """会话结束时写入 JSONL。"""
        if not self._session_id:
            return
        now = datetime.now()
        entry = SessionEntry(
            session_id=self._session_id,
            timestamp=now.isoformat(),
            date=now.strftime("%Y-%m-%d"),
            duration_ms=int((time.time() - self._session_start) * 1000),
            message_count=self._message_count,
            tool_call_count=self._tool_call_count,
            model_tokens=dict(self._model_tokens),
        )
        with _lock:
            try:
                with open(self._file, "a", encoding="utf-8") as f:
                    f.write(json.dumps(asdict(entry)) + "\n")
                logger.debug(f"[Stats] 写入会话: {self._session_id}")
            except Exception as e:
                logger.warning(f"[Stats] 写入失败: {e}")

    def compute_stats(self, days: int = 90) -> GiraffeStats:
        """从 JSONL 计算聚合统计。"""
        if not self._file.exists():
            return GiraffeStats()

        entries: list[SessionEntry] = []
        with _lock:
            try:
                with open(self._file, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if line:
                            try:
                                d = json.loads(line)
                                entries.append(SessionEntry(**d))
                            except Exception:
                                pass
            except Exception as e:
                logger.warning(f"[Stats] 读取失败: {e}")
                return GiraffeStats()

        if not entries:
            return GiraffeStats()

        # 按日聚合
        daily: dict[str, DailyActivity] = {}
        hourly: dict[int, int] = defaultdict(int)
        model_usage: dict[str, dict] = defaultdict(lambda: {"input": 0, "output": 0, "cost": 0.0})
        longest_ms = 0

        for e in entries:
            d = daily.setdefault(e.date, DailyActivity(date=e.date))
            d.message_count += e.message_count
            d.session_count += 1
            d.tool_call_count += e.tool_call_count
            # 时段统计
            try:
                hour = datetime.fromisoformat(e.timestamp).hour
                hourly[hour] += e.message_count
            except Exception:
                pass
            # 模型用量
            for model, usage in e.model_tokens.items():
                m = model_usage[model]
                m["input"] += usage.get("input", 0)
                m["output"] += usage.get("output", 0)
                m["cost"] += usage.get("cost", 0.0)
            if e.duration_ms > longest_ms:
                longest_ms = e.duration_ms

        sorted_days = sorted(daily.keys())
        daily_list = [daily[d] for d in sorted_days]
        active_days = len([d for d in daily_list if d.message_count > 0])

        # 连续天数
        streaks = self._calc_streaks(sorted_days)

        # 峰值
        peak_day = max(daily, key=lambda d: daily[d].message_count, default=None)
        peak_hour = max(hourly, key=hourly.get, default=None) if hourly else None

        return GiraffeStats(
            total_sessions=len(entries),
            total_messages=sum(e.message_count for e in entries),
            total_tool_calls=sum(e.tool_call_count for e in entries),
            active_days=active_days,
            streaks=streaks,
            daily_activity=daily_list[-days:],
            model_usage=dict(model_usage),
            first_session_date=sorted_days[0] if sorted_days else None,
            last_session_date=sorted_days[-1] if sorted_days else None,
            peak_activity_day=peak_day,
            peak_activity_hour=peak_hour,
            longest_session_ms=longest_ms,
        )

    def _calc_streaks(self, sorted_dates: list[str]) -> StreakInfo:
        """计算当前/历史最长连续天数。"""
        if not sorted_dates:
            return StreakInfo()

        info = StreakInfo()
        current = 1
        current_start = sorted_dates[0]
        longest = 1
        longest_start = sorted_dates[0]
        longest_end = sorted_dates[0]

        for i in range(1, len(sorted_dates)):
            prev = datetime.strptime(sorted_dates[i - 1], "%Y-%m-%d")
            curr = datetime.strptime(sorted_dates[i], "%Y-%m-%d")
            if (curr - prev).days == 1:
                current += 1
                if current > longest:
                    longest = current
                    longest_start = current_start
                    longest_end = sorted_dates[i]
            else:
                current = 1
                current_start = sorted_dates[i]

        # 当前是否仍在连续（今天或昨天有活动）
        today = datetime.now().strftime("%Y-%m-%d")
        yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
        if sorted_dates[-1] in (today, yesterday):
            info.current_streak = current
            info.current_streak_start = current_start

        info.longest_streak = longest
        info.longest_streak_start = longest_start
        info.longest_streak_end = longest_end
        return info

# ── 全局单例 ─────────────────────────────────────────────────────────────────

_tracker: StatsTracker | None = None

def get_tracker() -> StatsTracker:
    global _tracker
    if _tracker is None:
        _tracker = StatsTracker()
    return _tracker

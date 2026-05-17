"""
ResponseCache — 响应缓存
缓存结果，重复查询直接返回不重复调用API
"""
from __future__ import annotations

import hashlib
import json
import logging
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

DEFAULT_TTL = 3600   # 默认缓存TTL（秒）
DEFAULT_MAX_SIZE = 500


class CachedEntry:
    __slots__ = ("value", "created_at", "ttl", "hit_count")

    def __init__(self, value: Any, ttl: float = DEFAULT_TTL) -> None:
        self.value = value
        self.created_at = time.time()
        self.ttl = ttl
        self.hit_count = 0

    def is_expired(self) -> bool:
        return (time.time() - self.created_at) > self.ttl

    def hit(self) -> Any:
        self.hit_count += 1
        return self.value


class ResponseCache:
    """
    响应缓存（LRU + TTL）。
    将查询+模型作为key，响应内容作为value缓存。
    支持内存缓存和JSON文件持久化。
    """

    def __init__(
        self,
        ttl: float = DEFAULT_TTL,
        max_size: int = DEFAULT_MAX_SIZE,
        persist_path: Path | str | None = None,
    ) -> None:
        self._ttl = ttl
        self._max_size = max_size
        self._cache: dict[str, CachedEntry] = {}
        self._persist_path = Path(persist_path) if persist_path else None
        self._hit_count = 0
        self._miss_count = 0

        if self._persist_path and self._persist_path.exists():
            self._load_from_disk()

    # ─── 核心接口 ─────────────────────────────────────────────────────────────
    def get(self, query: str, model: str = "") -> Any | None:
        """
        查询缓存。命中返回缓存值，未命中返回None。
        """
        key = self._make_key(query, model)
        entry = self._cache.get(key)
        if entry is None:
            self._miss_count += 1
            return None
        if entry.is_expired():
            del self._cache[key]
            self._miss_count += 1
            return None
        self._hit_count += 1
        return entry.hit()

    def set(self, query: str, response: Any, model: str = "") -> None:
        """写入缓存。超过max_size时淘汰最旧条目。"""
        if len(self._cache) >= self._max_size:
            self._evict_oldest()
        key = self._make_key(query, model)
        self._cache[key] = CachedEntry(response, self._ttl)

    def check_and_store(self, query: str, response: Any, model: str = "") -> bool:
        """
        检查是否缓存命中，未命中则存储。
        返回 True 表示已缓存（首次存储），False 表示已存在。
        """
        key = self._make_key(query, model)
        if key not in self._cache:
            self.set(query, response, model)
            return True
        return False

    def invalidate(self, query: str, model: str = "") -> bool:
        """使指定缓存失效。"""
        key = self._make_key(query, model)
        return bool(self._cache.pop(key, None))

    def clear(self) -> None:
        """清空所有缓存。"""
        self._cache.clear()

    # ─── 内部工具 ─────────────────────────────────────────────────────────────
    def _make_key(self, query: str, model: str) -> str:
        raw = f"{model}::{query}"
        return hashlib.md5(raw.encode("utf-8")).hexdigest()

    def _evict_oldest(self) -> None:
        """淘汰最旧的缓存条目。"""
        if not self._cache:
            return
        oldest_key = min(self._cache, key=lambda k: self._cache[k].created_at)
        del self._cache[oldest_key]

    def _cleanup_expired(self) -> int:
        """清理所有过期条目，返回清理数量。"""
        expired = [k for k, v in self._cache.items() if v.is_expired()]
        for k in expired:
            del self._cache[k]
        return len(expired)

    # ─── 持久化 ───────────────────────────────────────────────────────────────
    def save_to_disk(self) -> None:
        if not self._persist_path:
            return
        self._persist_path.parent.mkdir(parents=True, exist_ok=True)
        serializable = {}
        import json as _json
        for key, entry in self._cache.items():
            if not entry.is_expired():
                try:
                    _json.dumps(entry.value)  # 预检：确认值可 JSON 序列化
                    serializable[key] = {
                        "value": entry.value,
                        "created_at": entry.created_at,
                        "ttl": entry.ttl,
                    }
                except (TypeError, ValueError) as e:
                    logger.debug(f"[ResponseCache] 条目不可序列化，跳过: {e}")
        with open(self._persist_path, "w", encoding="utf-8") as f:
            json.dump(serializable, f, ensure_ascii=False, indent=2)

    def _load_from_disk(self) -> None:
        try:
            with open(self._persist_path, encoding="utf-8") as f:
                data = json.load(f)
            for key, item in data.items():
                entry = CachedEntry(item["value"], item.get("ttl", self._ttl))
                entry.created_at = item["created_at"]
                if not entry.is_expired():
                    self._cache[key] = entry
            logger.info(f"[ResponseCache] 从磁盘加载 {len(self._cache)} 条缓存")
        except Exception as e:
            logger.warning(f"[ResponseCache] 加载磁盘缓存失败: {e}")

    # ─── 统计 ─────────────────────────────────────────────────────────────────
    @property
    def hit_rate(self) -> float:
        total = self._hit_count + self._miss_count
        return round(self._hit_count / total, 3) if total > 0 else 0.0

    def stats(self) -> dict:
        return {
            "size": len(self._cache),
            "max_size": self._max_size,
            "hit_count": self._hit_count,
            "miss_count": self._miss_count,
            "hit_rate": self.hit_rate,
            "ttl_seconds": self._ttl,
        }

    def __repr__(self) -> str:
        return f"ResponseCache(size={len(self._cache)}, hit_rate={self.hit_rate})"

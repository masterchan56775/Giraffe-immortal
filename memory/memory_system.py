"""
MemorySystem — 主记忆系统
四层记忆架构：短期（内存）/ 事实（facts.json）/ 长期（SQLite）/ 结构化
"""
from __future__ import annotations

import json
import logging
import sqlite3
from pathlib import Path

from .auto_extract import AutoExtract
from .diary import Diary
from .memory_refiner import MemoryRefiner
from .structured_memory import MemoryFact, StructuredMemory
from .vector_store import VectorStore

logger = logging.getLogger(__name__)


class MemorySystem:
    """
    四层记忆系统（单例）。

    层级：
    1. 短期记忆  — 内存中的当前会话消息列表（含 user + assistant 两种角色）
    2. 事实记忆  — facts.json 持久化用户偏好/环境信息
    3. 长期记忆  — SQLite 跨会话知识库（全文搜索）
    4. 结构化记忆— StructuredMemory (UserContext/HistoryContext/Facts)

    循环：
    对话输入 → process_message() → 提取事实 → add_fact() → 写入facts.json
    下次会话 → load() → 注入system prompt

    附加：
    - MemoryRefiner 定期对 facts 做去重/合并
    - Diary 记录每次对话摘要
    """

    _instance: "MemorySystem | None" = None

    def __init__(self, data_dir: Path | str | None = None, config: dict | None = None) -> None:
        self._data_dir = Path(data_dir) if data_dir else Path(__file__).parent.parent / "data"
        self._cfg = config or {}
        self._data_dir.mkdir(parents=True, exist_ok=True)
        (self._data_dir / "cache").mkdir(exist_ok=True)

        # 短期记忆（当前会话：role=user|assistant|system 均保存）
        self._short_term: list[dict] = []

        # 事实记忆
        self._facts_path = self._data_dir / "facts.json"
        self._facts: list[dict] = []
        self._load_facts()

        # 长期记忆（SQLite）
        self._db_path = self._data_dir / "memory.db"
        self._init_db()

        # 结构化记忆
        self._structured = StructuredMemory(
            persist_path=self._data_dir / "structured_memory.json"
        )

        # 自动事实提取器
        self._extractor = AutoExtract(
            confidence_threshold=self._cfg.get("confidence_threshold", 0.7)
        )

        # 记忆精炼器（去重+合并）
        self._refiner = MemoryRefiner()

        # 日记系统
        self._diary = Diary(diary_path=self._data_dir / "diary.json")

        # 向量存储（语义检索）
        vec_cfg = self._cfg.get("vector_store", {})
        if vec_cfg.get("enabled", False):
            self._vector_store = VectorStore(
                persist_dir=self._data_dir / "vector_db",
                embedding_model=vec_cfg.get("embedding_model", "all-MiniLM-L6-v2"),
            )
        else:
            self._vector_store = VectorStore()  # 未启用，自动降级

        self._max_facts = self._cfg.get("max_facts", 1000)
        self._refine_interval = 20   # 每20条新消息触发一次精炼
        self._msg_since_refine = 0

    @classmethod
    def get(cls, data_dir: Path | str | None = None, config: dict | None = None) -> "MemorySystem":
        if cls._instance is None:
            cls._instance = cls(data_dir, config)
        return cls._instance

    @classmethod
    def reset(cls) -> None:
        cls._instance = None

    # ─── 主处理接口 ────────────────────────────────────────────────────────────
    def process_message(self, role: str, content: str) -> list[MemoryFact]:
        """
        处理一条消息：
        - 追加到短期记忆（user/assistant/system 均收录）
        - 对 user 消息提取事实（AutoExtract）
        - 周期性触发 MemoryRefiner 去重
        返回本次提取到的事实列表。
        """
        msg = {"role": role, "content": content}
        self._short_term.append(msg)
        self._msg_since_refine += 1

        # 只对用户输入提取事实
        extracted = self._extractor.extract(content, role)
        added_facts = []
        for ef in extracted:
            if len(self._facts) < self._max_facts:
                fact = self.add_fact(ef.content, ef.category, ef.confidence)
                added_facts.append(fact)
                # 同步到结构化记忆
                self._structured.add_fact(ef.content, ef.category, ef.confidence)

        # 周期性精炼
        if self._msg_since_refine >= self._refine_interval:
            self._run_refine()
            self._msg_since_refine = 0

        return added_facts

    def _run_refine(self) -> None:
        """触发 MemoryRefiner 去重+合并 facts。"""
        try:
            raw = [f.get("content", "") for f in self._facts if isinstance(f, dict)]
            refined = self._refiner.refine(raw)
            if len(refined) < len(raw):
                existing_map = {
                    f.get("content", ""): f for f in self._facts if isinstance(f, dict)
                }
                self._facts = [
                    existing_map[c] for c in refined if c in existing_map
                ]
                self._save_facts()
                logger.info(f"[Memory] 精炼完成: {len(raw)} → {len(self._facts)} 条事实")
        except Exception as e:
            logger.warning(f"[Memory] 精炼失败: {e}")

    # ─── 事实记忆 ─────────────────────────────────────────────────────────────
    def add_fact(self, content: str, category: str = "general",
                 confidence: float = 0.8) -> MemoryFact:
        """写入事实到facts.json，并同步写入向量库。"""
        fact = MemoryFact(content=content, category=category, confidence=confidence)
        self._facts.append(fact.to_dict())
        self._save_facts()

        # 同步写入向量库
        import uuid
        doc_id = f"fact_{uuid.uuid4().hex[:8]}"
        self._vector_store.add(
            doc_id=doc_id,
            text=content,
            metadata={"category": category, "confidence": confidence, "source": "fact"},
        )

        logger.debug(f"[Memory] 新增事实: {content[:50]}")
        return fact

    def get_facts(self, category: str | None = None) -> list[dict]:
        if category:
            return [f for f in self._facts if f.get("category") == category]
        return list(self._facts)

    def _load_facts(self) -> None:
        if self._facts_path.exists():
            try:
                with open(self._facts_path, encoding="utf-8") as fp:
                    self._facts = json.load(fp)
                logger.info(f"[Memory] 加载 {len(self._facts)} 条事实记忆")
            except Exception as e:
                logger.warning(f"[Memory] 加载facts失败: {e}")

    def _save_facts(self) -> None:
        with open(self._facts_path, "w", encoding="utf-8") as fp:
            json.dump(self._facts, fp, ensure_ascii=False, indent=2)

    # ─── 短期记忆 ─────────────────────────────────────────────────────────────
    @property
    def short_term(self) -> list[dict]:
        return list(self._short_term)

    def clear_short_term(self) -> None:
        self._short_term.clear()

    def get_context_messages(self, max_messages: int = 20) -> list[dict]:
        """
        获取用于API调用的上下文消息列表（最近N条）。
        包含 user 和 assistant 双角色，保持对话完整性。
        system 消息不包含在此处（由 build_system_prompt 负责注入）。
        """
        non_system = [m for m in self._short_term if m.get("role") != "system"]
        return non_system[-max_messages:]

    # ─── 长期记忆（SQLite）────────────────────────────────────────────────────
    def _init_db(self) -> None:
        with sqlite3.connect(self._db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS long_term (
                    id TEXT PRIMARY KEY,
                    content TEXT NOT NULL,
                    category TEXT,
                    confidence REAL,
                    session_id TEXT,
                    created_at TEXT
                )
            """)
            conn.commit()

    def save_to_long_term(
        self, content: str, category: str = "knowledge",
        confidence: float = 0.8, session_id: str = ""
    ) -> str:
        """保存知识到长期记忆（SQLite），并同步写入向量库。"""
        import uuid
        from datetime import datetime
        fact_id = f"lt_{uuid.uuid4().hex[:8]}"
        with sqlite3.connect(self._db_path) as conn:
            conn.execute(
                "INSERT OR IGNORE INTO long_term VALUES (?, ?, ?, ?, ?, ?)",
                (fact_id, content, category, confidence, session_id,
                 datetime.now().isoformat())
            )
            conn.commit()

        # 同步写入向量库
        self._vector_store.add(
            doc_id=fact_id,
            text=content,
            metadata={"category": category, "confidence": confidence, "source": "long_term"},
        )

        return fact_id

    def search_long_term(self, keyword: str, limit: int = 10) -> list[dict]:
        """全文搜索长期记忆。"""
        with sqlite3.connect(self._db_path) as conn:
            cursor = conn.execute(
                "SELECT id, content, category, confidence, created_at "
                "FROM long_term WHERE content LIKE ? ORDER BY confidence DESC LIMIT ?",
                (f"%{keyword}%", limit)
            )
            return [
                {"id": r[0], "content": r[1], "category": r[2],
                 "confidence": r[3], "created_at": r[4]}
                for r in cursor.fetchall()
            ]

    def delete_from_long_term(self, fact_id: str) -> bool:
        """从长期记忆中删除一条记录。"""
        with sqlite3.connect(self._db_path) as conn:
            cursor = conn.execute("DELETE FROM long_term WHERE id = ?", (fact_id,))
            conn.commit()
            return cursor.rowcount > 0

    # ─── 日记 ─────────────────────────────────────────────────────────────────
    def record_session(self, session_id: str, summary: str, tags: list[str] | None = None) -> None:
        """记录会话摘要到日记。"""
        self._diary.record(session_id=session_id, summary=summary, tags=tags or [])

    def get_recent_sessions(self, n: int = 5) -> list[dict]:
        """获取最近N次会话日记。"""
        return self._diary.recent(n)

    # ─── 语义检索 ───────────────────────────────────────────────────────────
    def semantic_search(self, query: str, top_k: int = 5) -> list[dict]:
        """
        混合检索：向量相似度 + 关键词匹配，合并去重后返回。

        Args:
            query: 搜索查询语句
            top_k: 返回结果数量上限

        Returns:
            [{"id": ..., "text": ..., "score": ..., "source": ...}, ...]
        """
        results = []
        seen_texts = set()

        # 1. 向量检索
        vector_results = self._vector_store.search(query, top_k=top_k)
        for vr in vector_results:
            text = vr.get("text", "")
            if text and text not in seen_texts:
                seen_texts.add(text)
                results.append({
                    "id": vr.get("id", ""),
                    "text": text,
                    "score": round(1.0 - vr.get("distance", 1.0), 4),
                    "source": "vector",
                })

        # 2. 关键词检索（补充）
        keyword_results = self.search_long_term(query, limit=top_k)
        for kr in keyword_results:
            text = kr.get("content", "")
            if text and text not in seen_texts:
                seen_texts.add(text)
                results.append({
                    "id": kr.get("id", ""),
                    "text": text,
                    "score": kr.get("confidence", 0.5),
                    "source": "keyword",
                })

        # 按分数降序
        results.sort(key=lambda x: x["score"], reverse=True)
        return results[:top_k]

    # ─── 系统提示词 ───────────────────────────────────────────────────────────
    def build_system_prompt(self) -> str:
        """生成包含记忆内容的系统提示词。"""
        return self._structured.generate_system_prompt(
            min_confidence=self._cfg.get("confidence_threshold", 0.7)
        )

    def memory_summary(self) -> str:
        """生成人类可读的记忆摘要（用于 /memory 命令）。"""
        lines = [
            f"📦 短期记忆: {len(self._short_term)} 条消息",
            f"💡 事实记忆: {len(self._facts)} 条 (facts.json)",
        ]
        with sqlite3.connect(self._db_path) as conn:
            lt_count = conn.execute("SELECT COUNT(*) FROM long_term").fetchone()[0]
        lines.append(f"🗄️ 长期记忆: {lt_count} 条 (SQLite)")
        struct_stats = self._structured.stats()
        lines.append(f"🔧 结构化记忆: {struct_stats.get('total_facts', 0)} 条")
        return "\n".join(lines)

    # ─── 结构化记忆代理 ───────────────────────────────────────────────────────
    @property
    def structured(self) -> StructuredMemory:
        return self._structured

    # ─── 统计 ─────────────────────────────────────────────────────────────────
    def stats(self) -> dict:
        with sqlite3.connect(self._db_path) as conn:
            lt_count = conn.execute("SELECT COUNT(*) FROM long_term").fetchone()[0]
        return {
            "short_term_messages": len(self._short_term),
            "fact_memory_count": len(self._facts),
            "long_term_count": lt_count,
            "structured_facts": self._structured.stats()["total_facts"],
            "vector_store": self._vector_store.stats(),
        }

    def __repr__(self) -> str:
        return f"MemorySystem(facts={len(self._facts)}, short_term={len(self._short_term)})"

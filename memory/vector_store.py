"""
memory/vector_store.py — LLM 驱动的语义记忆检索

用 LLM side query 替代 ChromaDB + sentence-transformers 向量嵌入。
设计灵感来自 src/memdir/findRelevantMemories.ts：
  1. 记忆以 JSON 条目存储（text + metadata），持久化到本地文件
  2. 检索时把所有记忆摘要列表发给小模型，由 LLM 判断哪些与查询相关
  3. 支持任意已配置的模型（Claude / Gemini / Grok / OpenAI / 等）

优点：
  - 零额外依赖（不需要 PyTorch / ChromaDB / sentence-transformers）
  - 与主路由矩阵共用模型，自动跟随用户配置的提供商
  - 语义理解质量与主模型相同
"""
from __future__ import annotations

import json
import logging
import re
import uuid
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# 每次 search() 发送给 LLM 的最大记忆条目数（保护 context window）
_MAX_ENTRIES_FOR_LLM = 200
# LLM 返回的最大结果数
_MAX_LLM_RESULTS = 10
# 摘要截断长度（字符），避免超长条目塞爆 prompt
_PREVIEW_LEN = 120
# 本地存储文件名
_STORE_FILENAME = "llm_memory_store.json"

_SELECT_SYSTEM = """\
You are a memory relevance selector for an AI assistant.
Given a user query and a numbered list of stored memory entries,
return the indices of entries that are clearly relevant to the query.

Rules:
- Only include entries that will genuinely help answer the query.
- Be selective — if unsure, leave it out.
- Return ONLY a JSON array of integers, e.g.: [0, 3, 7]
- If nothing is relevant, return: []
"""


class VectorStore:
    """
    LLM 驱动的语义记忆存储，完全兼容原 ChromaDB 版本的公共 API。

    接口：
      add(doc_id, text, metadata)  → 写入一条记忆
      search(query, top_k)         → LLM 语义检索，返回最相关条目
      delete(doc_id)               → 删除指定记忆
      count()                      → 返回总条目数
      stats()                      → 返回统计信息
    """

    def __init__(
        self,
        persist_dir: Path | str | None = None,
        collection_name: str = "giraffe_memory",
        embedding_model: str = "",   # 保留参数，LLM 模式下忽略
        llm_model: str | None = None,  # 指定用于检索的 LLM；None=从路由器获取
    ) -> None:
        self._persist_dir = Path(persist_dir) if persist_dir else None
        self._collection_name = collection_name
        self._llm_model = llm_model  # None 表示运行时动态获取
        self._enabled = True

        # 内存中的记忆条目：{doc_id: {"text": str, "metadata": dict}}
        self._store: dict[str, dict[str, Any]] = {}

        # 持久化路径
        self._store_path: Path | None = None
        if self._persist_dir:
            self._persist_dir.mkdir(parents=True, exist_ok=True)
            self._store_path = self._persist_dir / _STORE_FILENAME
            self._load()

        logger.info(
            f"[VectorStore] LLM 模式已初始化"
            f"（entries={len(self._store)}, "
            f"persist={'是' if self._store_path else '否'}）"
        )

    @property
    def enabled(self) -> bool:
        return self._enabled

    # ─── 写入 ─────────────────────────────────────────────────────────────────
    def add(self, doc_id: str, text: str, metadata: dict | None = None) -> bool:
        """写入一条记忆条目。若 doc_id 已存在则覆盖（upsert）。"""
        if not text or not text.strip():
            return False
        self._store[doc_id] = {
            "text": text,
            "metadata": metadata or {},
        }
        self._save()
        return True

    # ─── 检索 ─────────────────────────────────────────────────────────────────
    def search(self, query: str, top_k: int = 5) -> list[dict]:
        """
        LLM 语义检索：发送记忆摘要清单给小模型，由模型选出最相关条目。

        Returns:
            [{\"id\": ..., \"text\": ..., \"distance\": ..., \"metadata\": ...}, ...]
            distance 字段保留兼容性（LLM 模式下固定为 0.1，表示高相关）
        """
        if not self._store or not query.strip():
            return []

        entries = list(self._store.items())  # [(doc_id, {text, metadata})]

        # 超出上限时取最新的（靠后写入的 dict key，Python 3.7+ 保持插入顺序）
        if len(entries) > _MAX_ENTRIES_FOR_LLM:
            entries = entries[-_MAX_ENTRIES_FOR_LLM:]

        # 构建编号清单
        manifest_lines = []
        for i, (doc_id, entry) in enumerate(entries):
            preview = entry["text"][:_PREVIEW_LEN].replace("\n", " ")
            meta = entry.get("metadata", {})
            cat = meta.get("category", "")
            tag = f"[{cat}] " if cat else ""
            manifest_lines.append(f"{i}. {tag}{preview}")

        manifest = "\n".join(manifest_lines)
        user_msg = (
            f"Query: {query}\n\n"
            f"Memory entries ({len(entries)} total):\n{manifest}"
        )

        # 调用 LLM 获取相关索引
        selected_indices = self._llm_select(user_msg)

        # 组装结果
        results = []
        for idx in selected_indices:
            if 0 <= idx < len(entries):
                doc_id, entry = entries[idx]
                results.append({
                    "id": doc_id,
                    "text": entry["text"],
                    "distance": 0.1,   # 固定低 distance（高相关）
                    "metadata": entry.get("metadata", {}),
                })
                if len(results) >= top_k:
                    break

        logger.debug(
            f"[VectorStore] 检索 '{query[:40]}...' "
            f"→ {len(selected_indices)} 候选，返回 {len(results)} 条"
        )
        return results

    # ─── 删除 ─────────────────────────────────────────────────────────────────
    def delete(self, doc_id: str) -> bool:
        if doc_id in self._store:
            del self._store[doc_id]
            self._save()
            return True
        return False

    # ─── 统计 ─────────────────────────────────────────────────────────────────
    def count(self) -> int:
        return len(self._store)

    def stats(self) -> dict:
        return {
            "enabled": self._enabled,
            "mode": "llm",
            "count": self.count(),
            "embedding_model": None,  # LLM 模式无嵌入模型
            "llm_model": self._llm_model or "(auto from router)",
        }

    # ─── LLM 调用 ─────────────────────────────────────────────────────────────
    def _llm_select(self, user_message: str) -> list[int]:
        """
        调用 LLM 选出相关记忆索引。
        支持所有已配置的提供商（Claude / Gemini / Grok / OpenAI / 等）。
        失败时静默返回空列表，不影响主流程。
        """
        model = self._resolve_model()
        try:
            from executor.pipeline import ExecutorPipeline, ExecutionContext
            pipeline = ExecutorPipeline.get_default()
            if pipeline is None:
                return self._keyword_fallback(user_message)

            ctx = ExecutionContext(
                message=user_message,
                model=model,
                system_prompt=_SELECT_SYSTEM,
                messages=[],
                max_tokens=256,
                use_cache=False,
            )
            result = pipeline.execute(ctx)
            raw = (result.response or "").strip()
            return self._parse_indices(raw)

        except Exception as e:
            logger.debug(f"[VectorStore] LLM 检索失败，降级关键词: {e}")
            return self._keyword_fallback(user_message)

    def _resolve_model(self) -> str:
        """获取用于检索的模型名：优先使用配置的 llm_model，否则从路由器取最快小模型。"""
        if self._llm_model:
            return self._llm_model
        try:
            from router.model_registry import ModelRegistry
            chain = ModelRegistry().get_model_chain("chat")
            # 用 emergency（最快/最便宜）做 side query
            return chain.get("emergency") or chain.get("fallback") or chain.get("primary", "")
        except Exception:
            return ""

    @staticmethod
    def _parse_indices(raw: str) -> list[int]:
        """从 LLM 输出中提取整数列表，容忍格式噪音。"""
        # 尝试解析 JSON 数组
        try:
            match = re.search(r"\[[\d,\s]*\]", raw)
            if match:
                return [int(x) for x in json.loads(match.group()) if isinstance(x, int)]
        except Exception:
            pass
        # 备用：提取所有数字
        return [int(x) for x in re.findall(r"\d+", raw)]

    def _keyword_fallback(self, user_message: str) -> list[int]:
        """
        LLM 不可用时的关键词降级：对 query 分词后做简单字符串匹配。
        保证 search() 始终有结果返回。
        """
        # 从 user_message 中提取 query 部分（第一行 "Query: ..." ）
        query_line = user_message.split("\n")[0]
        query = re.sub(r"^Query:\s*", "", query_line, flags=re.I).lower()
        keywords = set(re.findall(r"\w{2,}", query))
        if not keywords:
            return list(range(min(5, len(self._store))))

        entries = list(self._store.values())
        scored: list[tuple[int, int]] = []
        for i, entry in enumerate(entries):
            text_lower = entry["text"].lower()
            score = sum(1 for kw in keywords if kw in text_lower)
            if score > 0:
                scored.append((i, score))

        scored.sort(key=lambda x: x[1], reverse=True)
        return [i for i, _ in scored[:_MAX_LLM_RESULTS]]

    # ─── 持久化 ───────────────────────────────────────────────────────────────
    def _load(self) -> None:
        if self._store_path and self._store_path.exists():
            try:
                with open(self._store_path, encoding="utf-8") as f:
                    self._store = json.load(f)
                logger.info(f"[VectorStore] 加载 {len(self._store)} 条记忆")
            except Exception as e:
                logger.warning(f"[VectorStore] 加载失败: {e}")
                self._store = {}

    def _save(self) -> None:
        if self._store_path:
            try:
                with open(self._store_path, "w", encoding="utf-8") as f:
                    json.dump(self._store, f, ensure_ascii=False)
            except Exception as e:
                logger.warning(f"[VectorStore] 保存失败: {e}")

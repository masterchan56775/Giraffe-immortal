"""
memory/vector_store.py — 向量存储管理器

基于 ChromaDB 的本地向量数据库封装，提供语义检索能力。
当 ChromaDB 或 sentence-transformers 未安装时，自动降级为禁用状态。
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# ─── 可选依赖检测 ─────────────────────────────────────────────────────────────
_CHROMA_AVAILABLE = False
_EMBEDDING_AVAILABLE = False

try:
    import chromadb
    from chromadb.config import Settings

    _CHROMA_AVAILABLE = True
except ImportError:
    chromadb = None  # type: ignore

try:
    from sentence_transformers import SentenceTransformer

    _EMBEDDING_AVAILABLE = True
except ImportError:
    SentenceTransformer = None  # type: ignore


class VectorStore:
    """
    基于 ChromaDB 的向量存储。

    功能：
    - add(): 将文本向量化后写入本地持久化集合
    - search(): 语义检索，返回与 query 最相似的 top_k 条结果
    - delete(): 删除指定文档
    - stats(): 返回集合大小等统计信息

    当依赖未安装时，所有方法安全降级为空操作。
    """

    def __init__(
        self,
        persist_dir: Path | str | None = None,
        collection_name: str = "giraffe_memory",
        embedding_model: str = "all-MiniLM-L6-v2",
    ) -> None:
        self._enabled = False
        self._client = None
        self._collection = None
        self._embedder = None
        self._persist_dir = Path(persist_dir) if persist_dir else None

        if not _CHROMA_AVAILABLE:
            logger.info("[VectorStore] chromadb 未安装，向量检索已禁用")
            return

        try:
            if self._persist_dir:
                self._persist_dir.mkdir(parents=True, exist_ok=True)
                self._client = chromadb.PersistentClient(
                    path=str(self._persist_dir),
                    settings=Settings(anonymized_telemetry=False),
                )
            else:
                self._client = chromadb.Client(
                    settings=Settings(anonymized_telemetry=False),
                )

            self._collection = self._client.get_or_create_collection(
                name=collection_name,
                metadata={"hnsw:space": "cosine"},
            )

            if _EMBEDDING_AVAILABLE:
                self._embedder = SentenceTransformer(embedding_model)
                logger.info(
                    f"[VectorStore] 已初始化 (model={embedding_model}, "
                    f"collection={collection_name}, docs={self._collection.count()})"
                )
            else:
                logger.info(
                    "[VectorStore] sentence-transformers 未安装，使用 ChromaDB 默认嵌入"
                )

            self._enabled = True
        except Exception as e:
            logger.warning(f"[VectorStore] 初始化失败: {e}")

    @property
    def enabled(self) -> bool:
        return self._enabled

    # ─── 写入 ─────────────────────────────────────────────────────────────────
    def add(self, doc_id: str, text: str, metadata: dict | None = None) -> bool:
        """
        将文本向量化后写入集合。

        Args:
            doc_id: 文档唯一标识
            text: 文本内容
            metadata: 附加元数据（如 category, confidence）

        Returns:
            是否写入成功
        """
        if not self._enabled or not self._collection:
            return False

        try:
            kwargs: dict[str, Any] = {
                "ids": [doc_id],
                "documents": [text],
            }
            if metadata:
                # ChromaDB 要求 metadata 的值只能是 str/int/float/bool
                safe_meta = {
                    k: v for k, v in metadata.items()
                    if isinstance(v, (str, int, float, bool))
                }
                kwargs["metadatas"] = [safe_meta]
            if self._embedder:
                embedding = self._embedder.encode([text]).tolist()
                kwargs["embeddings"] = embedding

            self._collection.upsert(**kwargs)
            return True
        except Exception as e:
            logger.warning(f"[VectorStore] 写入失败 ({doc_id}): {e}")
            return False

    # ─── 检索 ─────────────────────────────────────────────────────────────────
    def search(self, query: str, top_k: int = 5) -> list[dict]:
        """
        语义检索，返回与 query 最相似的 top_k 条结果。

        Returns:
            [{"id": ..., "text": ..., "distance": ..., "metadata": ...}, ...]
        """
        if not self._enabled or not self._collection:
            return []

        try:
            kwargs: dict[str, Any] = {
                "query_texts": [query],
                "n_results": min(top_k, self._collection.count() or 1),
            }
            if self._embedder:
                query_embedding = self._embedder.encode([query]).tolist()
                kwargs = {
                    "query_embeddings": query_embedding,
                    "n_results": min(top_k, self._collection.count() or 1),
                }

            results = self._collection.query(**kwargs)

            items = []
            if results and results["ids"] and results["ids"][0]:
                ids = results["ids"][0]
                docs = results["documents"][0] if results["documents"] else [""] * len(ids)
                dists = results["distances"][0] if results["distances"] else [0.0] * len(ids)
                metas = results["metadatas"][0] if results["metadatas"] else [{}] * len(ids)

                for i, doc_id in enumerate(ids):
                    items.append({
                        "id": doc_id,
                        "text": docs[i],
                        "distance": round(dists[i], 4),
                        "metadata": metas[i] if metas[i] else {},
                    })

            return items
        except Exception as e:
            logger.warning(f"[VectorStore] 检索失败: {e}")
            return []

    # ─── 删除 ─────────────────────────────────────────────────────────────────
    def delete(self, doc_id: str) -> bool:
        """删除指定文档。"""
        if not self._enabled or not self._collection:
            return False
        try:
            self._collection.delete(ids=[doc_id])
            return True
        except Exception as e:
            logger.warning(f"[VectorStore] 删除失败 ({doc_id}): {e}")
            return False

    # ─── 统计 ─────────────────────────────────────────────────────────────────
    def count(self) -> int:
        """返回集合中的文档数量。"""
        if not self._enabled or not self._collection:
            return 0
        try:
            return self._collection.count()
        except Exception:
            return 0

    def stats(self) -> dict:
        return {
            "enabled": self._enabled,
            "count": self.count(),
            "embedding_model": (
                self._embedder.get_sentence_embedding_dimension()
                if self._embedder and hasattr(self._embedder, "get_sentence_embedding_dimension")
                else None
            ),
        }

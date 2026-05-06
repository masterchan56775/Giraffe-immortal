"""
tests/test_phase2.py — 阶段二测试：向量存储 + MCP 注册表
"""
import pytest
from memory.vector_store import VectorStore
from integration.mcp_client import MCPClient
from integration.mcp_registry import MCPRegistry


# ─── VectorStore 测试 ─────────────────────────────────────────────────────────
class TestVectorStore:
    """测试 VectorStore 在 ChromaDB 未安装时的降级行为。"""

    def test_disabled_by_default(self):
        """未传入 persist_dir 且 chromadb 未安装时应禁用。"""
        store = VectorStore()
        # enabled 取决于是否安装了 chromadb
        stats = store.stats()
        assert "enabled" in stats
        assert "count" in stats

    def test_add_returns_safely(self):
        """add() 在未启用时应安全返回。"""
        store = VectorStore()
        if not store.enabled:
            result = store.add("test_id", "test text", {"key": "value"})
            assert result is False

    def test_search_returns_empty(self):
        """search() 在未启用时应返回空列表。"""
        store = VectorStore()
        if not store.enabled:
            results = store.search("query")
            assert results == []

    def test_delete_returns_safely(self):
        """delete() 在未启用时应安全返回。"""
        store = VectorStore()
        if not store.enabled:
            result = store.delete("test_id")
            assert result is False

    def test_count_returns_zero(self):
        """count() 在未启用时应返回 0。"""
        store = VectorStore()
        if not store.enabled:
            assert store.count() == 0

    def test_stats_structure(self):
        """stats() 应包含标准字段。"""
        store = VectorStore()
        stats = store.stats()
        assert "enabled" in stats
        assert "count" in stats
        assert "embedding_model" in stats


# ─── MCPClient 测试 ───────────────────────────────────────────────────────────
class TestMCPClient:
    """测试 MCP 客户端基本行为。"""

    def test_default_disconnected(self):
        client = MCPClient(server_name="test")
        assert client.connected is False

    def test_health_structure(self):
        client = MCPClient(server_name="test", command="echo", args=["hello"])
        health = client.health()
        assert health["server_name"] == "test"
        assert health["connected"] is False
        assert health["transport"] == "stdio"
        assert health["tools_count"] == 0


# ─── MCPRegistry 测试 ─────────────────────────────────────────────────────────
class TestMCPRegistry:
    """测试 MCP 注册表。"""

    def setup_method(self):
        MCPRegistry.reset()

    def test_singleton(self):
        r1 = MCPRegistry.get()
        r2 = MCPRegistry.get()
        assert r1 is r2

    def test_load_from_config(self):
        registry = MCPRegistry.get()
        config = {
            "filesystem": {"command": "npx", "args": ["mcp-server-fs"]},
            "git": {"command": "npx", "args": ["mcp-server-git"]},
        }
        registry.load_from_config(config)
        assert len(registry.server_names) == 2
        assert "filesystem" in registry.server_names
        assert "git" in registry.server_names

    def test_empty_registry(self):
        registry = MCPRegistry.get()
        assert registry.connected_count == 0
        assert registry.server_names == []

    def test_health_structure(self):
        registry = MCPRegistry.get()
        health = registry.health()
        assert "total_servers" in health
        assert "connected" in health
        assert "servers" in health

    def test_load_and_health(self):
        registry = MCPRegistry.get()
        registry.load_from_config({"test": {"command": "echo"}})
        health = registry.health()
        assert health["total_servers"] == 1
        assert "test" in health["servers"]


# ─── MemorySystem 集成测试 ────────────────────────────────────────────────────
class TestMemoryVectorIntegration:
    """测试 MemorySystem 与 VectorStore 的集成。"""

    def setup_method(self):
        from memory.memory_system import MemorySystem
        MemorySystem.reset()

    def test_stats_includes_vector_store(self):
        """stats() 应包含 vector_store 字段。"""
        import tempfile
        from pathlib import Path
        from memory.memory_system import MemorySystem

        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as td:
            ms = MemorySystem(data_dir=Path(td))
            stats = ms.stats()
            assert "vector_store" in stats
            assert "enabled" in stats["vector_store"]

    def test_semantic_search_returns_list(self):
        """semantic_search() 应返回列表。"""
        import tempfile
        from pathlib import Path
        from memory.memory_system import MemorySystem

        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as td:
            ms = MemorySystem(data_dir=Path(td))
            results = ms.semantic_search("test query")
            assert isinstance(results, list)

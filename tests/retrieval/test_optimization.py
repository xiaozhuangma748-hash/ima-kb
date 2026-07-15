"""检索优化测试：语义缓存 + 查询路由 + 并发检索。"""
from __future__ import annotations

import time
import numpy as np
import pytest

from core.retrieval.semantic_cache import SemanticCache, CacheEntry
from core.retrieval.router import route_query, should_skip_retrieval, should_use_cache


class TestSemanticCache:
    """语义缓存测试。"""

    def test_l1_exact_match(self):
        """L1 精确缓存：相同 query 直接命中。"""
        cache = SemanticCache(threshold=0.9, ttl=60, max_size=10)
        emb = np.random.rand(512).tolist()
        cache.put("什么是生态安葬？", emb, "生态安葬是...")
        entry = cache.get("什么是生态安葬？")
        assert entry is not None
        assert entry.answer == "生态安葬是..."

    def test_l2_semantic_match(self):
        """L2 语义缓存：相似 embedding 命中。"""
        cache = SemanticCache(threshold=0.9, ttl=60, max_size=10)
        emb1 = np.random.rand(512).tolist()
        cache.put("什么是生态安葬？", emb1, "生态安葬是...")
        # 相同 embedding 应命中
        entry = cache.get("生态安葬是什么意思？", emb1)
        assert entry is not None
        assert entry.answer == "生态安葬是..."

    def test_no_match_different_embedding(self):
        """不同 embedding 不应命中。"""
        cache = SemanticCache(threshold=0.99, ttl=60, max_size=10)  # 高阈值
        emb1 = np.random.rand(512).tolist()
        emb2 = np.random.rand(512).tolist()
        cache.put("问题1", emb1, "答案1")
        entry = cache.get("问题2", emb2)
        assert entry is None

    def test_ttl_expiry(self):
        """TTL 过期后不命中。"""
        cache = SemanticCache(threshold=0.9, ttl=1, max_size=10)  # 1 秒过期
        emb = np.random.rand(512).tolist()
        cache.put("问题", emb, "答案")
        time.sleep(1.2)  # 等待过期
        entry = cache.get("问题")
        assert entry is None

    def test_lru_eviction(self):
        """超容量时淘汰最旧的。"""
        cache = SemanticCache(threshold=0.9, ttl=60, max_size=3)
        for i in range(5):
            cache.put(f"问题{i}", np.random.rand(512).tolist(), f"答案{i}")
        stats = cache.stats()
        assert stats["size"] == 3  # 不超过 max_size

    def test_hit_count(self):
        """命中次数统计。"""
        cache = SemanticCache(threshold=0.9, ttl=60, max_size=10)
        emb = np.random.rand(512).tolist()
        cache.put("问题", emb, "答案")
        cache.get("问题")
        cache.get("问题")
        cache.get("问题", emb)
        stats = cache.stats()
        assert stats["total_hits"] == 3

    def test_clear(self):
        """清空缓存。"""
        cache = SemanticCache(threshold=0.9, ttl=60, max_size=10)
        cache.put("问题", np.random.rand(512).tolist(), "答案")
        assert cache.stats()["size"] == 1
        cache.clear()
        assert cache.stats()["size"] == 0

    def test_cleanup_expired(self):
        """清理过期条目。"""
        cache = SemanticCache(threshold=0.9, ttl=1, max_size=10)
        cache.put("问题1", np.random.rand(512).tolist(), "答案1")
        cache.put("问题2", np.random.rand(512).tolist(), "答案2")
        time.sleep(1.2)
        cleaned = cache.cleanup_expired()
        assert cleaned == 2
        assert cache.stats()["size"] == 0

    def test_thread_safety(self):
        """线程安全：多线程并发读写。"""
        import threading
        cache = SemanticCache(threshold=0.5, ttl=60, max_size=100)
        errors = []

        def writer():
            try:
                for i in range(20):
                    cache.put(f"问题{i}", np.random.rand(512).tolist(), f"答案{i}")
            except Exception as e:
                errors.append(e)

        def reader():
            try:
                for i in range(20):
                    cache.get(f"问题{i}", np.random.rand(512).tolist())
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=writer) for _ in range(3)]
        threads += [threading.Thread(target=reader) for _ in range(3)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert not errors


class TestQueryRouter:
    """查询路由测试。"""

    def test_greeting(self):
        """问候语路由。"""
        assert route_query("你好") == "greeting"
        assert route_query("您好") == "greeting"
        assert route_query("谢谢") == "greeting"
        assert route_query("hi") == "greeting"
        assert route_query("早上好") == "greeting"

    def test_meta_question(self):
        """元问题路由。"""
        assert route_query("你是谁") == "chat"
        assert route_query("你能做什么") == "chat"
        assert route_query("你叫什么名字") == "chat"

    def test_knowledge_query(self):
        """知识查询路由。"""
        assert route_query("什么是生态安葬？") == "knowledge"
        assert route_query("杭州海葬补贴政策") == "knowledge"
        assert route_query("如何申请殡葬补助") == "knowledge"
        assert route_query("骨灰撒海的费用是多少") == "knowledge"

    def test_short_unknown(self):
        """短文本未知意图 → chat。"""
        assert route_query("好的") == "chat"
        assert route_query("嗯") == "chat"

    def test_long_default_knowledge(self):
        """长文本默认走知识库。"""
        assert route_query("我想了解一下关于殡葬改革的相关内容") == "knowledge"

    def test_should_skip_retrieval(self):
        """跳过检索判断。"""
        assert should_skip_retrieval("你好") == True
        assert should_skip_retrieval("谢谢") == True
        assert should_skip_retrieval("什么是生态安葬？") == False

    def test_should_use_cache(self):
        """使用缓存判断。"""
        assert should_use_cache("什么是生态安葬？") == True
        assert should_use_cache("你好") == False


class TestHybridRetrieverIntegration:
    """混合检索器集成测试（不依赖真实模型）。"""

    def test_cache_integration(self):
        """测试检索器与语义缓存的集成。"""
        from core.retrieval.hybrid import HybridRetriever, HybridResult
        from unittest.mock import MagicMock

        # Mock BM25 和 Vector
        mock_bm25 = MagicMock()
        mock_vector = MagicMock()
        mock_vector.is_available.return_value = False  # 禁用向量，走纯 BM25

        mock_bm25.search.return_value = [
            MagicMock(chunk_id="c1", doc_id="d1", score=1.0, content="内容1", doc_title="文档1")
        ]

        retriever = HybridRetriever(
            bm25_index=mock_bm25,
            vector_index=mock_vector,
            storage=None,
            enable_cache=False,  # 禁用缓存，测试纯检索
        )

        results = retriever.search("测试查询", top_k=5)
        assert len(results) == 1
        assert results[0].chunk_id == "c1"

    def test_cache_stats(self):
        """测试缓存统计接口。"""
        from core.retrieval.hybrid import HybridRetriever
        from unittest.mock import MagicMock

        mock_bm25 = MagicMock()
        mock_vector = MagicMock()
        mock_vector.is_available.return_value = False

        # 启用缓存
        retriever = HybridRetriever(
            bm25_index=mock_bm25,
            vector_index=mock_vector,
            storage=None,
            enable_cache=True,
        )
        stats = retriever.cache_stats()
        assert stats["enabled"] == True
        assert "size" in stats

        # 禁用缓存
        retriever_no_cache = HybridRetriever(
            bm25_index=mock_bm25,
            vector_index=mock_vector,
            storage=None,
            enable_cache=False,
        )
        stats = retriever_no_cache.cache_stats()
        assert stats["enabled"] == False

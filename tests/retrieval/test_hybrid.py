"""混合检索测试。"""
import pytest
from unittest.mock import MagicMock, patch
from core.retrieval.hybrid import HybridResult, HybridRetriever


def test_hybrid_result_dataclass():
    """HybridResult 包含 chunk_id/doc_id/score/source。"""
    r = HybridResult(chunk_id="c1", doc_id="d1", score=0.5, source="both")
    assert r.chunk_id == "c1"
    assert r.doc_id == "d1"
    assert r.score == 0.5
    assert r.source == "both"


def test_rrf_fusion_both_sources():
    """BM25 和向量都命中的 chunk source='both'。"""
    bm25 = MagicMock()
    bm25.search.return_value = [
        MagicMock(chunk_id="c1", doc_id="d1", score=0.9, content="content1", doc_title="title1"),
        MagicMock(chunk_id="c2", doc_id="d2", score=0.8, content="content2", doc_title="title2"),
    ]
    vector = MagicMock()
    vector.is_available.return_value = True
    vector.search.return_value = [
        MagicMock(chunk_id="c1", doc_id="d1", score=0.95),
        MagicMock(chunk_id="c3", doc_id="d3", score=0.85),
    ]

    retriever = HybridRetriever(bm25_index=bm25, vector_index=vector)
    results = retriever.search("查询", top_k=5)

    assert len(results) >= 1
    # c1 在两边都出现，source 应为 "both"
    c1 = next(r for r in results if r.chunk_id == "c1")
    assert c1.source == "both"


def test_rrf_fusion_bm25_only():
    """只在 BM25 命中的 chunk source='bm25'。"""
    bm25 = MagicMock()
    bm25.search.return_value = [
        MagicMock(chunk_id="c1", doc_id="d1", score=0.9, content="c1", doc_title="t1"),
        MagicMock(chunk_id="c2", doc_id="d2", score=0.8, content="c2", doc_title="t2"),
    ]
    vector = MagicMock()
    vector.is_available.return_value = True
    vector.search.return_value = [
        MagicMock(chunk_id="c3", doc_id="d3", score=0.9),
    ]

    retriever = HybridRetriever(bm25_index=bm25, vector_index=vector)
    results = retriever.search("查询", top_k=5)

    c2 = next(r for r in results if r.chunk_id == "c2")
    assert c2.source == "bm25"


def test_vector_unavailable_degrades_to_bm25():
    """向量不可用时降级为纯 BM25。"""
    bm25 = MagicMock()
    bm25.search.return_value = [
        MagicMock(chunk_id="c1", doc_id="d1", score=0.9, content="c1", doc_title="t1"),
    ]
    vector = MagicMock()
    vector.is_available.return_value = False

    retriever = HybridRetriever(bm25_index=bm25, vector_index=vector)
    results = retriever.search("查询", top_k=5)

    assert len(results) == 1
    assert results[0].source == "bm25"


def test_empty_results():
    """BM25 和向量都返回空时返回空列表。"""
    bm25 = MagicMock()
    bm25.search.return_value = []
    vector = MagicMock()
    vector.is_available.return_value = True
    vector.search.return_value = []

    retriever = HybridRetriever(bm25_index=bm25, vector_index=vector)
    results = retriever.search("查询", top_k=5)
    assert results == []


def test_top_k_limit():
    """结果数量不超过 top_k。"""
    bm25 = MagicMock()
    bm25.search.return_value = [
        MagicMock(chunk_id=f"c{i}", doc_id=f"d{i}", score=0.9, content="c", doc_title="t")
        for i in range(10)
    ]
    vector = MagicMock()
    vector.is_available.return_value = True
    vector.search.return_value = []

    retriever = HybridRetriever(bm25_index=bm25, vector_index=vector)
    results = retriever.search("查询", top_k=3)
    assert len(results) == 3

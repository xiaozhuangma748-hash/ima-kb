"""元数据预过滤测试（hybrid.search 的 doc_ids 参数）。"""
from unittest.mock import MagicMock, patch

import pytest

from core.retrieval.hybrid import HybridRetriever, HybridResult
from core.search.bm25 import SearchResult
from core.retrieval.vector import VectorResult


def _make_bm25_result(cid, doc_id, score=0.5):
    return SearchResult(chunk_id=cid, doc_id=doc_id, score=score)


def _make_vec_result(cid, doc_id, score=0.5):
    return VectorResult(chunk_id=cid, doc_id=doc_id, score=score)


# ============================================================
# HybridRetriever.search 的 doc_ids 过滤
# ============================================================

def test_search_no_doc_ids_no_filter():
    """doc_ids=None 时不过滤。"""
    bm25 = MagicMock()
    bm25.search.return_value = [
        _make_bm25_result("d1_0", "doc1"),
        _make_bm25_result("d2_0", "doc2"),
    ]
    vector = MagicMock()
    vector.is_available.return_value = True
    vector.search.return_value = [
        _make_vec_result("d1_0", "doc1"),
        _make_vec_result("d3_0", "doc3"),
    ]
    vector.embed_query.return_value = None  # 禁用语义缓存

    retriever = HybridRetriever(bm25, vector, enable_cache=False)
    results = retriever.search("test", top_k=5, doc_ids=None)

    # 不过滤，所有结果都保留
    doc_ids = {r.doc_id for r in results}
    assert "doc1" in doc_ids
    assert "doc2" in doc_ids or "doc3" in doc_ids  # 至少有其他文档


def test_search_filters_bm25_by_doc_ids():
    """doc_ids 过滤 BM25 结果。"""
    bm25 = MagicMock()
    bm25.search.return_value = [
        _make_bm25_result("d1_0", "doc1", 0.9),
        _make_bm25_result("d2_0", "doc2", 0.5),  # 应被过滤掉
        _make_bm25_result("d3_0", "doc3", 0.3),  # 应被过滤掉
    ]
    vector = MagicMock()
    vector.is_available.return_value = False  # 纯 BM25 模式

    retriever = HybridRetriever(bm25, vector, enable_cache=False)
    results = retriever.search("test", top_k=5, doc_ids=["doc1"])

    # 只保留 doc1 的结果
    assert all(r.doc_id == "doc1" for r in results)
    assert len(results) == 1


def test_search_passes_where_to_vector():
    """doc_ids 转换为 where 条件传给向量检索。"""
    bm25 = MagicMock()
    bm25.search.return_value = []
    vector = MagicMock()
    vector.is_available.return_value = True
    vector.search.return_value = [
        _make_vec_result("d1_0", "doc1"),
    ]
    vector.embed_query.return_value = None

    retriever = HybridRetriever(bm25, vector, enable_cache=False)
    retriever.search("test", top_k=5, doc_ids=["doc1"])

    # 验证 vector.search 收到了 where 参数
    vector.search.assert_called_once()
    call_args = vector.search.call_args
    where = call_args[1].get("where") if "where" in call_args[1] else (
        call_args[0][2] if len(call_args[0]) > 2 else None
    )
    assert where is not None
    assert where == {"doc_id": "doc1"}


def test_search_multiple_doc_ids_where():
    """多个 doc_ids 转换为 $in 条件。"""
    bm25 = MagicMock()
    bm25.search.return_value = []
    vector = MagicMock()
    vector.is_available.return_value = True
    vector.search.return_value = []
    vector.embed_query.return_value = None

    retriever = HybridRetriever(bm25, vector, enable_cache=False)
    retriever.search("test", top_k=5, doc_ids=["doc1", "doc2"])

    call_args = vector.search.call_args
    where = call_args[1].get("where") if "where" in call_args[1] else (
        call_args[0][2] if len(call_args[0]) > 2 else None
    )
    assert where == {"doc_id": {"$in": ["doc1", "doc2"]}}


def test_search_filters_both_bm25_and_vector():
    """doc_ids 同时过滤 BM25 和向量结果。"""
    bm25 = MagicMock()
    bm25.search.return_value = [
        _make_bm25_result("d1_0", "doc1", 0.9),
        _make_bm25_result("d2_0", "doc2", 0.8),  # 被过滤
    ]
    vector = MagicMock()
    vector.is_available.return_value = True
    vector.search.return_value = [
        _make_vec_result("d1_1", "doc1", 0.7),
        _make_vec_result("d3_0", "doc3", 0.6),  # 向量不过滤（where 处理），但这里模拟返回了
    ]
    vector.embed_query.return_value = None

    retriever = HybridRetriever(bm25, vector, enable_cache=False)
    results = retriever.search("test", top_k=5, doc_ids=["doc1"])

    # BM25 结果中 doc2 被过滤
    bm25_results_in_fusion = [r for r in results if r.source in ("bm25", "both")]
    assert all(r.doc_id == "doc1" for r in bm25_results_in_fusion)

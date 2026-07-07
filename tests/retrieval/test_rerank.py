"""LLM 重排序测试。"""
import pytest
from unittest.mock import MagicMock
from core.retrieval.rerank import RerankResult, Reranker
from core.retrieval.hybrid import HybridResult


def test_rerank_result_dataclass():
    """RerankResult 包含 reason 字段。"""
    r = RerankResult(
        chunk_id="c1", doc_id="d1", score=0.9,
        source="both", content="内容", doc_title="标题",
        relevance_score=8.5, reason="高度相关"
    )
    assert r.relevance_score == 8.5
    assert r.reason == "高度相关"


def test_rerank_reorders_by_score():
    """LLM 打分后按分数降序排列。"""
    candidates = [
        HybridResult(chunk_id="c1", doc_id="d1", score=0.1, source="bm25", content="内容1", doc_title="标题1"),
        HybridResult(chunk_id="c2", doc_id="d2", score=0.2, source="vector", content="内容2", doc_title="标题2"),
        HybridResult(chunk_id="c3", doc_id="d3", score=0.3, source="both", content="内容3", doc_title="标题3"),
    ]
    # mock LLM 返回：c2 最相关（9分），c1 次之（5分），c3 最不相关（3分）
    llm = MagicMock()
    llm.chat.return_value = '[{"index": 0, "score": 5, "reason": "一般"}, {"index": 1, "score": 9, "reason": "高度相关"}, {"index": 2, "score": 3, "reason": "不太相关"}]'

    reranker = Reranker(llm)
    results = reranker.rerank("查询", candidates, top_n=3)

    assert results[0].chunk_id == "c2"
    assert results[0].relevance_score == 9
    assert results[1].chunk_id == "c1"
    assert results[2].chunk_id == "c3"


def test_rerank_top_n_limit():
    """top_n 限制返回数量。"""
    candidates = [
        HybridResult(chunk_id=f"c{i}", doc_id=f"d{i}", score=0.1, source="bm25", content=f"内容{i}", doc_title=f"标题{i}")
        for i in range(5)
    ]
    llm = MagicMock()
    llm.chat.return_value = '[{"index": 0, "score": 5, "reason": "r"}, {"index": 1, "score": 9, "reason": "r"}, {"index": 2, "score": 3, "reason": "r"}, {"index": 3, "score": 7, "reason": "r"}, {"index": 4, "score": 1, "reason": "r"}]'

    reranker = Reranker(llm)
    results = reranker.rerank("查询", candidates, top_n=2)
    assert len(results) == 2


def test_rerank_llm_failure_keeps_original_order():
    """LLM 失败时保留原顺序。"""
    candidates = [
        HybridResult(chunk_id="c1", doc_id="d1", score=0.5, source="bm25", content="内容1", doc_title="标题1"),
        HybridResult(chunk_id="c2", doc_id="d2", score=0.3, source="vector", content="内容2", doc_title="标题2"),
    ]
    llm = MagicMock()
    llm.chat.side_effect = Exception("LLM 不可用")

    reranker = Reranker(llm)
    results = reranker.rerank("查询", candidates, top_n=2)

    # 保留原顺序
    assert results[0].chunk_id == "c1"
    assert results[1].chunk_id == "c2"
    # relevance_score 为 0（降级）
    assert results[0].relevance_score == 0


def test_rerank_empty_candidates():
    """空候选列表返回空结果。"""
    llm = MagicMock()
    reranker = Reranker(llm)
    results = reranker.rerank("查询", [], top_n=5)
    assert results == []


def test_rerank_handles_malformed_llm_response():
    """LLM 返回格式错误时降级为原顺序。"""
    candidates = [
        HybridResult(chunk_id="c1", doc_id="d1", score=0.5, source="bm25", content="内容1", doc_title="标题1"),
    ]
    llm = MagicMock()
    llm.chat.return_value = "这不是 JSON 格式"

    reranker = Reranker(llm)
    results = reranker.rerank("查询", candidates, top_n=1)
    assert len(results) == 1
    assert results[0].chunk_id == "c1"

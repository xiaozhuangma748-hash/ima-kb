"""Parent-Document 上下文扩展测试。"""
from unittest.mock import MagicMock

import pytest

from core.retrieval.parent_document import (
    enrich_results,
    get_parent_context,
    _PARENT_SEPARATOR,
)
from core.retrieval.hybrid import HybridResult
from core.storage import ChunkRecord


def _make_chunk(cid: str, doc_id: str, idx: int, content: str) -> ChunkRecord:
    """构造测试用 ChunkRecord。"""
    return ChunkRecord(
        id=cid, doc_id=doc_id, index=idx, content=content,
        token_count=0, start_char=0, end_char=len(content),
    )


def _make_result(chunk_id: str, doc_id: str, content: str = "matched") -> HybridResult:
    """构造测试用 HybridResult。"""
    return HybridResult(
        chunk_id=chunk_id, doc_id=doc_id, score=0.5,
        source="both", content=content, doc_title="test",
    )


# ============================================================
# get_parent_context
# ============================================================

def test_get_parent_context_window_zero():
    """window=0 时返回空字符串。"""
    storage = MagicMock()
    assert get_parent_context(storage, "doc1", 2, window=0) == ""


def test_get_parent_context_middle_chunk():
    """中间 chunk：前后各 1 个。"""
    chunks = [
        _make_chunk("doc1_0", "doc1", 0, "前文"),
        _make_chunk("doc1_1", "doc1", 1, "匹配片段"),
        _make_chunk("doc1_2", "doc1", 2, "后文"),
    ]
    storage = MagicMock()
    storage.get_chunks.return_value = chunks

    result = get_parent_context(storage, "doc1", 1, window=1)
    assert "前文" in result
    assert "后文" in result
    assert "匹配片段" not in result  # 当前 chunk 不含


def test_get_parent_context_first_chunk():
    """第一个 chunk：无前文，只有后文。"""
    chunks = [
        _make_chunk("doc1_0", "doc1", 0, "第一段"),
        _make_chunk("doc1_1", "doc1", 1, "第二段"),
        _make_chunk("doc1_2", "doc1", 2, "第三段"),
    ]
    storage = MagicMock()
    storage.get_chunks.return_value = chunks

    result = get_parent_context(storage, "doc1", 0, window=1)
    assert "第一段" not in result  # 当前 chunk
    assert "第二段" in result


def test_get_parent_context_last_chunk():
    """最后一个 chunk：无后文，只有前文。"""
    chunks = [
        _make_chunk("doc1_0", "doc1", 0, "第一段"),
        _make_chunk("doc1_1", "doc1", 1, "第二段"),
        _make_chunk("doc1_2", "doc1", 2, "最后一段"),
    ]
    storage = MagicMock()
    storage.get_chunks.return_value = chunks

    result = get_parent_context(storage, "doc1", 2, window=1)
    assert "最后一段" not in result  # 当前 chunk
    assert "第二段" in result


def test_get_parent_context_storage_error_returns_empty():
    """storage 查询异常时返回空字符串。"""
    storage = MagicMock()
    storage.get_chunks.side_effect = Exception("db error")
    assert get_parent_context(storage, "doc1", 0) == ""


def test_get_parent_context_no_chunks_returns_empty():
    """无 chunks 时返回空字符串。"""
    storage = MagicMock()
    storage.get_chunks.return_value = []
    assert get_parent_context(storage, "doc1", 0) == ""


# ============================================================
# enrich_results
# ============================================================

def test_enrich_results_empty_list():
    """空结果列表直接返回。"""
    storage = MagicMock()
    assert enrich_results(storage, [], window=1) == []


def test_enrich_results_window_zero():
    """window=0 不附加上下文。"""
    storage = MagicMock()
    r = _make_result("doc1_1", "doc1", "原始内容")
    result = enrich_results(storage, [r], window=0)
    assert result[0].content == "原始内容"
    storage.get_chunks.assert_not_called()


def test_enrich_results_appends_parent_context():
    """附加 parent context 到 content 后面。"""
    chunks = [
        _make_chunk("doc1_0", "doc1", 0, "前文内容"),
        _make_chunk("doc1_1", "doc1", 1, "匹配片段"),
        _make_chunk("doc1_2", "doc1", 2, "后文内容"),
    ]
    storage = MagicMock()
    storage.get_chunks.return_value = chunks

    r = _make_result("doc1_1", "doc1", "匹配片段")
    enrich_results(storage, [r], window=1)

    assert "匹配片段" in r.content
    assert _PARENT_SEPARATOR in r.content
    assert "前文内容" in r.content
    assert "后文内容" in r.content


def test_enrich_results_batch_no_n_plus_1():
    """同一文档的多个结果只查询一次 chunks。"""
    chunks = [
        _make_chunk("doc1_0", "doc1", 0, "段0"),
        _make_chunk("doc1_1", "doc1", 1, "段1"),
        _make_chunk("doc1_2", "doc1", 2, "段2"),
    ]
    storage = MagicMock()
    storage.get_chunks.return_value = chunks

    results = [
        _make_result("doc1_0", "doc1", "段0"),
        _make_result("doc1_2", "doc1", "段2"),
    ]
    enrich_results(storage, results, window=1)

    # 只查询了一次（同一文档）
    assert storage.get_chunks.call_count == 1


def test_enrich_results_multiple_docs():
    """多个文档的结果分别查询。"""
    chunks_doc1 = [
        _make_chunk("d1_0", "d1", 0, "d1段0"),
        _make_chunk("d1_1", "d1", 1, "d1段1"),
    ]
    chunks_doc2 = [
        _make_chunk("d2_0", "d2", 0, "d2段0"),
        _make_chunk("d2_1", "d2", 1, "d2段1"),
    ]

    storage = MagicMock()
    storage.get_chunks.side_effect = [chunks_doc1, chunks_doc2]

    results = [
        _make_result("d1_0", "d1", "d1段0"),
        _make_result("d2_1", "d2", "d2段1"),
    ]
    enrich_results(storage, results, window=1)

    assert storage.get_chunks.call_count == 2
    # d1_0 的 parent 是 d1段1
    assert "d1段1" in results[0].content
    # d2_1 的 parent 是 d2段0
    assert "d2段0" in results[1].content


def test_enrich_results_no_doc_id_skipped():
    """无 doc_id 的结果被跳过。"""
    storage = MagicMock()
    r = _make_result("doc1_1", "", "内容")
    r.doc_id = ""
    enrich_results(storage, [r], window=1)
    assert r.content == "内容"  # 未被修改


def test_enrich_results_chunk_not_found_skipped():
    """chunk_id 在 chunks 列表中找不到时跳过。"""
    chunks = [_make_chunk("doc1_0", "doc1", 0, "段0")]
    storage = MagicMock()
    storage.get_chunks.return_value = chunks

    r = _make_result("doc1_99", "doc1", "内容")  # index 99 不存在
    enrich_results(storage, [r], window=1)
    assert r.content == "内容"  # 未被修改

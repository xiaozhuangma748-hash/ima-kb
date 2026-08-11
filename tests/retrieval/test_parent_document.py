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
    """window=0 且无 parent_content 时不附加上下文。

    注：small-to-big 升级后，window=0 仍会调用 get_chunks 检查 parent_content，
    但 parent_content 为空时降级到 window 方式，window=0 跳过，content 不变。
    """
    chunks = [_make_chunk("doc1_1", "doc1", 1, "原始内容")]
    storage = MagicMock()
    storage.get_chunks.return_value = chunks
    r = _make_result("doc1_1", "doc1", "原始内容")
    result = enrich_results(storage, [r], window=0)
    assert result[0].content == "原始内容"


def test_enrich_results_uses_parent_content():
    """small-to-big: 有 parent_content 时优先使用，替换 content。"""
    # chunk 有 parent_content（比 content 长）
    chunk = ChunkRecord(
        id="doc1_1", doc_id="doc1", index=1, content="小片段",
        token_count=0, start_char=0, end_char=4,
        parent_content="完整章节内容（包含小片段和其他内容）",
    )
    storage = MagicMock()
    storage.get_chunks.return_value = [chunk]
    r = _make_result("doc1_1", "doc1", "小片段")
    enrich_results(storage, [r], window=1)
    # parent_content 比 content 长，应替换
    assert "完整章节内容" in r.content
    assert r.content == "完整章节内容（包含小片段和其他内容）"


def test_enrich_results_uses_hybrid_result_parent_content_no_query():
    """优化路径：HybridResult 已携带 parent_content 时，不再回表查 storage。

    场景：storage.enrich_hybrid_results 已在一次 IN 查询中取出 parent_content
    并填入 HybridResult.parent_content。enrich_results 应直接消费，避免 N+1。
    """
    storage = MagicMock()
    # 关键断言：不应调用 get_chunks（已通过 HybridResult 携带）
    r = _make_result("doc1_1", "doc1", "小片段")
    r.parent_content = "完整章节内容（包含小片段和其他内容）"
    enrich_results(storage, [r], window=1)
    assert storage.get_chunks.call_count == 0
    assert r.content == "完整章节内容（包含小片段和其他内容）"


def test_enrich_results_mixed_carry_and_missing():
    """混合场景：部分 result 携带 parent_content，部分没有。

    携带的不触发查询；缺失的走降级路径批量查询。
    """
    chunks = [
        _make_chunk("doc1_0", "doc1", 0, "段0"),
        _make_chunk("doc1_1", "doc1", 1, "段1"),
    ]
    storage = MagicMock()
    storage.get_chunks.return_value = chunks

    r1 = _make_result("doc1_1", "doc1", "段1原文")
    r1.parent_content = "段1的父级内容（更长）" * 3  # 比 content 长
    r2 = _make_result("doc1_0", "doc1", "段0原文")  # 无 parent_content
    enrich_results(storage, [r1, r2], window=1)

    # r1 走热路径，r2 走降级路径 → 总共只查 1 次（doc1）
    assert storage.get_chunks.call_count == 1
    # r1 用了携带的 parent_content
    assert "段1的父级内容" in r1.content
    # r2 走 window 降级，附加了相邻段
    assert "段1" in r2.content


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

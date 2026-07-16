"""Lost in Middle 重排 + Context 压缩测试。"""
from unittest.mock import MagicMock

import pytest

from core.retrieval.context_optimizer import (
    reorder_lost_in_middle,
    compress_context,
    compress_results,
)
from core.retrieval.hybrid import HybridResult


def _make_result(score: float, content: str = "test") -> HybridResult:
    return HybridResult(
        chunk_id=f"c{score}", doc_id="d1", score=score,
        source="both", content=content, doc_title="test",
    )


# ============================================================
# reorder_lost_in_middle
# ============================================================

def test_reorder_empty_list():
    """空列表返回空列表。"""
    assert reorder_lost_in_middle([]) == []


def test_reorder_single_element():
    """单元素不重排。"""
    r = _make_result(0.9)
    assert reorder_lost_in_middle([r]) == [r]


def test_reorder_two_elements():
    """两个元素不重排。"""
    r0, r1 = _make_result(0.9), _make_result(0.8)
    result = reorder_lost_in_middle([r0, r1])
    assert result == [r0, r1]


def test_reorder_three_elements():
    """三个元素：最相关在两端，最不相关在中间。"""
    r0, r1, r2 = _make_result(0.9), _make_result(0.8), _make_result(0.7)
    result = reorder_lost_in_middle([r0, r1, r2])
    # [r0, r1, r2] → even=[r0, r2], odd=[r1], reversed_odd=[r1]
    # 结果: [r0, r2, r1]
    assert result[0] is r0   # 最相关在最前
    assert result[-1] is r1   # 次相关在最后
    assert result[1] is r2    # 最不相关在中间


def test_reorder_five_elements():
    """五个元素：蛇形排列。"""
    results = [_make_result(0.9 - i * 0.1) for i in range(5)]
    # [r0, r1, r2, r3, r4] → even=[r0, r2, r4], odd=[r1, r3], reversed_odd=[r3, r1]
    # 结果: [r0, r2, r4, r3, r1]
    reordered = reorder_lost_in_middle(results)
    assert reordered[0] is results[0]   # 最相关在开头
    assert reordered[-1] is results[1]  # 次相关在结尾
    assert reordered[2] is results[4]   # 最不相关在中间附近


def test_reorder_does_not_modify_original():
    """重排不修改原列表。"""
    results = [_make_result(0.9 - i * 0.1) for i in range(5)]
    original = list(results)
    reorder_lost_in_middle(results)
    assert results == original


def test_reorder_preserves_all_elements():
    """重排后元素数量不变。"""
    results = [_make_result(0.9 - i * 0.1) for i in range(7)]
    reordered = reorder_lost_in_middle(results)
    assert len(reordered) == len(results)
    assert set(id(r) for r in reordered) == set(id(r) for r in results)


# ============================================================
# compress_context
# ============================================================

def test_compress_short_text_unchanged():
    """短文本不压缩。"""
    text = "这是一段短文本"
    assert compress_context(text, max_chars=100) == text


def test_compress_empty_text():
    """空文本返回空。"""
    assert compress_context("", max_chars=100) == ""


def test_compress_long_text():
    """长文本压缩为前半+省略号+后半。"""
    text = "A" * 200
    result = compress_context(text, max_chars=100)
    assert len(result) <= 110  # 前半50 + \n...\n + 后半50 = 约110
    assert "..." in result
    assert result.startswith("A" * 50)
    assert result.endswith("A" * 50)


def test_compress_exact_boundary():
    """恰好等于 max_chars 时不压缩。"""
    text = "A" * 100
    assert compress_context(text, max_chars=100) == text


def test_compress_zero_max_chars():
    """max_chars=0 时不压缩。"""
    text = "A" * 200
    assert compress_context(text, max_chars=0) == text


# ============================================================
# compress_results
# ============================================================

def test_compress_results_empty_list():
    """空列表直接返回。"""
    assert compress_results([], max_chars=100) == []


def test_compress_results_compresses_content():
    """批量压缩 results 中每个 result 的 content。"""
    results = [
        _make_result(0.9, "A" * 200),
        _make_result(0.8, "B" * 50),
    ]
    compress_results(results, max_chars=100)
    assert len(results[0].content) <= 110  # 被压缩
    assert results[1].content == "B" * 50  # 未被压缩（短于 max_chars）


def test_compress_results_zero_max_chars():
    """max_chars=0 时不压缩。"""
    results = [_make_result(0.9, "A" * 200)]
    compress_results(results, max_chars=0)
    assert results[0].content == "A" * 200


def test_compress_results_modifies_in_place():
    """压缩原地修改 results。"""
    results = [_make_result(0.9, "A" * 200)]
    returned = compress_results(results, max_chars=100)
    assert returned is results  # 同一对象
    assert len(results[0].content) <= 110


# ============================================================
# _build_user_prompt low_conf 不依赖顺序
# ============================================================

def test_build_user_prompt_low_conf_uses_max_score():
    """low_conf 判断用最高分，不依赖顺序。"""
    from core.qa.chain import _build_user_prompt, DEFAULT_CONFIDENCE_THRESHOLD

    # results[0] 是低分，results[1] 是高分
    results = [
        _make_result(0.001, "低分内容"),
        _make_result(0.15, "高分内容"),
    ]
    prompt, low_conf = _build_user_prompt(
        "test question", results,
        confidence_threshold=DEFAULT_CONFIDENCE_THRESHOLD,
    )
    # 最高分 0.15 > 0.05，不应是 low_conf
    assert not low_conf


def test_build_user_prompt_all_low_conf():
    """所有分数都低于阈值时 low_conf=True。"""
    from core.qa.chain import _build_user_prompt, DEFAULT_CONFIDENCE_THRESHOLD

    results = [
        _make_result(0.001, "低分1"),
        _make_result(0.002, "低分2"),
    ]
    prompt, low_conf = _build_user_prompt(
        "test question", results,
        confidence_threshold=DEFAULT_CONFIDENCE_THRESHOLD,
    )
    assert low_conf  # 最高分 0.002 < 0.05

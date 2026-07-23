"""Query Transform 测试：HyDE + 子问题分解。"""
import pytest
from unittest.mock import MagicMock

from core.retrieval.query_transform import (
    hyde_transform, decompose_query, transform_query,
    QueryTransformResult, _parse_sub_queries,
)


# ============================================================
# HyDE 测试
# ============================================================

def test_hyde_disabled_returns_original():
    """HyDE 禁用时返回原 query。"""
    llm = MagicMock()
    new_q, source = hyde_transform("查询", llm, enabled=False)
    assert new_q == "查询"
    assert source == "original"
    llm.chat.assert_not_called()


def test_hyde_short_query_returns_original():
    """过短 query（<8 字符）不触发 HyDE。"""
    llm = MagicMock()
    new_q, source = hyde_transform("短", llm, enabled=True)
    assert new_q == "短"
    assert source == "original"
    llm.chat.assert_not_called()


def test_hyde_llm_none_returns_original():
    """LLM 为 None 时返回原 query。"""
    new_q, source = hyde_transform("这是一个查询", None, enabled=True)
    assert new_q == "这是一个查询"
    assert source == "original"


def test_hyde_success_returns_hypothesis():
    """HyDE 成功时返回假设答案。"""
    llm = MagicMock()
    llm.chat.return_value = "根据《殡葬管理条例》规定，节地生态安葬是指..."

    new_q, source = hyde_transform("什么是节地生态安葬", llm, enabled=True)

    assert source == "hyde"
    assert new_q == "根据《殡葬管理条例》规定，节地生态安葬是指..."
    llm.chat.assert_called_once()


def test_hyde_llm_failure_falls_back():
    """LLM 失败时回退到原 query。"""
    llm = MagicMock()
    llm.chat.side_effect = RuntimeError("LLM 不可用")

    new_q, source = hyde_transform("这是一个长查询", llm, enabled=True)

    assert new_q == "这是一个长查询"
    assert source == "original"


def test_hyde_empty_response_falls_back():
    """LLM 返回空内容时回退。"""
    llm = MagicMock()
    llm.chat.return_value = ""

    new_q, source = hyde_transform("这是一个长查询", llm, enabled=True)

    assert new_q == "这是一个长查询"
    assert source == "original"


# ============================================================
# 子问题分解测试
# ============================================================

def test_decompose_short_query_returns_single():
    """短 query 不触发分解。"""
    llm = MagicMock()
    result = decompose_query("短查询", llm, enabled=True)
    assert result == ["短查询"]
    llm.chat.assert_not_called()


def test_decompose_disabled_returns_single():
    """分解禁用时返回原 query。"""
    llm = MagicMock()
    result = decompose_query("这是一个比较长的查询", llm, enabled=False)
    assert result == ["这是一个比较长的查询"]


def test_decompose_success_returns_multiple():
    """分解成功返回多个子问题。"""
    llm = MagicMock()
    llm.chat.return_value = '["什么是海葬？", "什么是树葬？", "海葬和树葬有什么区别？"]'

    # 18 字以上且含"和/区别"复合信号，满足新的分解门槛
    result = decompose_query("请详细说明海葬和树葬的区别及各自的具体费用是多少", llm, enabled=True)

    assert len(result) == 3
    assert "什么是海葬？" in result
    assert "什么是树葬？" in result


def test_decompose_failure_falls_back():
    """LLM 失败时回退到原 query。"""
    llm = MagicMock()
    llm.chat.side_effect = RuntimeError("LLM 不可用")

    result = decompose_query("这是一个比较长的查询", llm, enabled=True)
    assert result == ["这是一个比较长的查询"]


def test_decompose_limits_to_four_subqueries():
    """子问题最多 4 个。"""
    llm = MagicMock()
    llm.chat.return_value = '["q1", "q2", "q3", "q4", "q5", "q6"]'

    # query 必须 >= _DECOMPOSE_MIN_QUERY_LEN(18) 且含复合信号才触发分解
    result = decompose_query("请对比分析杭州和上海两地在生态安葬政策上的具体差异有哪些", llm, enabled=True)
    assert len(result) == 4


def test_parse_sub_queries_json_array():
    """JSON 数组格式解析。"""
    result = _parse_sub_queries('["问题1", "问题2"]')
    assert result == ["问题1", "问题2"]


def test_parse_sub_queries_numbered_list():
    """编号列表格式解析。"""
    result = _parse_sub_queries("1. 问题1\n2. 问题2\n3. 问题3")
    assert len(result) == 3
    assert "问题1" in result[0]


def test_parse_sub_queries_empty_response():
    """空响应返回空列表。"""
    assert _parse_sub_queries("") == []
    assert _parse_sub_queries(None) == []


# ============================================================
# transform_query 组合入口测试
# ============================================================

def test_transform_query_llm_none_skips_all():
    """LLM 为 None 时跳过所有变换。"""
    result = transform_query("查询", llm=None, enable_hyde=True, enable_decompose=True)

    assert result.original == "查询"
    assert result.final_query == "查询"
    assert result.sub_queries == ["查询"]
    assert result.used_hyde is False
    assert result.used_decompose is False


def test_transform_query_both_disabled():
    """HyDE 和分解都禁用时返回原 query。"""
    llm = MagicMock()
    result = transform_query("查询", llm=llm, enable_hyde=False, enable_decompose=False)

    assert result.final_query == "查询"
    assert result.sub_queries == ["查询"]
    assert result.used_hyde is False
    assert result.used_decompose is False


def test_transform_query_hyde_only_no_decompose():
    """只启用 HyDE，子问题未分解时使用 HyDE 结果。"""
    llm = MagicMock()
    # decompose 返回单元素（不分解），hyde 返回假设答案（长度需 ≥10）
    llm.chat.side_effect = [
        '["单一查询"]',  # decompose 调用
        '根据殡葬管理条例规定节地生态安葬是指骨灰海葬树葬等形式',  # hyde 调用
    ]

    # query 长度 >=18 且含复合信号触发 decompose，
    # 但 decompose 返回单元素（不分解），所以会走 HyDE
    result = transform_query("请详细说明海葬和树葬这两种安葬方式之间的主要区别是什么", llm=llm, enable_hyde=True, enable_decompose=True)

    assert result.used_hyde is True
    assert result.used_decompose is False
    assert result.final_query == "根据殡葬管理条例规定节地生态安葬是指骨灰海葬树葬等形式"
    assert result.sub_queries == ["根据殡葬管理条例规定节地生态安葬是指骨灰海葬树葬等形式"]


def test_transform_query_decompose_skips_hyde():
    """子问题分解时跳过 HyDE（避免多次 LLM 调用）。"""
    llm = MagicMock()
    llm.chat.return_value = '["子问题1", "子问题2", "子问题3"]'

    # query 长度 >=18 且含复合信号触发分解，分解返回多元素，跳过 HyDE
    result = transform_query("请对比分析杭州和上海在生态安葬与海葬补贴政策上的差异", llm=llm, enable_hyde=True, enable_decompose=True)

    assert result.used_decompose is True
    assert result.used_hyde is False  # 分解时不做 HyDE
    assert len(result.sub_queries) == 3

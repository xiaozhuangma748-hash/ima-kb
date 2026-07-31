"""Agentic RAG 反思模块单元测试。

验证：
1. should_retry 判断逻辑（幻觉/无法回答/答案过短 → True）
2. reflect_and_rewrite_query 调用 LLM 改写 query
3. LLM 失败时回退原 query
"""
from __future__ import annotations

from pathlib import Path
import sys
from unittest.mock import MagicMock

import pytest

PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


# ============================================================
# should_retry 判断测试
# ============================================================

def test_should_retry_true_when_hallucination_detected():
    """Self-RAG 检测到幻觉时应该重试。"""
    from core.qa.agentic_reflect import should_retry
    verify_result = MagicMock()
    verify_result.has_hallucination = True
    assert should_retry(
        question="问题",
        answer="答案内容",
        verify_result=verify_result,
        max_score=0.8,
        round_num=1,
        max_rounds=2,
    ) is True


def test_should_retry_true_when_answer_says_cannot_answer_but_has_results():
    """答案含"无法回答"但检索结果有相关内容时应该重试。"""
    from core.qa.agentic_reflect import should_retry
    assert should_retry(
        question="问题",
        answer="根据现有资料无法回答该问题",
        verify_result=None,
        max_score=0.5,  # 高于拒答阈值，说明有相关资料
        round_num=1,
        max_rounds=2,
    ) is True


def test_should_retry_false_when_answer_good():
    """答案正常且无幻觉时不重试。"""
    from core.qa.agentic_reflect import should_retry
    verify_result = MagicMock()
    verify_result.has_hallucination = False
    assert should_retry(
        question="问题",
        answer="海葬是骨灰撒入海洋 [1]。",
        verify_result=verify_result,
        max_score=0.8,
        round_num=1,
        max_rounds=2,
    ) is False


def test_should_retry_false_when_max_rounds_reached():
    """达到最大轮次时不重试。"""
    from core.qa.agentic_reflect import should_retry
    verify_result = MagicMock()
    verify_result.has_hallucination = True
    assert should_retry(
        question="问题",
        answer="答案",
        verify_result=verify_result,
        max_score=0.8,
        round_num=2,  # 已是第 2 轮
        max_rounds=2,
    ) is False


def test_should_retry_false_when_low_confidence_no_results():
    """低置信度且无相关资料时不重试（重试也没用）。"""
    from core.qa.agentic_reflect import should_retry
    assert should_retry(
        question="问题",
        answer="根据现有资料无法回答该问题",
        verify_result=None,
        max_score=0.05,  # 低于拒答阈值，说明真的没相关资料
        round_num=1,
        max_rounds=2,
    ) is False


# ============================================================
# reflect_and_rewrite_query 测试
# ============================================================

def test_reflect_and_rewrite_query_calls_llm_and_returns_new_query():
    """反思模块应调用 LLM 改写 query。"""
    from core.qa.agentic_reflect import reflect_and_rewrite_query
    mock_llm = MagicMock()
    mock_llm.chat.return_value = "海葬 申请流程 材料"
    new_query = reflect_and_rewrite_query(
        question="海葬怎么办理？",
        previous_answer="根据现有资料无法回答该问题",
        issues="答案无法回答用户问题，可能需要更具体的检索词",
        llm=mock_llm,
    )
    assert new_query == "海葬 申请流程 材料"
    assert mock_llm.chat.call_count == 1


def test_reflect_and_rewrite_query_llm_failure_returns_original():
    """LLM 调用失败时返回原 query（不破坏流程）。"""
    from core.qa.agentic_reflect import reflect_and_rewrite_query
    mock_llm = MagicMock()
    mock_llm.chat.side_effect = Exception("API 挂了")
    new_query = reflect_and_rewrite_query(
        question="海葬怎么办理？",
        previous_answer="无法回答",
        issues="需要更具体的检索词",
        llm=mock_llm,
    )
    assert new_query == "海葬怎么办理？"


def test_reflect_and_rewrite_query_empty_response_returns_original():
    """LLM 返回空字符串时返回原 query。"""
    from core.qa.agentic_reflect import reflect_and_rewrite_query
    mock_llm = MagicMock()
    mock_llm.chat.return_value = ""
    new_query = reflect_and_rewrite_query(
        question="海葬怎么办理？",
        previous_answer="无法回答",
        issues="需要更具体的检索词",
        llm=mock_llm,
    )
    assert new_query == "海葬怎么办理？"


def test_reflect_and_rewrite_query_strips_quotes():
    """LLM 返回带引号的 query 时去掉引号。"""
    from core.qa.agentic_reflect import reflect_and_rewrite_query
    mock_llm = MagicMock()
    mock_llm.chat.return_value = '"海葬 申请流程"'
    new_query = reflect_and_rewrite_query(
        question="海葬怎么办理？",
        previous_answer="无法回答",
        issues="需要更具体的检索词",
        llm=mock_llm,
    )
    assert new_query == "海葬 申请流程"

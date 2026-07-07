"""LLM 降级文案统一测试。"""
import pytest
from core.llm.degrade import get_llm_degrade_message
from core.llm.client import LLMError


def test_degrade_with_sources():
    """有检索资料时的降级文案。"""
    msg = get_llm_degrade_message(has_sources=True, source_count=3)
    assert "LLM 不可用" in msg
    assert "3" in msg
    assert "检索" in msg


def test_degrade_without_sources():
    """无检索资料时的降级文案。"""
    msg = get_llm_degrade_message(has_sources=False)
    assert "LLM 不可用" in msg
    assert "未检索到" in msg


def test_degrade_with_error():
    """带异常的降级文案。"""
    err = LLMError("连接超时")
    msg = get_llm_degrade_message(error=err, has_sources=False)
    assert "LLMError" in msg
    assert "连接超时" in msg


def test_degrade_with_error_and_sources():
    """带异常且有资料的降级文案。"""
    err = LLMError("API 错误")
    msg = get_llm_degrade_message(error=err, has_sources=True, source_count=2)
    assert "LLMError" in msg
    assert "API 错误" in msg
    assert "2" in msg


def test_degrade_no_error_no_sources():
    """无异常无资料的降级文案。"""
    msg = get_llm_degrade_message()
    assert "LLM 不可用" in msg
    assert "未检索到" in msg
    # 无异常时不应该有括号
    assert "（" not in msg


def test_degrade_source_count_zero_treated_as_no_sources():
    """source_count=0 时按无资料处理。"""
    msg = get_llm_degrade_message(has_sources=True, source_count=0)
    assert "未检索到" in msg

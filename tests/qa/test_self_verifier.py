"""Self-RAG 答案验证模块单元测试。

验证模块的核心功能：解析 LLM 返回的验证结果、标注幻觉句子、
构造验证后的答案。不真正调用 LLM，用 mock 测试逻辑。
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


def test_parse_verify_response_all_grounded():
    """所有句子都有依据时返回 has_hallucination=False。"""
    from core.qa.self_verifier import parse_verify_response
    raw = '{"sentences": [{"text": "海葬是骨灰撒入海洋", "grounded": true, "citation": 1}], "has_hallucination": false}'
    result = parse_verify_response(raw)
    assert result["has_hallucination"] is False
    assert len(result["sentences"]) == 1
    assert result["sentences"][0]["grounded"] is True
    assert result["sentences"][0]["citation"] == 1


def test_parse_verify_response_has_hallucination():
    """有幻觉句子时返回 has_hallucination=True。"""
    from core.qa.self_verifier import parse_verify_response
    raw = '{"sentences": [{"text": "海葬免费", "grounded": false, "citation": null}, {"text": "海葬需申请", "grounded": true, "citation": 2}], "has_hallucination": true}'
    result = parse_verify_response(raw)
    assert result["has_hallucination"] is True
    assert len(result["sentences"]) == 2
    assert result["sentences"][0]["grounded"] is False
    assert result["sentences"][1]["grounded"] is True


def test_parse_verify_response_with_markdown_fence():
    """解析带 ```json 代码块的返回。"""
    from core.qa.self_verifier import parse_verify_response
    raw = '```json\n{"sentences": [], "has_hallucination": false}\n```'
    result = parse_verify_response(raw)
    assert result["has_hallucination"] is False


def test_parse_verify_response_invalid_returns_unverified():
    """无法解析时返回 None 表示跳过验证（不破坏原答案）。"""
    from core.qa.self_verifier import parse_verify_response
    result = parse_verify_response("验证失败")
    assert result is None


def test_mark_ungrounded_sentences():
    """给幻觉句子加 ⚠️ 标注。"""
    from core.qa.self_verifier import mark_ungrounded_sentences
    sentences = [
        {"text": "海葬是骨灰撒入海洋", "grounded": True, "citation": 1},
        {"text": "海葬完全免费", "grounded": False, "citation": None},
        {"text": "需提前申请", "grounded": True, "citation": 2},
    ]
    result = mark_ungrounded_sentences(sentences)
    assert "海葬是骨灰撒入海洋" in result
    assert "⚠️ 未经资料支持" in result
    assert "海葬完全免费" in result
    # 有依据的句子不应有标注
    assert "海葬是骨灰撒入海洋 ⚠️" not in result


def test_build_verify_messages_contains_required_fields():
    """验证 prompt 应包含问题、答案、参考资料。"""
    from core.qa.self_verifier import build_verify_messages
    messages = build_verify_messages(
        question="什么是海葬？",
        answer="海葬是把骨灰撒到海里 [1]。海葬完全免费。",
        snippets=["海葬是指将骨灰撒入海洋的生态安葬方式"],
    )
    assert len(messages) == 2
    assert messages[0]["role"] == "system"
    assert messages[1]["role"] == "user"
    user_content = messages[1]["content"]
    assert "海葬" in user_content
    assert "参考资料" in user_content
    assert "JSON" in user_content


def test_self_verifier_no_hallucination_returns_original():
    """无幻觉时返回原答案，不修改。"""
    from core.qa.self_verifier import SelfVerifier, VerificationResult

    mock_llm = MagicMock()
    # LLM 返回：所有句子都有依据
    mock_llm.chat.return_value = '{"sentences": [{"text": "海葬是骨灰撒入海洋", "grounded": true, "citation": 1}], "has_hallucination": false}'
    verifier = SelfVerifier(llm=mock_llm)

    result = verifier.verify(
        question="什么是海葬？",
        answer="海葬是把骨灰撒到海里 [1]。",
        snippets=["海葬是指将骨灰撒入海洋的生态安葬方式"],
    )
    assert isinstance(result, VerificationResult)
    assert result.has_hallucination is False
    assert result.verified_answer == "海葬是把骨灰撒到海里 [1]。"
    assert result.needs_regenerate is False


def test_self_verifier_has_hallucination_marks_sentences():
    """有幻觉时标注幻觉句子，needs_regenerate=False（标注而非重生成）。"""
    from core.qa.self_verifier import SelfVerifier

    mock_llm = MagicMock()
    mock_llm.chat.return_value = '{"sentences": [{"text": "海葬是骨灰撒入海洋", "grounded": true, "citation": 1}, {"text": "海葬完全免费", "grounded": false, "citation": null}], "has_hallucination": true}'
    verifier = SelfVerifier(llm=mock_llm)

    result = verifier.verify(
        question="什么是海葬？",
        answer="海葬是骨灰撒入海洋 [1]。海葬完全免费。",
        snippets=["海葬是指将骨灰撒入海洋的生态安葬方式"],
    )
    assert result.has_hallucination is True
    assert "⚠️ 未经资料支持" in result.verified_answer
    assert "海葬完全免费" in result.verified_answer
    # 默认模式只标注不重生成
    assert result.needs_regenerate is False


def test_self_verifier_llm_failure_returns_none():
    """LLM 调用失败时返回 None（跳过验证，保留原答案）。"""
    from core.qa.self_verifier import SelfVerifier

    mock_llm = MagicMock()
    mock_llm.chat.side_effect = Exception("API 挂了")
    verifier = SelfVerifier(llm=mock_llm)

    result = verifier.verify(
        question="什么是海葬？",
        answer="海葬是骨灰撒到海里 [1]。",
        snippets=["海葬是指将骨灰撒入海洋"],
    )
    assert result is None


def test_self_verifier_disabled_returns_none():
    """enable=False 时直接返回 None。"""
    from core.qa.self_verifier import SelfVerifier

    mock_llm = MagicMock()
    verifier = SelfVerifier(llm=mock_llm, enabled=False)
    result = verifier.verify("问题", "答案", ["资料"])
    assert result is None
    mock_llm.chat.assert_not_called()

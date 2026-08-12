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


def test_mark_ungrounded_sentences_preserves_separators():
    """Bug 8 修复验证：句子之间应有分隔符，避免粘连。

    场景：LLM 切分句子时丢失原文标点，拼接后 [1]海葬 会连在一起破坏引用语义。
    """
    from core.qa.self_verifier import mark_ungrounded_sentences
    sentences = [
        {"text": "海葬是骨灰撒入海洋 [1]", "grounded": True, "citation": 1},
        {"text": "海葬完全免费", "grounded": False, "citation": None},
    ]
    result = mark_ungrounded_sentences(sentences)
    # 两句之间应有分隔符（空格或换行），不能直接粘连
    assert "[1]海葬" not in result, \
        f"句子粘连破坏引用语义: {result}"
    assert "[1] 海葬" in result or "[1]\n海葬" in result or "[1]\n\n海葬" in result, \
        f"句子间应有分隔符: {result}"


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


def test_self_verifier_empty_sentences_with_hallucination_keeps_original():
    """Bug 2 修复验证：LLM 返回空 sentences + has_hallucination=True 时，
    不应把答案替换为空串，而应保留原答案。

    场景：LLM 异常返回 {"sentences": [], "has_hallucination": true}，
    mark_ungrounded_sentences([]) 返回 ""，若直接替换会导致用户拿到空答案。
    """
    from core.qa.self_verifier import SelfVerifier

    mock_llm = MagicMock()
    mock_llm.chat.return_value = '{"sentences": [], "has_hallucination": true}'
    verifier = SelfVerifier(llm=mock_llm)
    result = verifier.verify(
        question="什么是海葬？",
        answer="海葬是骨灰撒入海洋 [1]。",
        snippets=["海葬是指将骨灰撒入海洋的生态安葬方式"]
    )
    # 不应返回空答案，应保留原答案
    assert result is not None
    assert result.verified_answer == "海葬是骨灰撒入海洋 [1]。"
    # has_hallucination 应为 True（LLM 说了有幻觉），但没有可标注的句子
    assert result.has_hallucination is True
    assert result.hallucinated_sentences == []


def test_parse_verify_response_string_boolean_false():
    """Bug 7 修复验证：LLM 返回字符串型 "false" 时应正确转为 False。

    场景：LLM 返回 {"has_hallucination": "false"}（字符串而非布尔），
    bool("false") 为 True（非空字符串均为真），导致无幻觉被误判为有幻觉。
    """
    from core.qa.self_verifier import parse_verify_response
    raw = '{"sentences": [{"text": "海葬是骨灰撒入海洋", "grounded": true, "citation": 1}], "has_hallucination": "false"}'
    result = parse_verify_response(raw)
    assert result is not None
    assert result["has_hallucination"] is False, \
        "字符串 'false' 应转为布尔 False，而非 bool('false')=True"


def test_parse_verify_response_string_boolean_true():
    """Bug 7 修复验证：LLM 返回字符串型 "true" 时应正确转为 True。"""
    from core.qa.self_verifier import parse_verify_response
    raw = '{"sentences": [{"text": "海葬完全免费", "grounded": false, "citation": null}], "has_hallucination": "true"}'
    result = parse_verify_response(raw)
    assert result is not None
    assert result["has_hallucination"] is True


def test_parse_verify_response_truncated_recovers_complete_sentences():
    """截断恢复：LLM 返回被 max_tokens 截断时，应提取已完整的 sentence 项。

    场景：实测 q003 的 LLM 返回在 char 842 处被截断，最后一项 text 字段
    没闭合引号，整体 JSON 解析失败。本测试验证能从截断 JSON 中救回前 8 项。
    """
    from core.qa.self_verifier import parse_verify_response
    # 模拟真实截断：第 9 项 text 字段被截断，没有闭合引号和 }
    raw = '''{
  "sentences": [
    {"text": "根据现有资料，政策包括以下项目", "grounded": true, "citation": 1},
    {"text": "1. 遗体接运", "grounded": true, "citation": 1},
    {"text": "2. 遗体存放", "grounded": true, "citation": 1},
    {"text": "3. 遗体火化", "grounded": true, "citation": 1},
    {"text": "5. 骨灰盒", "grounded": true, "citation": 3},
    {"text": "海葬完全免费", "grounded": false, "citation": null},
    {"text": "6. 骨灰安葬", "grounded": true, "citation": 3},
    {"text": "* 殡仪馆内骨灰寄存费", "grounded": true, "citation": 3},
    {"text": "* 骨灰安葬形式符合节地生态安葬条件的，按《关于对杭州市区实施'''
    result = parse_verify_response(raw)
    # 应至少恢复 8 项完整 sentence
    assert result is not None, "截断的 JSON 应能恢复出已完整的 sentence 项"
    assert len(result["sentences"]) == 8
    # 第 6 项是幻觉，has_hallucination 应为 True
    assert result["has_hallucination"] is True
    # 第 6 项的 grounded 应为 False
    assert any(s["grounded"] is False for s in result["sentences"])
    # citation 字段类型正确
    assert result["sentences"][0]["citation"] == 1
    assert result["sentences"][5]["citation"] is None


def test_parse_verify_response_truncated_no_complete_sentences_returns_none():
    """截断恢复：如果连 1 个完整 sentence 都没有，返回 None。"""
    from core.qa.self_verifier import parse_verify_response
    raw = '{"sentences": [{"text": "被截断的句子没有闭合'
    result = parse_verify_response(raw)
    assert result is None


def test_parse_verify_response_truncated_with_escaped_quote():
    """截断恢复：text 字段含转义引号时应正确解析。"""
    from core.qa.self_verifier import parse_verify_response
    # text 字段含 \" 转义引号
    raw = '''{
  "sentences": [
    {"text": "他说\\"你好\\"", "grounded": true, "citation": 1},
    {"text": "截断的'''
    result = parse_verify_response(raw)
    assert result is not None
    assert len(result["sentences"]) == 1
    assert result["sentences"][0]["text"] == '他说"你好"'

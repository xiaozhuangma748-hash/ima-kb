"""端到端回答评测脚本的单元测试。

验证评测脚本的核心函数：评分解析、报告聚合、失败案例识别。
不真正调用 LLM，用 mock 数据测试逻辑。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


def test_parse_judge_response_valid_json():
    """解析 LLM 裁判返回的 JSON 评分。"""
    from scripts.eval_answer import parse_judge_response
    raw = '{"score": 5, "has_hallucination": false, "has_citation": true, "reason": "答案准确"}'
    result = parse_judge_response(raw)
    assert result["score"] == 5
    assert result["has_hallucination"] is False
    assert result["has_citation"] is True
    assert "准确" in result["reason"]


def test_parse_judge_response_with_markdown_fence():
    """解析带 ```json 代码块的裁判返回。"""
    from scripts.eval_answer import parse_judge_response
    raw = '```json\n{"score": 3, "has_hallucination": true, "has_citation": false, "reason": "有幻觉"}\n```'
    result = parse_judge_response(raw)
    assert result["score"] == 3
    assert result["has_hallucination"] is True


def test_parse_judge_response_invalid_returns_zero():
    """无法解析的返回给默认 0 分。"""
    from scripts.eval_answer import parse_judge_response
    result = parse_judge_response("裁判罢工了")
    assert result["score"] == 0
    assert result["has_hallucination"] is True  # 解析失败视为有幻觉
    assert result["has_citation"] is False


def test_aggregate_results_overall():
    """聚合评测结果计算总体指标。"""
    from scripts.eval_answer import aggregate_results
    details = [
        {"score": 5, "has_hallucination": False, "has_citation": True, "category": "policy"},
        {"score": 4, "has_hallucination": False, "has_citation": True, "category": "policy"},
        {"score": 2, "has_hallucination": True, "has_citation": False, "category": "negative"},
        {"score": 0, "has_hallucination": True, "has_citation": False, "category": "negative"},
    ]
    overall = aggregate_results(details)
    assert overall["total"] == 4
    assert overall["avg_score"] == 2.75
    assert overall["hallucination_rate"] == 0.5
    assert overall["citation_rate"] == 0.5
    assert overall["accuracy_rate"] == 0.5  # score >= 4 算正确


def test_aggregate_results_by_category():
    """按类别聚合评测结果。"""
    from scripts.eval_answer import aggregate_results
    details = [
        {"score": 5, "has_hallucination": False, "has_citation": True, "category": "policy"},
        {"score": 4, "has_hallucination": False, "has_citation": True, "category": "policy"},
        {"score": 1, "has_hallucination": True, "has_citation": False, "category": "negative"},
    ]
    result = aggregate_results(details)
    assert "policy" in result["by_category"]
    assert result["by_category"]["policy"]["avg_score"] == 4.5
    assert result["by_category"]["policy"]["accuracy_rate"] == 1.0
    assert "negative" in result["by_category"]
    assert result["by_category"]["negative"]["accuracy_rate"] == 0.0


def test_judge_prompt_contains_required_fields():
    """裁判 prompt 应包含问题、参考答案、实际答案、参考资料。"""
    from scripts.eval_answer import build_judge_messages
    messages = build_judge_messages(
        question="什么是海葬？",
        reference_answer="海葬是将骨灰撒入海洋的安葬方式",
        actual_answer="海葬是把骨灰撒到海里 [1]",
        reference_snippets=["海葬是指将骨灰撒入海洋的生态安葬方式"],
    )
    assert len(messages) == 2
    assert messages[0]["role"] == "system"
    assert messages[1]["role"] == "user"
    user_content = messages[1]["content"]
    assert "海葬" in user_content
    assert "参考答案" in user_content
    assert "实际答案" in user_content
    assert "参考资料" in user_content
    assert "JSON" in user_content  # 要求 LLM 返回 JSON

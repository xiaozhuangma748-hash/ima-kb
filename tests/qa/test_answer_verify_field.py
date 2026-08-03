"""Answer dataclass 的 _verify_result 字段化测试。

Bug 4 修复验证：_verify_result 应作为 Answer dataclass 的正式字段，
所有早退路径都应正确赋值，避免 AgenticRAGChain 拿到 None。
"""
from __future__ import annotations

from pathlib import Path
import sys
from unittest.mock import MagicMock

import pytest

PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


def test_answer_dataclass_has_verify_result_field():
    """Answer dataclass 应声明 verify_result 字段。"""
    from core.qa.chain import Answer
    import dataclasses
    field_names = {f.name for f in dataclasses.fields(Answer)}
    assert "verify_result" in field_names, \
        "Answer dataclass 应声明 verify_result 字段（Bug 4 修复）"


def test_answer_default_verify_result_is_none():
    """Answer 默认 verify_result 应为 None。"""
    from core.qa.chain import Answer
    a = Answer(question="q", content="c")
    assert a.verify_result is None


def test_answer_low_confidence_path_has_verify_result(tmp_path):
    """低置信度硬拒答路径返回的 Answer 应有 verify_result=None。"""
    from core.qa.chain import RAGChain
    from core.storage import Storage
    import config

    storage = Storage(storage_path=tmp_path)
    original = config.settings.parent_window
    config.settings.parent_window = 0
    try:
        chain = RAGChain(storage=storage)
    finally:
        config.settings.parent_window = original

    # Mock 检索返回低分结果（低于 reject_confidence_threshold=0.15）
    low_score_result = MagicMock()
    low_score_result.content = "无关内容"
    low_score_result.score = 0.05
    low_score_result.chunk_id = "c1"
    low_score_result.doc_id = "d1"
    low_score_result.doc_title = "文档"
    low_score_result.source = "bm25"
    low_score_result.format_tag = ""
    chain.hybrid.search = MagicMock(return_value=[low_score_result])
    chain.reranker = None
    chain._answer_cache = None
    chain.self_verifier = None

    answer = chain.ask("测试问题")
    # 低置信度早退路径也应正确设置 verify_result
    assert hasattr(answer, "verify_result")
    assert answer.verify_result is None


def test_answer_no_results_path_has_verify_result(tmp_path):
    """无检索结果路径返回的 Answer 应有 verify_result=None。"""
    from core.qa.chain import RAGChain
    from core.storage import Storage
    import config

    storage = Storage(storage_path=tmp_path)
    original = config.settings.parent_window
    config.settings.parent_window = 0
    try:
        chain = RAGChain(storage=storage)
    finally:
        config.settings.parent_window = original

    chain.hybrid.search = MagicMock(return_value=[])
    chain.reranker = None
    chain._answer_cache = None
    chain.self_verifier = None

    answer = chain.ask("测试问题")
    assert hasattr(answer, "verify_result")
    assert answer.verify_result is None

"""AgenticRAGChain 单元测试。

验证：
1. enable_agentic_rag=False 时退化为普通 RAGChain（单轮）
2. enable_agentic_rag=True 时多轮检索
3. 最大轮次保护
4. 低置信度不重试
"""
from __future__ import annotations

from pathlib import Path
import sys
from unittest.mock import MagicMock, patch

import pytest

PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


def _make_mock_result(content="资料内容", score=0.5, chunk_id="c1", doc_id="d1"):
    """构造 mock HybridResult。"""
    r = MagicMock()
    r.content = content
    r.score = score
    r.chunk_id = chunk_id
    r.doc_id = doc_id
    r.doc_title = "文档标题"
    r.source = "bm25"
    r.format_tag = ""
    r.paragraph_num = 1
    return r


def _make_mock_verify_result(has_hallucination=False):
    """构造 mock VerificationResult。"""
    v = MagicMock()
    v.has_hallucination = has_hallucination
    v.verified_answer = "验证后的答案 [1]"
    v.needs_regenerate = False
    v.hallucinated_sentences = [] if not has_hallucination else ["幻觉句子"]
    return v


def test_agentic_chain_disabled_degrades_to_single_round(tmp_path):
    """enable_agentic_rag=False 时只检索一次。"""
    from core.qa.agentic_chain import AgenticRAGChain
    from core.storage import Storage

    storage = Storage(storage_path=tmp_path)
    import config
    original = config.settings.parent_window
    config.settings.parent_window = 0
    try:
        chain = AgenticRAGChain(storage=storage, enable_agentic=False)
    finally:
        config.settings.parent_window = original

    # Mock 父类 ask
    mock_answer = MagicMock()
    mock_answer.content = "测试答案 [1]"
    mock_answer.low_confidence = False
    chain.chain.ask = MagicMock(return_value=mock_answer)

    result = chain.ask("测试问题")

    # 只调用一次父类 ask
    assert chain.chain.ask.call_count == 1
    assert result.content == "测试答案 [1]"


def test_agentic_chain_enabled_retries_on_hallucination(tmp_path):
    """检测到幻觉时重检索一次。"""
    from core.qa.agentic_chain import AgenticRAGChain
    from core.storage import Storage

    storage = Storage(storage_path=tmp_path)
    import config
    original = config.settings.parent_window
    config.settings.parent_window = 0
    try:
        chain = AgenticRAGChain(storage=storage, enable_agentic=True, max_rounds=2)
    finally:
        config.settings.parent_window = original

    # 第一轮：检测到幻觉；第二轮：正常答案
    answer1 = MagicMock()
    answer1.content = "幻觉答案"
    answer1.low_confidence = False
    answer1.confidence = 0.8
    answer1.retrieved = [_make_mock_result(score=0.8)]
    answer1.verify_result = _make_mock_verify_result(has_hallucination=True)

    answer2 = MagicMock()
    answer2.content = "正确答案 [1]"
    answer2.low_confidence = False
    answer2.confidence = 0.9
    answer2.retrieved = [_make_mock_result(score=0.9)]
    answer2.verify_result = _make_mock_verify_result(has_hallucination=False)

    chain.chain.ask = MagicMock(side_effect=[answer1, answer2])
    # Mock 反思
    chain._reflect = MagicMock(return_value="改写后的 query")

    result = chain.ask("测试问题")

    # 调用了 2 次父类 ask
    assert chain.chain.ask.call_count == 2
    assert result.content == "正确答案 [1]"


def test_agentic_chain_respects_max_rounds(tmp_path):
    """达到最大轮次后停止。"""
    from core.qa.agentic_chain import AgenticRAGChain
    from core.storage import Storage

    storage = Storage(storage_path=tmp_path)
    import config
    original = config.settings.parent_window
    config.settings.parent_window = 0
    try:
        chain = AgenticRAGChain(storage=storage, enable_agentic=True, max_rounds=2)
    finally:
        config.settings.parent_window = original

    # 每轮都有幻觉
    bad_answer = MagicMock()
    bad_answer.content = "幻觉答案"
    bad_answer.low_confidence = False
    bad_answer.confidence = 0.8
    bad_answer.retrieved = [_make_mock_result(score=0.8)]
    bad_answer.verify_result = _make_mock_verify_result(has_hallucination=True)

    chain.chain.ask = MagicMock(return_value=bad_answer)
    chain._reflect = MagicMock(return_value="改写后的 query")

    result = chain.ask("测试问题")

    # 最多调用 max_rounds 次
    assert chain.chain.ask.call_count == 2


def test_agentic_chain_no_retry_when_low_confidence(tmp_path):
    """低置信度无资料时不重试。"""
    from core.qa.agentic_chain import AgenticRAGChain
    from core.storage import Storage

    storage = Storage(storage_path=tmp_path)
    import config
    original = config.settings.parent_window
    config.settings.parent_window = 0
    try:
        chain = AgenticRAGChain(storage=storage, enable_agentic=True, max_rounds=2)
    finally:
        config.settings.parent_window = original

    # 低置信度答案（无法回答 + 低分）
    bad_answer = MagicMock()
    bad_answer.content = "根据现有资料无法回答该问题"
    bad_answer.low_confidence = True
    bad_answer.confidence = 0.05
    bad_answer.retrieved = [_make_mock_result(score=0.05)]
    bad_answer.verify_result = None

    chain.chain.ask = MagicMock(return_value=bad_answer)

    result = chain.ask("测试问题")

    # 只调用一次（低置信度不重试）
    assert chain.chain.ask.call_count == 1


def test_agentic_chain_retries_when_cannot_answer_but_has_results(tmp_path):
    """答案含'无法回答'但有相关资料时重试。"""
    from core.qa.agentic_chain import AgenticRAGChain
    from core.storage import Storage

    storage = Storage(storage_path=tmp_path)
    import config
    original = config.settings.parent_window
    config.settings.parent_window = 0
    try:
        chain = AgenticRAGChain(storage=storage, enable_agentic=True, max_rounds=2)
    finally:
        config.settings.parent_window = original

    # 第一轮：无法回答但有资料；第二轮：正常答案
    answer1 = MagicMock()
    answer1.content = "根据现有资料无法回答该问题"
    answer1.low_confidence = False
    answer1.confidence = 0.5
    answer1.retrieved = [_make_mock_result(score=0.5)]
    answer1.verify_result = None

    answer2 = MagicMock()
    answer2.content = "正确答案 [1]"
    answer2.low_confidence = False
    answer2.confidence = 0.9
    answer2.retrieved = [_make_mock_result(score=0.9)]
    answer2.verify_result = None

    chain.chain.ask = MagicMock(side_effect=[answer1, answer2])
    chain._reflect = MagicMock(return_value="改写后的 query")

    result = chain.ask("测试问题")

    assert chain.chain.ask.call_count == 2
    assert result.content == "正确答案 [1]"


def test_agentic_chain_restores_original_question(tmp_path):
    """多轮检索后 Answer.question 应为用户原始问题，不是改写后的 query。"""
    from core.qa.agentic_chain import AgenticRAGChain
    from core.storage import Storage

    storage = Storage(storage_path=tmp_path)
    import config
    original = config.settings.parent_window
    config.settings.parent_window = 0
    try:
        chain = AgenticRAGChain(storage=storage, enable_agentic=True, max_rounds=2)
    finally:
        config.settings.parent_window = original

    # 第一轮幻觉，第二轮正常
    answer1 = MagicMock()
    answer1.content = "幻觉答案"
    answer1.low_confidence = False
    answer1.confidence = 0.8
    answer1.retrieved = [_make_mock_result(score=0.8)]
    answer1.verify_result = _make_mock_verify_result(has_hallucination=True)
    answer1.question = "改写后的 query"  # 父类用改写后的 query

    answer2 = MagicMock()
    answer2.content = "正确答案 [1]"
    answer2.low_confidence = False
    answer2.confidence = 0.9
    answer2.retrieved = [_make_mock_result(score=0.9)]
    answer2.verify_result = _make_mock_verify_result(has_hallucination=False)
    answer2.question = "改写后的 query 2"

    chain.chain.ask = MagicMock(side_effect=[answer1, answer2])
    chain._reflect = MagicMock(return_value="改写后的 query")

    result = chain.ask("用户原始问题")

    # 返回的 Answer.question 应恢复为用户原始问题
    assert result.question == "用户原始问题"


def test_agentic_chain_bypasses_answer_cache(tmp_path):
    """Bug 1 修复验证：Agentic 多轮检索时不应被答案缓存命中绕过。

    场景：第一轮 ask 产生幻觉被缓存；第二次相同问题不应直接返回缓存答案，
    而应走完整的 Agentic 多轮流程（chain.ask 应使用 use_cache=False）。
    """
    from core.qa.agentic_chain import AgenticRAGChain
    from core.storage import Storage

    storage = Storage(storage_path=tmp_path)
    import config
    original = config.settings.parent_window
    config.settings.parent_window = 0
    try:
        chain = AgenticRAGChain(storage=storage, enable_agentic=True, max_rounds=2)
    finally:
        config.settings.parent_window = original

    # Mock 父类 ask，捕获 use_cache 参数
    answer1 = MagicMock()
    answer1.content = "幻觉答案"
    answer1.low_confidence = False
    answer1.confidence = 0.8
    answer1.retrieved = [_make_mock_result(score=0.8)]
    answer1.verify_result = _make_mock_verify_result(has_hallucination=True)

    answer2 = MagicMock()
    answer2.content = "正确答案 [1]"
    answer2.low_confidence = False
    answer2.confidence = 0.9
    answer2.retrieved = [_make_mock_result(score=0.9)]
    answer2.verify_result = _make_mock_verify_result(has_hallucination=False)

    chain.chain.ask = MagicMock(side_effect=[answer1, answer2])
    chain._reflect = MagicMock(return_value="改写后的 query")

    chain.ask("测试问题")

    # 验证每次 chain.ask 调用都传了 use_cache=False
    for call_args in chain.chain.ask.call_args_list:
        assert call_args.kwargs.get("use_cache") is False, \
            "Agentic RAG 调用 chain.ask 时必须传 use_cache=False，避免缓存绕过多轮检索"

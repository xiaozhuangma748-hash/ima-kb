"""低置信度拒答机制测试。

当检索结果 top1 score 低于硬拒答阈值时，RAGChain 应主动返回"无法回答"
而非调用 LLM。这能修复 negative 类（知识库里没有的问题）的误答问题。

注意：项目已有 prompt 提示机制（阈值 0.05，在 prompt 里加"请谨慎回答"），
但 LLM 仍然会生成，可能编造答案。本测试验证新增的"硬拒答"机制：
score < reject_confidence_threshold 时直接返回，不调 LLM。
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


def _make_result(content="资料", score=0.1, chunk_id="c1", doc_id="d1", doc_title="文档"):
    """构造 mock HybridResult。"""
    r = MagicMock()
    r.content = content
    r.score = score
    r.chunk_id = chunk_id
    r.doc_id = doc_id
    r.doc_title = doc_title
    r.source = "bm25"
    r.format_tag = ""
    r.paragraph_num = 1
    return r


def _make_chain(tmp_path):
    """构造轻量 RAGChain（mock 重型组件）。

    返回 (chain, captured_messages) 捕获 LLM 调用。
    """
    from core.qa.chain import RAGChain
    from core.storage import Storage

    storage = Storage(storage_path=tmp_path)
    import config
    original = config.settings.parent_window
    config.settings.parent_window = 0
    try:
        chain = RAGChain(storage=storage)
    finally:
        config.settings.parent_window = original

    captured_messages = []

    def mock_chat(messages, temperature=0.2, **kwargs):
        captured_messages.extend(messages)
        return "不应该被调用 [1]"

    chain.llm.chat = mock_chat
    chain.llm.chat_stream = lambda messages, temperature=0.2, **kwargs: iter(["不应该被调用 [1]"])
    chain.reranker = None
    chain._answer_cache = None
    return chain, captured_messages


def test_low_confidence_triggers_reject(tmp_path):
    """top1 score 低于硬拒答阈值时应返回"无法回答"而非调用 LLM 生成答案。

    关闭 HyDE/分解后，检索阶段不调 LLM，只有最终回答会调 LLM。
    硬拒答应拦截最终回答的 LLM 调用。
    """
    chain, captured = _make_chain(tmp_path)
    low_score_results = [_make_result(score=0.05, content="无关内容")]

    with patch.object(chain.hybrid, "search", return_value=low_score_results):
        answer = chain.ask("杭州冬天平均气温多少？", enable_hyde=False, enable_decompose=False)

    # 关闭 HyDE/分解后不应调用 LLM
    assert len(captured) == 0, "低置信度时应直接拒答，不调用 LLM"
    # 应返回"无法回答"类内容
    assert "无法回答" in answer.content or "资料不足" in answer.content
    assert answer.low_confidence is True


def test_high_confidence_proceeds_to_llm(tmp_path):
    """top1 score 高于硬拒答阈值时应正常调用 LLM 生成答案。"""
    chain, captured = _make_chain(tmp_path)
    high_score_results = [_make_result(score=0.9, content="海葬是骨灰撒入海洋")]
    # 重新设置 mock 让它返回有意义的答案
    def mock_chat(messages, temperature=0.2, **kwargs):
        captured.extend(messages)
        return "海葬是把骨灰撒到海里 [1]"
    chain.llm.chat = mock_chat

    with patch.object(chain.hybrid, "search", return_value=high_score_results):
        answer = chain.ask("什么是海葬？", enable_hyde=False, enable_decompose=False)

    assert len(captured) > 0, "高置信度时应调用 LLM"
    assert "海葬" in answer.content


def test_empty_results_triggers_reject(tmp_path):
    """无检索结果时应返回"无法回答"。"""
    chain, captured = _make_chain(tmp_path)

    with patch.object(chain.hybrid, "search", return_value=[]):
        answer = chain.ask("随便什么问题", enable_hyde=False, enable_decompose=False)

    assert "无法回答" in answer.content or "资料不足" in answer.content
    assert answer.low_confidence is True
    assert len(captured) == 0


def test_reject_threshold_configurable():
    """拒答阈值应可通过 config 配置。"""
    from config import settings
    # 默认阈值（如果已定义）
    threshold = getattr(settings, "reject_confidence_threshold", None)
    if threshold is not None:
        assert 0 < threshold < 1, "阈值应在 0-1 之间"

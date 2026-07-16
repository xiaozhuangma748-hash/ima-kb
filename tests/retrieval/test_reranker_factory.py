"""reranker 工厂函数测试。"""
import pytest
from unittest.mock import MagicMock, patch

from core.retrieval.rerank import create_reranker, Reranker, RerankResult
from core.retrieval.cross_encoder import CrossEncoderReranker


def test_create_reranker_returns_none_when_type_none():
    """settings.reranker_type == 'none' 时返回 None。"""
    with patch("core.retrieval.rerank.settings") as mock_settings:
        mock_settings.reranker_type = "none"
        result = create_reranker(llm=MagicMock())
    assert result is None


def test_create_reranker_returns_cross_encoder_when_available():
    """Cross-Encoder 可用时返回 CrossEncoderReranker 实例。"""
    mock_ce = MagicMock(spec=CrossEncoderReranker)
    mock_ce.is_available.return_value = True

    with patch("core.retrieval.rerank.settings") as mock_settings, \
         patch("core.retrieval.cross_encoder.CrossEncoderReranker") as MockCE:
        mock_settings.reranker_type = "cross_encoder"
        MockCE.return_value = mock_ce
        result = create_reranker(llm=MagicMock())

    assert result is mock_ce


def test_create_reranker_falls_back_to_llm_when_ce_unavailable():
    """Cross-Encoder 加载失败时降级为 LLM Reranker。"""
    mock_ce = MagicMock(spec=CrossEncoderReranker)
    mock_ce.is_available.return_value = False  # Cross-Encoder 不可用

    mock_llm = MagicMock()

    with patch("core.retrieval.rerank.settings") as mock_settings, \
         patch("core.retrieval.cross_encoder.CrossEncoderReranker") as MockCE:
        mock_settings.reranker_type = "cross_encoder"
        MockCE.return_value = mock_ce
        result = create_reranker(llm=mock_llm)

    # 应该返回 LLM Reranker（不是 CrossEncoderReranker）
    assert isinstance(result, Reranker)
    assert result.llm is mock_llm


def test_create_reranker_returns_llm_when_type_llm():
    """settings.reranker_type == 'llm' 时直接返回 LLM Reranker。"""
    mock_llm = MagicMock()
    with patch("core.retrieval.rerank.settings") as mock_settings:
        mock_settings.reranker_type = "llm"
        result = create_reranker(llm=mock_llm)

    assert isinstance(result, Reranker)
    assert result.llm is mock_llm


def test_create_reranker_returns_none_when_all_unavailable():
    """所有 reranker 都不可用时返回 None。"""
    with patch("core.retrieval.rerank.settings") as mock_settings, \
         patch("core.retrieval.cross_encoder.CrossEncoderReranker") as MockCE:
        mock_settings.reranker_type = "cross_encoder"
        mock_ce = MagicMock(spec=CrossEncoderReranker)
        mock_ce.is_available.return_value = False
        MockCE.return_value = mock_ce

        # LLM 也失败
        with patch("core.retrieval.rerank.Reranker", side_effect=Exception("LLM 不可用")):
            result = create_reranker(llm=None)

    assert result is None

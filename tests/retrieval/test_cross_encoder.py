"""Cross-Encoder 重排序器测试。

由于真实 bge-reranker-v2-m3 模型体积较大（1.1B 参数），
测试以 mock 为主，验证：
1. 模型不可用时正确降级
2. 模型可用时正确调用 predict 并排序
3. 异常处理
"""
import pytest
from unittest.mock import MagicMock, patch

from core.retrieval.hybrid import HybridResult
from core.retrieval.cross_encoder import CrossEncoderReranker


def _make_candidate(cid: str, content: str, title: str = "标题") -> HybridResult:
    """构造测试用 HybridResult。"""
    return HybridResult(
        chunk_id=cid, doc_id="d1", score=0.1, source="both",
        content=content, doc_title=title,
    )


def test_cross_encoder_unavailable_falls_back_to_original_order():
    """模型不可用时，保留原顺序且 relevance_score=0。"""
    candidates = [
        _make_candidate("c1", "内容1"),
        _make_candidate("c2", "内容2"),
    ]
    # mock 模型加载失败
    with patch.object(CrossEncoderReranker, "_init", return_value=None):
        reranker = CrossEncoderReranker()
        reranker._available = False  # 显式标记不可用
        results = reranker.rerank("查询", candidates, top_n=2)

    assert len(results) == 2
    assert results[0].chunk_id == "c1"  # 保留原顺序
    assert results[1].chunk_id == "c2"
    assert results[0].relevance_score == 0.0
    assert results[0].reason == "cross-encoder-unavailable"


def test_cross_encoder_empty_candidates():
    """空候选返回空列表。"""
    with patch.object(CrossEncoderReranker, "_init", return_value=None):
        reranker = CrossEncoderReranker()
        reranker._available = True  # 假装可用
        results = reranker.rerank("查询", [], top_n=5)
    assert results == []


def test_cross_encoder_reorders_by_score():
    """模型可用时按 Cross-Encoder 分数降序排列。"""
    candidates = [
        _make_candidate("c1", "骨灰海葬办理流程", "海葬指南"),
        _make_candidate("c2", "骨灰树葬办理流程", "树葬指南"),
        _make_candidate("c3", "退休人员丧葬费", "丧葬费规定"),
    ]
    # mock 模型预测：c2 > c1 > c3
    mock_model = MagicMock()
    mock_model.predict.return_value = [0.5, 2.5, -0.3]  # logit 分数

    with patch.object(CrossEncoderReranker, "_init", return_value=None):
        reranker = CrossEncoderReranker()
        reranker._available = True
        reranker._model = mock_model
        results = reranker.rerank("骨灰海葬", candidates, top_n=3)

    # c2 分数最高（2.5），c1 次之（0.5），c3 最低（-0.3）
    assert results[0].chunk_id == "c2"
    assert results[1].chunk_id == "c1"
    assert results[2].chunk_id == "c3"
    # relevance_score 应在 0-1 之间（sigmoid 归一化）
    assert 0.0 < results[0].relevance_score < 1.0
    assert results[0].relevance_score > results[1].relevance_score
    assert results[1].relevance_score > results[2].relevance_score


def test_cross_encoder_top_n_limit():
    """top_n 限制返回数量。"""
    candidates = [
        _make_candidate(f"c{i}", f"内容{i}") for i in range(5)
    ]
    mock_model = MagicMock()
    mock_model.predict.return_value = [0.1, 0.2, 0.3, 0.4, 0.5]

    with patch.object(CrossEncoderReranker, "_init", return_value=None):
        reranker = CrossEncoderReranker()
        reranker._available = True
        reranker._model = mock_model
        results = reranker.rerank("查询", candidates, top_n=2)

    assert len(results) == 2


def test_cross_encoder_predict_failure_falls_back():
    """模型 predict 抛异常时降级为原顺序。"""
    candidates = [
        _make_candidate("c1", "内容1"),
        _make_candidate("c2", "内容2"),
    ]
    mock_model = MagicMock()
    mock_model.predict.side_effect = RuntimeError("模型推理失败")

    with patch.object(CrossEncoderReranker, "_init", return_value=None):
        reranker = CrossEncoderReranker()
        reranker._available = True
        reranker._model = mock_model
        results = reranker.rerank("查询", candidates, top_n=2)

    # 降级：保留原顺序
    assert results[0].chunk_id == "c1"
    assert results[1].chunk_id == "c2"
    assert results[0].relevance_score == 0.0


def test_cross_encoder_passes_full_content_not_truncated():
    """Cross-Encoder 应接收完整 content（不截断到 200 字符）。"""
    long_content = "骨灰海葬办理流程。" * 50  # 远超 200 字符
    candidates = [_make_candidate("c1", long_content)]
    mock_model = MagicMock()
    mock_model.predict.return_value = [1.0]

    with patch.object(CrossEncoderReranker, "_init", return_value=None):
        reranker = CrossEncoderReranker()
        reranker._available = True
        reranker._model = mock_model
        reranker.rerank("查询", candidates, top_n=1)

    # 验证 predict 接收的 content 是完整的
    assert mock_model.predict.called
    pairs = mock_model.predict.call_args[0][0]
    assert pairs[0][1] == long_content  # 第二个元素是完整 content


def test_cross_encoder_preserves_metadata():
    """重排后应保留 doc_id/source/paragraph_num 等元数据。"""
    candidates = [
        HybridResult(
            chunk_id="c1", doc_id="doc-001", score=0.5, source="both",
            content="内容", doc_title="标题", paragraph_num=7,
        ),
    ]
    mock_model = MagicMock()
    mock_model.predict.return_value = [1.0]

    with patch.object(CrossEncoderReranker, "_init", return_value=None):
        reranker = CrossEncoderReranker()
        reranker._available = True
        reranker._model = mock_model
        results = reranker.rerank("查询", candidates, top_n=1)

    assert results[0].doc_id == "doc-001"
    assert results[0].source == "both"
    assert results[0].paragraph_num == 7

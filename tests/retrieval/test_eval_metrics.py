"""评测脚本指标计算测试。"""
import sys
from pathlib import Path

# 把 scripts 目录加入 path 以便 import eval_retrieval
PROJECT_ROOT = Path(__file__).parent.parent.parent.resolve()
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from eval_retrieval import (
    _is_hit, compute_recall_at_k, compute_mrr, compute_ndcg_at_k,
    load_dataset,
)
from core.retrieval.hybrid import HybridResult


def _make_result(content: str, title: str = "标题") -> HybridResult:
    return HybridResult(
        chunk_id="c1", doc_id="d1", score=0.5, source="both",
        content=content, doc_title=title,
    )


def test_is_hit_by_content_keyword():
    """content 包含关键词即命中。"""
    r = _make_result("骨灰海葬的办理流程")
    assert _is_hit(r, ["海葬", "树葬"], [])


def test_is_hit_by_title_substring():
    """title 包含子串即命中。"""
    r = _make_result("无关内容", title="杭州市节地生态安葬奖补通知")
    assert _is_hit(r, [], ["节地生态安葬", "奖补"])


def test_is_hit_returns_false_when_no_match():
    """完全不匹配返回 False。"""
    r = _make_result("无关内容", title="其他文档")
    assert not _is_hit(r, ["海葬"], ["节地生态"])


def test_is_hit_case_insensitive():
    """匹配大小写不敏感。"""
    r = _make_result("Hello World", title="Test")
    assert _is_hit(r, ["hello"], [])
    assert _is_hit(r, [], ["test"])


def test_recall_at_k_returns_1_when_hit_in_top_k():
    """前 k 条命中返回 1。"""
    results = [
        _make_result("无关", "无关"),
        _make_result("骨灰海葬", "海葬指南"),
        _make_result("树葬", "树葬指南"),
    ]
    assert compute_recall_at_k(results, ["海葬"], [], 5) == 1
    assert compute_recall_at_k(results, ["海葬"], [], 2) == 1
    assert compute_recall_at_k(results, ["海葬"], [], 1) == 0  # 第 1 条没命中


def test_recall_at_k_returns_0_when_no_hit():
    """前 k 条全部未命中返回 0。"""
    results = [_make_result("内容1"), _make_result("内容2")]
    assert compute_recall_at_k(results, ["海葬"], [], 5) == 0


def test_mrr_returns_inverse_of_first_hit_rank():
    """MRR 等于第一个命中结果的排名倒数。"""
    results = [
        _make_result("无关1"),
        _make_result("骨灰海葬"),  # rank=2
        _make_result("无关3"),
    ]
    assert compute_mrr(results, ["海葬"], []) == 0.5  # 1/2


def test_mrr_returns_0_when_no_hit():
    """无命中时 MRR=0。"""
    results = [_make_result("内容1"), _make_result("内容2")]
    assert compute_mrr(results, ["海葬"], []) == 0.0


def test_mrr_returns_1_when_first_hits():
    """第一条命中时 MRR=1。"""
    results = [_make_result("骨灰海葬"), _make_result("内容2")]
    assert compute_mrr(results, ["海葬"], []) == 1.0


def test_ndcg_at_k_returns_high_value_when_hit_at_top():
    """命中靠前时 NDCG 高。"""
    results = [
        _make_result("骨灰海葬"),  # rank=1
        _make_result("无关"),
        _make_result("无关"),
    ]
    ndcg = compute_ndcg_at_k(results, ["海葬"], [], 3)
    # 简化版 DCG：1/2 = 0.5；IDCG：1/2+1/3+1/4 ≈ 1.083
    # 实际值 0.5/1.083 ≈ 0.461，断言 > 0.4 验证"命中靠前时较高"
    assert ndcg > 0.4


def test_ndcg_at_k_returns_0_when_no_hit():
    """无命中时 NDCG=0。"""
    results = [_make_result("内容1"), _make_result("内容2")]
    assert compute_ndcg_at_k(results, ["海葬"], [], 5) == 0.0


def test_load_dataset_returns_questions_list():
    """加载评测集返回问题列表。"""
    dataset_path = PROJECT_ROOT / "tests/eval/golden_dataset.json"
    if not dataset_path.exists():
        import pytest
        pytest.skip("评测集不存在")
    questions = load_dataset(dataset_path)
    assert isinstance(questions, list)
    assert len(questions) >= 30
    # 每个问题有必需字段
    for q in questions:
        assert "id" in q
        assert "question" in q
        assert "expected_doc_keywords" in q
        assert "expected_doc_titles_containing" in q
        assert "category" in q

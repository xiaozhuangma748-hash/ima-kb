"""测试 eval_retrieval.py 的按格式分桶（by_format）逻辑。

构造 mock questions 和 mock retriever，验证：
1. by_format 字段存在且非空
2. 每种 source_format 的统计正确
3. print_report 输出包含"按来源格式"表格
"""
from __future__ import annotations

import io
import sys
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import MagicMock

# 项目根目录
PROJECT_ROOT = Path(__file__).parent.parent.parent.resolve()
sys.path.insert(0, str(PROJECT_ROOT))

from scripts.eval_retrieval import evaluate, print_report
from core.retrieval.hybrid import HybridResult


def _make_result(chunk_id: str, doc_id: str, content: str, doc_title: str, score: float = 0.1) -> HybridResult:
    """构造 HybridResult。"""
    return HybridResult(
        chunk_id=chunk_id,
        doc_id=doc_id,
        score=score,
        source="both",
        content=content,
        doc_title=doc_title,
    )


def _make_mock_retriever(results_map: dict):
    """构造 mock retriever，根据 query 返回预设结果。"""
    retriever = MagicMock()
    def search(query, top_k=6, use_cache=False, doc_ids=None):
        return results_map.get(query, [])
    retriever.search = search
    return retriever


def _build_basic_test_data():
    """构造基本测试数据（供多个测试复用）。"""
    questions = [
        {
            "id": "q001",
            "question": "节地生态安葬",
            "category": "definition",
            "expected_doc_keywords": ["节地生态安葬"],
            "expected_doc_titles_containing": ["节地生态安葬"],
            "difficulty": "easy",
            "source_format": "pdf",
        },
        {
            "id": "q002",
            "question": "丧葬补助金",
            "category": "subsidy",
            "expected_doc_keywords": ["丧葬补助金"],
            "expected_doc_titles_containing": ["丧葬补助金"],
            "difficulty": "medium",
            "source_format": "docx",
        },
        {
            "id": "q003",
            "question": "政策汇集表",
            "category": "policy",
            "expected_doc_keywords": ["政策"],
            "expected_doc_titles_containing": ["政策汇集"],
            "difficulty": "medium",
            "source_format": "excel",
        },
        {
            "id": "q004",
            "question": "无关问题",
            "category": "negative",
            "expected_doc_keywords": [],
            "expected_doc_titles_containing": [],
            "difficulty": "hard",
            "source_format": "unknown",
        },
    ]

    results_map = {
        "节地生态安葬": [
            _make_result("c1", "d1", "节地生态安葬包括海葬树葬", "节地生态安葬奖补通知"),
        ],
        "丧葬补助金": [
            _make_result("c2", "d2", "丧葬补助金申领条件", "丧葬补助金与抚恤金"),
        ],
        "政策汇集表": [
            _make_result("c3", "d3", "政策汇集表内容", "政策汇集表"),
        ],
        "无关问题": [],
    }

    retriever = _make_mock_retriever(results_map)
    return questions, retriever


def test_by_format_basic():
    """测试基本的 by_format 分桶。"""
    questions, retriever = _build_basic_test_data()

    result = evaluate(
        questions=questions,
        retriever=retriever,
        reranker=None,
        top_k=6,
        top_n=5,
    )

    # 1. by_format 字段存在
    assert "by_format" in result, "by_format 字段缺失"

    # 2. 每种格式都有统计
    by_fmt = result["by_format"]
    print(f"by_format: {by_fmt}")

    assert "pdf" in by_fmt, "pdf 格式缺失"
    assert "docx" in by_fmt, "docx 格式缺失"
    assert "excel" in by_fmt, "excel 格式缺失"
    assert "unknown" in by_fmt, "unknown 格式缺失"

    # 3. 题数正确
    assert by_fmt["pdf"]["total"] == 1, f"pdf 题数错误: {by_fmt['pdf']['total']}"
    assert by_fmt["docx"]["total"] == 1, f"docx 题数错误: {by_fmt['docx']['total']}"
    assert by_fmt["excel"]["total"] == 1, f"excel 题数错误: {by_fmt['excel']['total']}"
    assert by_fmt["unknown"]["total"] == 1, f"unknown 题数错误: {by_fmt['unknown']['total']}"

    # 4. pdf/docx/excel 应该命中，unknown 不命中
    assert by_fmt["pdf"]["hit_rate"] == 1.0, f"pdf hit_rate 错误: {by_fmt['pdf']['hit_rate']}"
    assert by_fmt["docx"]["hit_rate"] == 1.0, f"docx hit_rate 错误: {by_fmt['docx']['hit_rate']}"
    assert by_fmt["excel"]["hit_rate"] == 1.0, f"excel hit_rate 错误: {by_fmt['excel']['hit_rate']}"
    assert by_fmt["unknown"]["hit_rate"] == 0.0, f"unknown hit_rate 错误: {by_fmt['unknown']['hit_rate']}"

    # 5. detail 中包含 source_format 字段
    for d in result["details"]:
        assert "source_format" in d, f"detail {d['id']} 缺少 source_format 字段"

    print("\n[PASS] test_by_format_basic")


def test_print_report_includes_format_table():
    """测试 print_report 输出包含按来源格式表格。"""
    questions, retriever = _build_basic_test_data()
    result = evaluate(
        questions=questions,
        retriever=retriever,
        reranker=None,
        top_k=6,
        top_n=5,
    )

    # 捕获 stdout
    f = io.StringIO()
    with redirect_stdout(f):
        print_report(result, "test-mode")
    output = f.getvalue()

    # 验证输出包含"按来源格式"表格
    assert "按来源格式" in output, "输出缺少'按来源格式'表格"
    assert "| 格式 | 题数 |" in output, "输出缺少格式表格表头"
    assert "pdf" in output, "输出缺少 pdf 行"
    assert "docx" in output, "输出缺少 docx 行"
    assert "excel" in output, "输出缺少 excel 行"
    assert "unknown" in output, "输出缺少 unknown 行"

    print("\n[PASS] test_print_report_includes_format_table")

    # 打印完整报告供人工检查
    print("\n--- 完整报告输出 ---")
    print(output)


def test_mixed_format():
    """测试 mixed 格式（跨文档题）。"""
    questions = [
        {
            "id": "q001",
            "question": "跨文档问题",
            "category": "cross_doc",
            "expected_doc_keywords": ["海葬", "树葬"],
            "expected_doc_titles_containing": ["节地生态安葬", "实施方案"],
            "difficulty": "hard",
            "source_format": "mixed",
        },
    ]

    results_map = {
        "跨文档问题": [
            _make_result("c1", "d1", "海葬树葬内容", "节地生态安葬奖补通知"),
        ],
    }

    retriever = _make_mock_retriever(results_map)
    result = evaluate(
        questions=questions,
        retriever=retriever,
        reranker=None,
        top_k=6,
        top_n=5,
    )

    by_fmt = result["by_format"]
    assert "mixed" in by_fmt, "mixed 格式缺失"
    assert by_fmt["mixed"]["total"] == 1, f"mixed 题数错误: {by_fmt['mixed']['total']}"
    assert by_fmt["mixed"]["hit_rate"] == 1.0, f"mixed hit_rate 错误: {by_fmt['mixed']['hit_rate']}"

    print("\n[PASS] test_mixed_format")


if __name__ == "__main__":
    test_by_format_basic()
    test_print_report_includes_format_table()
    test_mixed_format()
    print("\n=== 所有测试通过 ===")

"""LaTeX 清理测试。"""
from __future__ import annotations

import pytest

from core.cli.chat import ChatMixin
from core.pet.administrator import _sanitize_latex
from core.agent.agent import _sanitize_latex as _agent_sanitize_latex, _check_citation_markers


@pytest.mark.parametrize(
    "raw, expected",
    [
        # 行内/块级公式去掉 $ 符号
        ("$$6520.92 \\times 2 = \\mathbf{13,041.84元}$$", "6520.92 × 2 = 13,041.84元"),
        ("$6,520.92 \\times 2 = \\mathbf{13,041.84元}$", "6,520.92 × 2 = 13,041.84元"),
        # 普通文本不变
        ("丧葬补助金 = 6520.92 × 2 = 13041.84 元", "丧葬补助金 = 6520.92 × 2 = 13041.84 元"),
        # 其他 LaTeX 命令
        ("a \\div b \\approx c \\leq d \\geq e", "a ÷ b ≈ c ≤ d ≥ e"),
        ("x \\neq y \\equiv z \\pm 1", "x ≠ y ≡ z ± 1"),
        ("a \\cdot b", "a · b"),
        # 多行公式：\\ 后面跟 n 这种不标准写法会被清理，重点验证 $$ 已去掉
        ("$$a = b\\\\nc = d$$", "a = b\nnc = d"),
    ],
)
def test_sanitize_latex(raw, expected):
    """三种实现应保持一致且正确清理。"""
    assert ChatMixin._sanitize_latex(raw) == expected
    assert _sanitize_latex(raw) == expected
    assert _agent_sanitize_latex(raw) == expected


def test_sanitize_preserves_markdown():
    """不破坏正常 markdown。"""
    text = "**加粗** 和 [链接](http://a.com) 以及 `代码`"
    assert ChatMixin._sanitize_latex(text) == text
    assert _agent_sanitize_latex(text) == text


def test_check_citation_markers_no_citations():
    """无 [n] 标记时返回空字符串。"""
    text = "这是一个普通答案，没有任何引用标记。"
    assert _check_citation_markers(text) == ""


def test_check_citation_markers_with_citations():
    """含 [n] 标记时返回警告文本。"""
    text = "根据[1]所述，海葬政策规定..."
    warning = _check_citation_markers(text)
    assert warning != ""
    assert "引用说明" in warning
    assert "[n]" in warning


def test_check_citation_markers_multiple():
    """多个 [n] 标记也只返回一条警告。"""
    text = "根据[1]和[2]以及[3]所述..."
    warning = _check_citation_markers(text)
    assert warning != ""
    assert warning.count("引用说明") == 1


def test_check_citation_markers_empty_text():
    """空文本返回空字符串。"""
    assert _check_citation_markers("") == ""
    assert _check_citation_markers(None) == ""

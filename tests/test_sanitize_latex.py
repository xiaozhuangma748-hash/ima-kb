"""LaTeX 清理测试。"""
from __future__ import annotations

import pytest

from core.cli.chat import ChatMixin
from core.pet.administrator import _sanitize_latex


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
    """两种实现应保持一致且正确清理。"""
    assert ChatMixin._sanitize_latex(raw) == expected
    assert _sanitize_latex(raw) == expected


def test_sanitize_preserves_markdown():
    """不破坏正常 markdown。"""
    text = "**加粗** 和 [链接](http://a.com) 以及 `代码`"
    assert ChatMixin._sanitize_latex(text) == text

"""LaTeX 数学公式语法清理（统一公共实现）。

将 LLM 输出中的 LaTeX 命令转为终端 Markdown 可读的 Unicode 字符。
原三处重复实现（core/agent/agent.py、core/pet/administrator.py、core/cli/chat.py）
合并到此模块，遵循 DRY 原则，单一权威来源。

迁移自 core/agent/agent.py 的 _sanitize_latex（含 _LATEX_REPLACEMENTS 常量）。
"""
from __future__ import annotations

import re


# LaTeX 命令 → Unicode 字符映射（流式和最终清理共用）
LATEX_REPLACEMENTS = {
    r"\times": "×", r"\div": "÷", r"\approx": "≈",
    r"\leq": "≤", r"\le": "≤", r"\geq": "≥", r"\ge": "≥",
    r"\neq": "≠", r"\equiv": "≡", r"\pm": "±", r"\cdot": "·",
}


def sanitize_latex(text: str) -> str:
    """清理 LaTeX 数学公式语法，使其在终端 Markdown 中可读。

    处理 5 类规则：
    1. ``$$...$$`` 块级公式 → 去壳保留内容
    2. ``$...$`` 行内公式 → 去壳保留内容
    3. 11 个 LaTeX 命令 → Unicode 字符（× ÷ ≈ ≤ ≥ ≠ ≡ ± ·）
    4. ``\\mathbf{...}`` / ``\\text{...}`` → 保留花括号内容
    5. ``\\\\`` → 换行，连续两空格 → 单空格

    Args:
        text: 可能含 LaTeX 语法的文本

    Returns:
        清理后的文本（纯 Unicode + Markdown）
    """
    text = re.sub(r"\$\$(.*?)\$\$", r"\1", text, flags=re.DOTALL)
    text = re.sub(r"\$(.*?)\$", r"\1", text, flags=re.DOTALL)
    for latex, char in LATEX_REPLACEMENTS.items():
        text = text.replace(latex, char)
    text = re.sub(r"\\mathbf\{(.*?)\}", r"\1", text, flags=re.DOTALL)
    text = re.sub(r"\\text\{(.*?)\}", r"\1", text, flags=re.DOTALL)
    text = text.replace("\\\\", "\n")
    return text.replace("  ", " ")

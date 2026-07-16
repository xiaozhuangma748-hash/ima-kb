"""引用验证增强：检测并修复 LLM 答案中的引用问题。

LLM 在生成答案时可能出现以下问题：
1. **越界引用**：标注 [9] 但只有 5 个参考资料（幻觉）
2. **缺失引用**：答案有实质内容但没有任何 [n] 标记（用户无法追溯）
3. **重复编号**：同一引用编号在列表中多次出现

本模块提供验证和清理工具，被 RAGChain 在构造最终答案时调用。
"""
from __future__ import annotations

import re
from typing import List, Optional, Tuple

# 匹配 [n] 形式的引用标记（n 为 1-3 位数字）
CITATION_PATTERN = re.compile(r"\[(\d{1,3})\]")


def extract_citation_indices(content: str) -> List[int]:
    """提取答案文本中所有 [n] 引用编号（按出现顺序，去重）。

    Args:
        content: LLM 生成的答案文本

    Returns:
        引用编号列表（1-based，去重保序）
    """
    seen = set()
    indices: List[int] = []
    for m in CITATION_PATTERN.finditer(content or ""):
        n = int(m.group(1))
        if n not in seen:
            seen.add(n)
            indices.append(n)
    return indices


def filter_valid_citations(
    content: str, num_sources: int
) -> List[int]:
    """过滤出合法的引用编号（1 ≤ n ≤ num_sources）。

    Args:
        content: LLM 生成的答案文本
        num_sources: 参考资料总数（最大合法编号）

    Returns:
        合法的引用编号列表（按出现顺序，去重）
    """
    if num_sources <= 0:
        return []
    valid: List[int] = []
    seen = set()
    for n in extract_citation_indices(content):
        if 1 <= n <= num_sources and n not in seen:
            seen.add(n)
            valid.append(n)
    return valid


def find_invalid_citations(content: str, num_sources: int) -> List[int]:
    """找出越界引用编号（n > num_sources 或 n < 1）。

    Args:
        content: LLM 生成的答案文本
        num_sources: 参考资料总数

    Returns:
        越界编号列表（按出现顺序，去重）
    """
    if num_sources <= 0:
        return extract_citation_indices(content)
    invalid: List[int] = []
    seen = set()
    for n in extract_citation_indices(content):
        if (n < 1 or n > num_sources) and n not in seen:
            seen.add(n)
            invalid.append(n)
    return invalid


def has_substantive_content(content: str, min_length: int = 20) -> bool:
    """检测答案是否有实质内容（排除空白、纯标点、纯警告词）。

    Args:
        content: 答案文本
        min_length: 实质内容最小长度（去掉空白和标点后）

    Returns:
        True 如果有实质内容
    """
    if not content:
        return False
    # 去掉 [n] 引用标记
    text = CITATION_PATTERN.sub("", content)
    # 去掉空白
    text = re.sub(r"\s+", "", text)
    # 去掉常见标点（中英文，方括号单独处理避免字符类歧义，- 放末尾避免范围）
    text = re.sub(r"[，。！？、；：""''（）()【】,.!?;:—-]", "", text)
    # 去掉方括号本身
    text = text.replace("[", "").replace("]", "")
    return len(text) >= min_length


def missing_citation_warning(
    content: str, num_sources: int
) -> Optional[str]:
    """检测答案有实质内容但缺少引用的情况，返回提示文本。

    Args:
        content: LLM 生成的答案文本
        num_sources: 参考资料总数

    Returns:
        警告文本（如果有问题），否则 None
    """
    if not has_substantive_content(content):
        return None
    if num_sources <= 0:
        return None
    valid = filter_valid_citations(content, num_sources)
    if not valid:
        return (
            "⚠️ 注意：本答案未明确标注引用来源，"
            "建议结合下方参考资料核对内容准确性。"
        )
    return None


def validate_answer(
    content: str, num_sources: int
) -> Tuple[List[int], List[int], Optional[str]]:
    """一次性完成引用验证。

    Args:
        content: LLM 生成的答案文本
        num_sources: 参考资料总数

    Returns:
        (valid_citations, invalid_citations, warning)
        - valid_citations: 合法引用编号列表
        - invalid_citations: 越界引用编号列表
        - warning: 缺失引用警告文本（无问题时为 None）
    """
    valid = filter_valid_citations(content, num_sources)
    invalid = find_invalid_citations(content, num_sources)
    warning = None
    if has_substantive_content(content) and not valid:
        warning = missing_citation_warning(content, num_sources)
    return valid, invalid, warning

"""引用结构化：从回答中提取 [n] 标记，映射到 doc_id + 段落号。"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import List


@dataclass
class Citation:
    """单条引用。"""
    marker: str           # "[1]"
    doc_id: str
    title: str
    paragraph_num: int
    snippet: str          # 原文片段（50-100 字）


def extract_citations(answer: str, sources: List[dict]) -> List[Citation]:
    """从回答中提取 [n] 引用标记，映射到 sources。

    Args:
        answer: LLM 回答文本，含 [1][2] 形式引用标记
        sources: 检索到的来源列表，每项含 doc_id/title/paragraph_num/snippet
                 sources[0] 对应 [1]，sources[1] 对应 [2]，以此类推

    Returns:
        引用列表，按出现顺序去重
    """
    # 匹配 [1] [12] [1][2] 等形式
    pattern = re.compile(r"\[(\d+)\]")
    matches = pattern.findall(answer)

    seen = set()
    citations = []
    for match in matches:
        idx = int(match) - 1  # [1] → sources[0]
        if idx < 0 or idx >= len(sources):
            continue
        if idx in seen:
            continue
        seen.add(idx)
        src = sources[idx]
        citations.append(Citation(
            marker=f"[{match}]",
            doc_id=src["doc_id"],
            title=src["title"],
            paragraph_num=src["paragraph_num"],
            snippet=src["snippet"],
        ))
    return citations


def sanitize_outbound_citations(text: str, num_sources: int) -> str:
    """删除越界的 [n] 引用标记。

    LLM 幻觉可能生成 [3] 但实际只有 1 条资料，此时 [3] 是越界标记，
    需要从正文删除，否则用户看到 [3] 却在引用列表找不到对应条目。

    Args:
        text: 原始文本
        num_sources: 参考资料总数（合法编号 1..num_sources）

    Returns:
        清理后的文本（越界 [n] 被删除）
    """
    if num_sources <= 0 or not text:
        return text

    def _replacer(m: "re.Match[str]") -> str:
        n = int(m.group(1))
        return m.group(0) if 1 <= n <= num_sources else ""

    return re.sub(r"\[(\d{1,3})\]", _replacer, text)

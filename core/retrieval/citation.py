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

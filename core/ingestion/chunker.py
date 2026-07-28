"""文档分块器（格式感知版）。

策略按 format_tag 分发：
- excel: 按行切（每行键值对完整保留），每 N 行一 chunk
- ppt:   按 `## Slide N` 切，每 slide 至少一个 chunk
- markdown: 按 `#`/`##`/`###` 标题层级切（structure-aware）
- pdf/docx/image/html/text: 段落+滑动窗口（沿用原策略）

通用策略：
1. 优先按段落（双换行）切分，保持语义完整
2. 段落过长时按 chunk_size 二次切分
3. 块之间保留 overlap 重叠，避免边界信息丢失

输出 Chunk 列表，每个 Chunk 带在文档中的顺序索引。
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import List

from .parser import ParsedDocument


@dataclass
class Chunk:
    """文档分块。

    Attributes:
        content: 块文本内容（child chunk，用于检索）
        index: 在原文档中的顺序（0-based）
        start_char: 起始字符位置
        end_char: 结束字符位置
        token_count: 大致 token 数（按字符数 / 2 估算，中文为主）
        parent_content: 父级 chunk 内容（small-to-big 检索用，None 表示无 parent）
    """

    content: str
    index: int
    start_char: int
    end_char: int
    token_count: int = 0
    parent_content: str = ""


def _estimate_tokens(text: str) -> int:
    """粗略估算 token 数。

    中文为主时约 1 字 = 1 token，英文约 4 字符 = 1 token。
    这里用字符数 / 2 做保守估算。空文本返回 0。
    """
    return len(text) // 2 if text else 0


def _merge_short_paragraphs(paragraphs: List[str], target_size: int) -> List[str]:
    """合并过短的段落，使每段尽量接近 target_size。

    保持段落语义完整，不会在段中间切。
    """
    if not paragraphs:
        return []

    merged: list[str] = []
    buffer = ""
    for para in paragraphs:
        para = para.strip()
        if not para:
            continue
        # 如果 buffer + para 还没到目标大小，合并
        if buffer and len(buffer) + len(para) + 2 <= target_size:
            buffer = f"{buffer}\n\n{para}"
        else:
            # 先把 buffer 推出去
            if buffer:
                merged.append(buffer)
            # 如果单个段落本身就比 target 大，保留它后面会被 _split_long_text 处理
            buffer = para
    if buffer:
        merged.append(buffer)
    return merged


def _split_long_text(text: str, max_size: int, overlap: int) -> List[tuple[int, int, str]]:
    """把过长文本切成多块，带 overlap 重叠。

    Returns:
        [(start_char, end_char, sub_text), ...]
    """
    if not text:
        return []
    if len(text) <= max_size:
        return [(0, len(text), text)]

    pieces: list[tuple[int, int, str]] = []
    start = 0
    while start < len(text):
        end = min(start + max_size, len(text))
        # 尽量在句号/换行处切，避免硬切
        if end < len(text):
            # 在 [start + max_size*0.7, end] 范围内找最近的换行或句号
            search_start = start + int(max_size * 0.7)
            for sep in ("\n", "。", "！", "？", ". ", "! ", "? ", "；", "; "):
                cut = text.rfind(sep, search_start, end)
                if cut > search_start:
                    end = cut + len(sep)
                    break
        pieces.append((start, end, text[start:end]))
        if end >= len(text):
            break
        # 下一块起点：回退 overlap 个字符
        start = max(end - overlap, start + 1)
    return pieces


# ============================================================
# 格式感知分块策略
# ============================================================

def _chunk_excel(text: str, chunk_size: int, chunk_overlap: int) -> List[tuple[int, int, str]]:
    """Excel 分块：一行一 chunk，永不切断单行，不合并多行。

    xlsx parser 输出每行一条记录（[SheetName] 序号=N | 字段=值 | ...），
    行间用 \\n 分隔。每行作为独立 chunk，确保检索精确：
    - 搜索"晨光社区"只命中该行所在 chunk，不会返回同 chunk 中的其他社区
    - LLM 看到的 context 也更精确（单条记录）

    chunk_size / chunk_overlap 参数仅为接口兼容，实际不使用。
    """
    if not text:
        return []
    lines = text.split("\n")
    pieces: list[tuple[int, int, str]] = []
    global_pos = 0

    for line in lines:
        if not line.strip():
            global_pos += len(line) + 1
            continue
        # 一行一 chunk，不合并
        pieces.append((global_pos, global_pos + len(line), line))
        global_pos += len(line) + 1  # +1 for \n

    return pieces


def _chunk_ppt(text: str, chunk_size: int, chunk_overlap: int) -> List[tuple[int, int, str]]:
    """PPT 分块：按 `## Slide N` 切，每 slide 至少一个 chunk。

    保持 slide 完整性，单 slide 过长时按 _split_long_text 二次切分。
    """
    if not text:
        return []
    # 用正则切分，保留分隔符
    pattern = re.compile(r"(?=^## Slide \d+$)", re.MULTILINE)
    parts = pattern.split(text)
    parts = [p.strip() for p in parts if p.strip()]

    pieces: list[tuple[int, int, str]] = []
    global_pos = 0
    for part in parts:
        if len(part) <= chunk_size:
            pieces.append((global_pos, global_pos + len(part), part))
        else:
            # 长 slide 二次切分
            sub_pieces = _split_long_text(part, chunk_size, chunk_overlap)
            for ls, le, sub_text in sub_pieces:
                pieces.append((global_pos + ls, global_pos + le, sub_text))
        global_pos += len(part) + 2  # +2 for \n\n separator
    return pieces


def _chunk_markdown(text: str, chunk_size: int, chunk_overlap: int) -> List[tuple[int, int, str]]:
    """Markdown 分块：按标题层级切（structure-aware）。

    策略：
    1. 按 `#`/`##`/`###` 标题切段，每段保留完整标题层级
    2. 段落过长时二次切分
    3. 合并过短段落
    """
    if not text:
        return []
    # 按标题行切分（保留标题）
    lines = text.split("\n")
    sections: list[str] = []
    current: list[str] = []

    for line in lines:
        # 匹配 # / ## / ### 等标题
        if re.match(r"^#{1,6}\s+", line):
            # 遇到新标题，把累积的 current 推出
            if current:
                sections.append("\n".join(current))
                current = []
        current.append(line)
    if current:
        sections.append("\n".join(current))

    # 合并过短 section
    merged = _merge_short_paragraphs(sections, target_size=chunk_size)

    # 二次切分超长 section
    pieces: list[tuple[int, int, str]] = []
    global_pos = 0
    for sec in merged:
        if len(sec) <= chunk_size:
            pieces.append((global_pos, global_pos + len(sec), sec))
        else:
            sub_pieces = _split_long_text(sec, chunk_size, chunk_overlap)
            for ls, le, sub_text in sub_pieces:
                pieces.append((global_pos + ls, global_pos + le, sub_text))
        global_pos += len(sec) + 2
    return pieces


def _chunk_text(text: str, chunk_size: int, chunk_overlap: int) -> List[tuple[int, int, str]]:
    """普通文本分块（沿用原策略）：段落 + 滑动窗口。"""
    if not text:
        return []
    # 兼容 Windows 换行
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    paragraphs = normalized.split("\n\n")
    paragraphs = _merge_short_paragraphs(paragraphs, target_size=chunk_size)

    pieces: list[tuple[int, int, str]] = []
    global_pos = 0
    for para in paragraphs:
        sub_pieces = _split_long_text(para, max_size=chunk_size, overlap=chunk_overlap)
        for local_start, local_end, sub_text in sub_pieces:
            abs_start = global_pos + local_start
            abs_end = global_pos + local_end
            pieces.append((abs_start, abs_end, sub_text))
        global_pos += len(para) + 2  # +2 for \n\n separator
    return pieces


def _build_parent_chunks(chunks: List[Chunk], doc: ParsedDocument, parent_size: int = 2048) -> None:
    """为 chunks 生成 parent_content（small-to-big 检索用）。

    策略按 format_tag：
    - excel/ppt: 每个 child 的 parent 就是其所属 sheet/slide 的全部内容
    - markdown: parent 是同章节（同 # 标题下）的所有 child 合并
    - 其他: 按 parent_size 容量合并相邻 child

    原地修改 chunks 的 parent_content 字段。
    """
    if not chunks:
        return

    format_tag = getattr(doc, "format_tag", "text")

    if format_tag == "ppt":
        # PPT: 按 `## Slide N` 边界分组
        _group_by_ppt_slide(chunks)
    elif format_tag == "excel":
        # Excel: 按 `[SheetName]` 边界分组
        _group_by_excel_sheet(chunks)
    elif format_tag == "markdown":
        # Markdown: 按 `#` 标题分组（降级到按容量合并）
        _group_by_capacity(chunks, parent_size)
    else:
        # pdf/docx/image/html/text: 按 parent_size 容量合并相邻 child
        _group_by_capacity(chunks, parent_size)


def _group_by_ppt_slide(chunks: List[Chunk]) -> None:
    """PPT parent: 按 `## Slide N` 边界分组合并。"""
    import re
    # 为每个 chunk 找出其所属 slide 的所有 chunk
    # 用 chunk content 是否含 `## Slide N` 或在其之后判断
    slide_groups: dict[int, list[int]] = {}  # slide_no -> [chunk_idx]
    current_slide = 0
    for i, c in enumerate(chunks):
        # 检测 chunk 开头的 slide 标记
        m = re.match(r"^## Slide (\d+)", c.content)
        if m:
            current_slide = int(m.group(1))
        slide_groups.setdefault(current_slide, []).append(i)

    # 每个 chunk 的 parent_content 是同 slide 所有 chunk 合并
    for slide_no, idxs in slide_groups.items():
        if len(idxs) <= 1:
            # 单 chunk 独占 slide，parent 就是自己
            chunks[idxs[0]].parent_content = chunks[idxs[0]].content
            continue
        merged = "\n\n".join(chunks[i].content for i in idxs)
        for i in idxs:
            chunks[i].parent_content = merged


def _group_by_excel_sheet(chunks: List[Chunk]) -> None:
    """Excel parent: 按 `[SheetName]` 边界分组合并。"""
    import re
    sheet_groups: dict[str, list[int]] = {}
    current_sheet = "default"
    for i, c in enumerate(chunks):
        # 检测 chunk 中出现的 sheet 标记
        m = re.match(r"^\[([^\]]+)\]", c.content)
        if m:
            current_sheet = m.group(1)
        sheet_groups.setdefault(current_sheet, []).append(i)

    for sheet, idxs in sheet_groups.items():
        if len(idxs) <= 1:
            chunks[idxs[0]].parent_content = chunks[idxs[0]].content
            continue
        merged = "\n".join(chunks[i].content for i in idxs)
        for i in idxs:
            chunks[i].parent_content = merged


def _group_by_capacity(chunks: List[Chunk], parent_size: int) -> None:
    """通用 parent: 按 parent_size 容量合并相邻 child。"""
    if not chunks:
        return
    # 简单策略：每 N 个 child 合并为一个 parent（N 根据 parent_size / chunk_size 估算）
    # 默认 4 个 child 合并为 1 个 parent（512*4 = 2048）
    group_size = max(1, parent_size // 512)
    for i, chunk in enumerate(chunks):
        group_start = (i // group_size) * group_size
        group_end = min(group_start + group_size, len(chunks))
        merged = "\n\n".join(chunks[j].content for j in range(group_start, group_end))
        chunk.parent_content = merged


def chunk_document(
    doc: ParsedDocument,
    chunk_size: int = 512,
    chunk_overlap: int = 64,
) -> List[Chunk]:
    """把 ParsedDocument 切成 Chunk 列表（格式感知）。

    Args:
        doc: 已解析的文档
        chunk_size: 每块最大字符数（默认 512）
        chunk_overlap: 块间重叠字符数（默认 64）

    Returns:
        Chunk 列表（含 parent_content 字段，用于 small-to-big 检索）
    """
    text = doc.text.strip()
    if not text:
        return []

    # 按 format_tag 分发分块策略
    format_tag = getattr(doc, "format_tag", "text")
    if format_tag == "excel":
        pieces = _chunk_excel(text, chunk_size, chunk_overlap)
    elif format_tag == "ppt":
        pieces = _chunk_ppt(text, chunk_size, chunk_overlap)
    elif format_tag == "markdown":
        pieces = _chunk_markdown(text, chunk_size, chunk_overlap)
    else:
        # pdf / docx / image / html / text 沿用通用策略
        pieces = _chunk_text(text, chunk_size, chunk_overlap)

    chunks: list[Chunk] = []
    for idx, (start, end, sub_text) in enumerate(pieces):
        sub_text = sub_text.strip()
        if sub_text:
            chunks.append(
                Chunk(
                    content=sub_text,
                    index=idx,
                    start_char=start,
                    end_char=end,
                    token_count=_estimate_tokens(sub_text),
                )
            )

    # 为每个 chunk 生成 parent_content（small-to-big 检索用）
    _build_parent_chunks(chunks, doc)

    return chunks

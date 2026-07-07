"""文档分块器。

策略：
1. 优先按段落（双换行）切分，保持语义完整
2. 段落过长时按 chunk_size 二次切分
3. 块之间保留 overlap 重叠，避免边界信息丢失
4. 代码文件按函数/类边界切分（保留完整逻辑块）

输出 Chunk 列表，每个 Chunk 带在文档中的顺序索引。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List

from .parser import ParsedDocument


@dataclass
class Chunk:
    """文档分块。

    Attributes:
        content: 块文本内容
        index: 在原文档中的顺序（0-based）
        start_char: 起始字符位置
        end_char: 结束字符位置
        token_count: 大致 token 数（按字符数 / 2 估算，中文为主）
    """

    content: str
    index: int
    start_char: int
    end_char: int
    token_count: int = 0


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


def chunk_document(
    doc: ParsedDocument,
    chunk_size: int = 512,
    chunk_overlap: int = 64,
) -> List[Chunk]:
    """把 ParsedDocument 切成 Chunk 列表。

    Args:
        doc: 已解析的文档
        chunk_size: 每块最大字符数（默认 512）
        chunk_overlap: 块间重叠字符数（默认 64）

    Returns:
        Chunk 列表
    """
    text = doc.text.strip()
    if not text:
        return []

    # 代码文件：按函数/类切分（简单按双换行）
    is_code = doc.meta.get("is_code") == "true"

    # 第一步：按段落（双换行）切分
    if is_code:
        # 代码按空行切分
        paragraphs = text.split("\n\n")
    else:
        # 普通文本：兼容 Windows 换行
        normalized = text.replace("\r\n", "\n").replace("\r", "\n")
        paragraphs = normalized.split("\n\n")

    # 第二步：合并过短段落
    paragraphs = _merge_short_paragraphs(paragraphs, target_size=chunk_size)

    # 第三步：把段落拼接成全局文本，记录每段起始位置
    chunks: list[Chunk] = []
    global_pos = 0
    chunk_idx = 0

    for para in paragraphs:
        # 段落前如果有分隔，对齐全局位置
        # 把当前段落切成长度合适的块
        pieces = _split_long_text(para, max_size=chunk_size, overlap=chunk_overlap)
        for local_start, local_end, sub_text in pieces:
            abs_start = global_pos + local_start
            abs_end = global_pos + local_end
            sub_text = sub_text.strip()
            if sub_text:
                chunks.append(
                    Chunk(
                        content=sub_text,
                        index=chunk_idx,
                        start_char=abs_start,
                        end_char=abs_end,
                        token_count=_estimate_tokens(sub_text),
                    )
                )
                chunk_idx += 1
        # 下一段从 global_pos + len(para) 开始
        global_pos += len(para)
        # 段落之间有 \n\n 分隔
        global_pos += 2

    return chunks

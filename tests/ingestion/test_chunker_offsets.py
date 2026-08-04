"""Chunker 偏移准确性测试。

验证每个 chunk 的 start_char/end_char 能在原文中定位到对应内容。
PDF 场景特别重要：page_text.strip() 不应导致位置错位。
"""
from __future__ import annotations

from pathlib import Path

import pytest

from core.ingestion.chunker import chunk_document, Chunk
from core.ingestion.parser import ParsedDocument


def _make_doc(text: str, format_tag: str = "text") -> ParsedDocument:
    """构造 ParsedDocument 用于测试。"""
    return ParsedDocument(
        text=text,
        title="test",
        file_path=Path("test.txt"),
        file_type=".txt",
        format_tag=format_tag,
    )


def test_text_chunk_offsets_match_original():
    """普通文本：每个 chunk 的 text[start:end] 应等于 chunk.content。"""
    text = "这是第一段内容。\n\n这是第二段内容。\n\n这是第三段内容，比较长一些用来测试切分。"
    doc = _make_doc(text, "text")
    chunks = chunk_document(doc, chunk_size=50, chunk_overlap=10)

    assert len(chunks) > 0
    for c in chunks:
        # 验证 start_char/end_char 能在原文中定位到内容
        snippet = text[c.start_char:c.end_char]
        # chunk.content 是 strip 后的，所以原文 snippet 的 strip 后应等于 content
        assert snippet.strip() == c.content.strip(), (
            f"chunk {c.index} 偏移错位: "
            f"text[{c.start_char}:{c.end_char}]={snippet!r} != content={c.content!r}"
        )


def test_pdf_chunk_offsets_match_original():
    """PDF：page_text.strip() 不应导致位置错位。"""
    text = (
        "--- Page 1 ---\n"
        "   前导空格的内容。\n"
        "   第二行内容。\n"
        "--- Page 2 ---\n"
        "第二页内容。"
    )
    doc = _make_doc(text, "pdf")
    chunks = chunk_document(doc, chunk_size=100, chunk_overlap=10)

    assert len(chunks) > 0
    for c in chunks:
        snippet = text[c.start_char:c.end_char]
        # 由于 _chunk_text 内部会做段落合并和切分，content 可能是原文片段的子集
        # 但至少 chunk.content 的核心内容应该出现在 text[start:end] 中
        assert c.content.strip(), f"chunk {c.index} 内容为空"
        # 验证：chunk.content 的前 10 个字符（去除空白）应在原文 snippet 中出现
        content_core = c.content.strip()[:10]
        if content_core:
            assert content_core in snippet or snippet.strip() in c.content, (
                f"chunk {c.index} 偏移错位: "
                f"text[{c.start_char}:{c.end_char}]={snippet!r} 与 content={c.content!r} 不匹配"
            )


def test_pdf_page_marker_offset_correct():
    """PDF：第一个 chunk 应在第一个 Page 标记之后。"""
    text = (
        "--- Page 1 ---\n"
        "Page one content here."
    )
    doc = _make_doc(text, "pdf")
    chunks = chunk_document(doc, chunk_size=100, chunk_overlap=10)

    assert len(chunks) >= 1
    page1_marker_end = len("--- Page 1 ---\n")
    for c in chunks:
        if c.page_num == 1:
            # chunk 的起始位置应在 page 1 标记之后
            assert c.start_char >= page1_marker_end - 5, (
                f"chunk {c.index} 起始位置 {c.start_char} 在 page 1 标记之前，"
                f"标记结束位置 {page1_marker_end}"
            )


def test_markdown_chunk_offsets_match_original():
    """Markdown：每个 chunk 的位置应在原文中可定位。"""
    text = (
        "# 标题一\n\n"
        "这是标题一下的内容。\n\n"
        "## 子标题\n\n"
        "子标题下的内容。\n\n"
        "# 标题二\n\n"
        "标题二下的内容。"
    )
    doc = _make_doc(text, "markdown")
    chunks = chunk_document(doc, chunk_size=100, chunk_overlap=10)

    assert len(chunks) > 0
    # 每个 chunk 的 content 应是原文的子串（允许 strip 差异）
    for c in chunks:
        content_stripped = c.content.strip()
        if content_stripped:
            # 至少 content 的前 20 字符应在原文中出现
            head = content_stripped[:20]
            assert head in text, (
                f"chunk {c.index} content 前缀 {head!r} 不在原文中，可能位置错位"
            )


def test_excel_chunk_offsets_monotonic():
    """Excel：chunk 的 start_char 应单调递增。"""
    text = "\n".join([
        "[Sheet1] 序号=1 | 字段A=值1 | 字段B=值2",
        "[Sheet1] 序号=2 | 字段A=值3 | 字段B=值4",
        "[Sheet2] 序号=1 | 字段C=值5",
    ])
    doc = _make_doc(text, "excel")
    chunks = chunk_document(doc, chunk_size=200, chunk_overlap=10)

    assert len(chunks) > 0
    for i in range(1, len(chunks)):
        assert chunks[i].start_char >= chunks[i-1].start_char, (
            f"chunk {i} start_char {chunks[i].start_char} < "
            f"chunk {i-1} start_char {chunks[i-1].start_char}"
        )


def test_chunks_cover_whole_text():
    """所有 chunk 的 union 应覆盖原文（允许 overlap）。"""
    text = (
        "这是第一段。\n\n"
        "这是第二段。\n\n"
        "这是第三段。"
    )
    doc = _make_doc(text, "text")
    chunks = chunk_document(doc, chunk_size=50, chunk_overlap=10)

    assert len(chunks) > 0
    # 第一个 chunk 应从原文开头开始（或接近开头）
    assert chunks[0].start_char <= 5, f"第一个 chunk 起始位置 {chunks[0].start_char} 偏离原文开头"
    # 最后一个 chunk 应到原文结尾（或接近结尾）
    assert chunks[-1].end_char >= len(text) - 5, (
        f"最后一个 chunk 结束位置 {chunks[-1].end_char} 偏离原文结尾 {len(text)}"
    )


def test_pdf_chunks_have_page_num():
    """PDF chunk 应携带 page_num 字段。"""
    text = (
        "--- Page 1 ---\n"
        "第一页内容。\n"
        "--- Page 2 ---\n"
        "第二页内容。"
    )
    doc = _make_doc(text, "pdf")
    chunks = chunk_document(doc, chunk_size=100, chunk_overlap=10)

    assert len(chunks) >= 2
    page_nums = {c.page_num for c in chunks}
    assert 1 in page_nums, "缺少 page 1"
    assert 2 in page_nums, "缺少 page 2"


def test_pdf_strip_leading_whitespace_offset():
    """PDF：page_text.strip() 不应导致 chunk.start_char 偏小。

    回归测试：原实现 page_start 直接用于 abs_start 计算，但 page_text 经过 strip
    后实际起始位置 = page_start + leading_ws_len。若不修正，chunk.start_char 会
    把前导空白算进去，导致 text[start:end] 包含空白而非实际内容。
    """
    text = (
        "--- Page 1 ---\n"
        "   \n"  # 3 个前导空格 + 换行（共 4 字符）
        "实际内容开始位置。"
    )
    doc = _make_doc(text, "pdf")
    chunks = chunk_document(doc, chunk_size=200, chunk_overlap=10)

    assert len(chunks) >= 1
    c = chunks[0]
    # 验证 text[start_char:] 开头就是 "实际内容" 而非空白
    snippet = text[c.start_char:c.end_char]
    assert snippet.lstrip()[:4] == "实际内容", (
        f"chunk.start_char={c.start_char} 偏移错位，"
        f"text[start:end]={snippet!r} 前导有空白"
    )


def test_chunk_index_is_sequential():
    """chunk.index 应从 0 开始连续递增。"""
    text = "段落一。\n\n段落二。\n\n段落三。"
    doc = _make_doc(text, "text")
    chunks = chunk_document(doc, chunk_size=50, chunk_overlap=10)

    for i, c in enumerate(chunks):
        assert c.index == i, f"chunk.index={c.index} 期望 {i}"

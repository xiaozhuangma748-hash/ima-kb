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
        page_num: PDF 页码（1-based，0 表示非 PDF 或未标记）
        heading: 所属章节标题（PDF 提取的标题层级，空字符串表示未标记）
    """

    content: str
    index: int
    start_char: int
    end_char: int
    token_count: int = 0
    parent_content: str = ""
    page_num: int = 0
    heading: str = ""


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
    """Excel 分块：短行合并，长行独立，永不切断单行。

    xlsx parser 输出每行一条记录（[SheetName] 序号=N | 字段=值 | ...），
    行间用 \\n 分隔。

    策略：
    - 单行长度 >= chunk_size：独立成 chunk（长行不合并）
    - 单行长度 < chunk_size：合并相邻短行直到接近 chunk_size
    - 保持单行完整性，永不切断单行
    - Sheet 边界（[SheetName] 开头的行）强制开启新 chunk

    这样既保留精确匹配能力（"晨光社区"只在该行 chunk 中），
    又避免政策汇集表等大量短行产生过多碎片 chunk。
    """
    if not text:
        return []
    lines = text.split("\n")
    pieces: list[tuple[int, int, str]] = []
    global_pos = 0

    buffer_lines: list[str] = []
    buffer_start_pos = 0
    buffer_len = 0

    def _flush_buffer() -> None:
        nonlocal buffer_lines, buffer_start_pos, buffer_len
        if buffer_lines:
            merged_text = "\n".join(buffer_lines)
            pieces.append((buffer_start_pos, buffer_start_pos + len(merged_text), merged_text))
            buffer_lines = []
            buffer_len = 0

    for line in lines:
        line_len = len(line)
        # 空行跳过位置但仍推进
        if not line.strip():
            global_pos += line_len + 1
            continue

        # Sheet 边界：强制 flush 并开始新 buffer
        is_sheet_boundary = line.startswith("[") and "]" in line

        # 长行（>= chunk_size）：独立成 chunk
        if line_len >= chunk_size:
            _flush_buffer()
            pieces.append((global_pos, global_pos + line_len, line))
            global_pos += line_len + 1
            continue

        # Sheet 边界：强制 flush
        if is_sheet_boundary and buffer_lines:
            _flush_buffer()

        # 合并到 buffer
        if not buffer_lines:
            buffer_start_pos = global_pos
        if buffer_lines and buffer_len + line_len + 1 > chunk_size:
            # buffer 已满，flush 后开新 buffer
            _flush_buffer()
            buffer_start_pos = global_pos
        buffer_lines.append(line)
        buffer_len += line_len + (1 if len(buffer_lines) > 1 else 0)
        global_pos += line_len + 1

    _flush_buffer()
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
    """Markdown 分块：按标题层级切（structure-aware），保护代码块完整性。

    策略：
    1. 先识别 ` ``` ` 围栏代码块，整体作为不可切分单元
    2. 按 `#`/`##`/`###` 标题切段，每段保留完整标题层级
    3. 段落过长时二次切分（代码块内部不再二次切分）
    4. 合并过短段落
    """
    if not text:
        return []

    # 第一步：把代码块作为"原子单元"提取出来，避免被标题切分逻辑打断
    # 用占位符替换代码块，最后再还原
    code_blocks: list[str] = []
    code_placeholder_tpl = "\x00CODEBLOCK{}\x00"

    def _extract_code_blocks(src: str) -> str:
        """把 ``` ... ``` 代码块替换为占位符，保护其完整性。"""
        nonlocal code_blocks
        # 匹配 ```lang\n...\n``` 或 ```\n...\n```（非贪婪）
        pattern = re.compile(r"```[^\n]*\n.*?\n```", re.DOTALL)
        new_result = []
        last_end = 0
        for m in pattern.finditer(src):
            new_result.append(src[last_end:m.start()])
            idx = len(code_blocks)
            code_blocks.append(m.group(0))
            new_result.append(code_placeholder_tpl.format(idx))
            last_end = m.end()
        new_result.append(src[last_end:])
        return "".join(new_result)

    placeholder_text = _extract_code_blocks(text)

    # 第二步：按标题行切分（保留标题）
    lines = placeholder_text.split("\n")
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

    # 第三步：还原代码块占位符
    def _restore_placeholders(s: str) -> str:
        for idx, code in enumerate(code_blocks):
            s = s.replace(code_placeholder_tpl.format(idx), code)
        return s

    merged = [_restore_placeholders(s) for s in merged]

    # 第四步：二次切分超长 section（代码块已还原，整体作为不可切分单元）
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


# Heading 行检测正则（# 开头的 Markdown 标题，_parse_docx 注入）
_DOCX_HEADING_PATTERN = re.compile(r"^(#{1,6})\s+(.+)$")


def _chunk_docx(text: str, chunk_size: int, chunk_overlap: int) -> List[tuple[int, int, str, str]]:
    """DOCX 专用分块：按 Heading 层级切分，提取 heading 字段。

    复用 Markdown 的标题切分逻辑（_parse_docx 已把 Heading 样式转为 `#` 标记），
    额外提取每个 chunk 所属的最近一个 Heading 文本作为 heading 字段。

    Returns:
        [(start_char, end_char, sub_text, heading), ...]
    """
    if not text:
        return []

    # 复用 markdown 切分逻辑获得 (start, end, text) 三元组
    md_pieces = _chunk_markdown(text, chunk_size, chunk_overlap)

    # 为每个 piece 提取所属 heading（该 piece 内第一个 # 标题，或继承自前一个 piece 的 heading）
    pieces: list[tuple[int, int, str, str]] = []
    current_heading = ""
    for start, end, sub_text in md_pieces:
        # 扫描该 piece 内的标题行，取第一个标题作为该 piece 的归属
        # （_chunk_markdown 按标题切分，piece 开头通常是标题）
        lines = sub_text.split("\n")
        piece_heading = current_heading  # 默认继承前一个 piece 的 heading
        for line in lines:
            m = _DOCX_HEADING_PATTERN.match(line)
            if m:
                # 取该 piece 内第一个标题作为归属
                piece_heading = m.group(2).strip()
                current_heading = piece_heading
                break  # 只取第一个标题
        pieces.append((start, end, sub_text, piece_heading))
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


# PDF 页码分隔标记的正则（_parse_pdf 注入的 `--- Page N ---`）
_PDF_PAGE_MARKER = re.compile(r"^--- Page (\d+) ---$", re.MULTILINE)

# PDF 标题检测正则（行首匹配，用于识别章节标题作为分块边界）
_PDF_HEADING_PATTERN = re.compile(
    r"^(?:"
    r"第[一二三四五六七八九十百千]+[章节条]"            # 第一章/第一节
    r"|[一二三四五六七八九十]+[、.]"                    # 一、 二.
    r"|\d+[.\s]"                                       # 1. / 1 （注意要有标点或空格，避免匹配"12345"）
    r"|[（(]\d+[）)]"                                  # （1） (1)
    r"|[【\[《「『]"                                  # 引号类开头
    r")"
)


def _chunk_pdf(text: str, chunk_size: int, chunk_overlap: int) -> List[tuple[int, int, str, int, str]]:
    """PDF 专用分块：按页 + 标题层级 + 段落切分。

    相比 _chunk_text 的改进：
    - 按 `--- Page N ---` 标记切分页面，保留页码到 chunk
    - 在每页内识别标题行（第N章/一、/1./（1）等）作为分块边界
    - 段落 + 滑动窗口二级切分

    Returns:
        [(start_char, end_char, sub_text, page_num, heading), ...]
    """
    if not text:
        return []

    # 按 `--- Page N ---` 切分页面
    # 用 finditer 找到所有页码标记，每两个标记之间是一页内容
    markers = list(_PDF_PAGE_MARKER.finditer(text))
    if not markers:
        # 没有页码标记（可能是 OCR 单页），回退到通用分块但加默认页码 1
        pieces_text = _chunk_text(text, chunk_size, chunk_overlap)
        return [(s, e, t, 1, "") for s, e, t in pieces_text]

    pieces: list[tuple[int, int, str, int, str]] = []
    # 处理第一页之前的文本（如果有）
    if markers[0].start() > 0:
        pre_text = text[: markers[0].start()].strip()
        if pre_text:
            sub_pieces = _chunk_text(pre_text, chunk_size, chunk_overlap)
            for s, e, t in sub_pieces:
                pieces.append((s, e, t, 1, ""))

    # 逐页处理
    for i, m in enumerate(markers):
        page_num = int(m.group(1))
        page_start = m.end()
        page_end = markers[i + 1].start() if i + 1 < len(markers) else len(text)
        # 修复偏移错位：strip() 会去掉前导/后缀空白，但 page_start 仍指向标记末尾，
        # 导致 abs_start 计算时把前导空白算进去，chunk.start_char 偏小。
        # 修正：记录前导空白长度，page_text 的实际起始位置 = page_start + leading_ws_len。
        raw_page_text = text[page_start:page_end]
        leading_ws_len = len(raw_page_text) - len(raw_page_text.lstrip())
        page_text = raw_page_text.strip()
        # page_text 在原 text 中的真实起始位置（用于后续 abs_start 计算）
        page_text_start = page_start + leading_ws_len

        if not page_text:
            continue

        # 在页内按标题切分章节
        sections = _split_pdf_page_by_headings(page_text)

        # 对每个 section 做二级切分
        # section_offset 基于 stripped page_text 内部累加
        section_offset = 0
        current_heading = ""
        for section_text, section_heading in sections:
            if section_heading:
                current_heading = section_heading
            # 在 section 内部用通用策略切分
            sub_pieces = _chunk_text(section_text, chunk_size, chunk_overlap)
            for local_s, local_e, sub_text in sub_pieces:
                # 用 page_text_start（修正后的位置）计算绝对偏移
                abs_start = page_text_start + section_offset + local_s
                abs_end = page_text_start + section_offset + local_e
                pieces.append((abs_start, abs_end, sub_text, page_num, current_heading))
            # section 之间用 \n 分隔（_split_pdf_page_by_headings 按行切分），
            # 但 _chunk_text 内部会做合并，section_text 长度是 stripped 后的，
            # 用 +1 估算分隔符（避免 +2 多算导致后续 section 偏移）
            section_offset += len(section_text) + 1  # +1 for \n separator

    return pieces


def _split_pdf_page_by_headings(page_text: str) -> List[tuple[str, str]]:
    """按标题行切分 PDF 单页内容。

    Returns:
        [(section_text, heading), ...]
        第一个 section 的 heading 可能是空字符串（标题之前的内容）
    """
    lines = page_text.split("\n")
    sections: list[tuple[str, str]] = []
    current_lines: list[str] = []
    current_heading = ""

    for line in lines:
        stripped = line.strip()
        # 检测标题行：短行 + 匹配标题模式 + 不是句子的延续
        is_heading = (
            stripped
            and len(stripped) <= 40
            and _PDF_HEADING_PATTERN.match(stripped)
            # 排除"1. 这是内容"这种可能是列表项的情况（标题通常更短且不含句号）
            and not stripped.endswith(("。", "！", "？", "；"))
        )

        if is_heading:
            # 先把当前累积的内容保存
            if current_lines:
                sections.append(("\n".join(current_lines).strip(), current_heading))
                current_lines = []
            current_heading = stripped
            # 标题行本身也加入下一节的开头（保留标题在内容中）
            current_lines.append(line)
        else:
            current_lines.append(line)

    if current_lines:
        sections.append(("\n".join(current_lines).strip(), current_heading))

    # 过滤空 section
    return [(s, h) for s, h in sections if s]


def _build_parent_chunks(chunks: List[Chunk], doc: ParsedDocument, parent_size: int = 2048) -> None:
    """为 chunks 生成 parent_content（small-to-big 检索用）。

    策略按 format_tag：
    - excel/ppt: 每个 child 的 parent 就是其所属 sheet/slide 的全部内容
    - pdf: 按 page_num 分组，同页 child 合并为 parent（不跨页拼接）
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
        # Excel: 按 `[SheetName]` 边界分组，同 sheet 内按容量二次切分
        _group_by_excel_sheet(chunks, parent_size)
    elif format_tag == "pdf":
        # PDF: 按 page_num 分组，同页 child 合并为 parent
        _group_by_pdf_page(chunks, parent_size)
    elif format_tag == "docx":
        # DOCX: 按 heading 分组，同章节 child 合并为 parent
        _group_by_docx_heading(chunks, parent_size)
    elif format_tag == "markdown":
        # Markdown: 按 `#` 标题分组，同章节 child 合并为 parent
        _group_by_markdown_heading(chunks, parent_size)
    else:
        # image/html/text: 按 parent_size 容量合并相邻 child
        _group_by_capacity(chunks, parent_size)


def _group_by_pdf_page(chunks: List[Chunk], parent_size: int) -> None:
    """PDF parent: 按 page_num 分组，同页 child 合并为 parent。

    相比 _group_by_capacity 的改进：
    - 不跨页拼接，避免不同页内容混合
    - 单页 child 数过多时按 parent_size 容量二次分组（避免 parent 过长）
    - 同页内若 chunk 有 heading，按 heading 二次分组（同章节优先合并）
    """
    if not chunks:
        return

    # 按 page_num 分组
    page_groups: dict[int, list[int]] = {}
    for i, c in enumerate(chunks):
        page_groups.setdefault(c.page_num, []).append(i)

    for page_num, idxs in page_groups.items():
        if not idxs:
            continue

        # 单页只有一个 chunk：parent 就是自己
        if len(idxs) == 1:
            chunks[idxs[0]].parent_content = chunks[idxs[0]].content
            continue

        # 若同页 chunk 数较多，按 heading 二次分组
        # 估算单组最大 chunk 数：parent_size // 512
        max_per_group = max(1, parent_size // 512)

        # 按 heading 分组（同 heading 的 chunk 优先合并）
        heading_subgroups: list[list[int]] = []
        current_subgroup: list[int] = [idxs[0]]
        current_heading = chunks[idxs[0]].heading

        for idx in idxs[1:]:
            # 新 heading 或当前组已满 → 开新组
            if (chunks[idx].heading and chunks[idx].heading != current_heading) or len(current_subgroup) >= max_per_group:
                heading_subgroups.append(current_subgroup)
                current_subgroup = [idx]
                current_heading = chunks[idx].heading
            else:
                current_subgroup.append(idx)
        if current_subgroup:
            heading_subgroups.append(current_subgroup)

        # 每个 subgroup 合并为 parent
        for subgroup in heading_subgroups:
            if len(subgroup) == 1:
                chunks[subgroup[0]].parent_content = chunks[subgroup[0]].content
            else:
                merged = "\n\n".join(chunks[i].content for i in subgroup)
                for i in subgroup:
                    chunks[i].parent_content = merged


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


def _group_by_excel_sheet(chunks: List[Chunk], parent_size: int = 2048) -> None:
    """Excel parent: 按 `[SheetName]` 边界分组，同 sheet 内按容量二次切分。

    改进：单 sheet 行数过多时（如政策汇集表 200+ 行），按 parent_size
    容量二次分组，避免 parent_content 过大导致 reranker 截断。
    """
    import re
    sheet_groups: dict[str, list[int]] = {}
    current_sheet = "default"
    for i, c in enumerate(chunks):
        # 检测 chunk 中出现的 sheet 标记
        m = re.match(r"^\[([^\]]+)\]", c.content)
        if m:
            current_sheet = m.group(1)
        sheet_groups.setdefault(current_sheet, []).append(i)

    max_per_group = max(1, parent_size // 512)

    for sheet, idxs in sheet_groups.items():
        if not idxs:
            continue
        if len(idxs) == 1:
            chunks[idxs[0]].parent_content = chunks[idxs[0]].content
            continue
        # 按 max_per_group 二次分组
        for start_idx in range(0, len(idxs), max_per_group):
            subgroup = idxs[start_idx:start_idx + max_per_group]
            if len(subgroup) == 1:
                chunks[subgroup[0]].parent_content = chunks[subgroup[0]].content
            else:
                merged = "\n".join(chunks[i].content for i in subgroup)
                for i in subgroup:
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


def _group_by_docx_heading(chunks: List[Chunk], parent_size: int) -> None:
    """DOCX parent: 按 heading 分组，同章节 child 合并为 parent。

    策略类似 _group_by_pdf_page 的 heading 二次分组：
    - 按 chunk.heading 分组（相同 heading 的 chunk 合并）
    - heading 为空的 chunk 单独成组或与相邻组合并（按容量）
    - 单组 chunk 数过多时按 parent_size 容量二次分组
    """
    if not chunks:
        return

    # 第一阶段：按 heading 分组（保持顺序）
    # heading 为空视为"无标题组"，与相邻同状态 chunk 合并
    heading_groups: list[list[int]] = []
    current_group: list[int] = [0]
    current_heading = chunks[0].heading

    for i in range(1, len(chunks)):
        # 新 heading（非空且与当前不同）→ 开新组
        if chunks[i].heading and chunks[i].heading != current_heading:
            heading_groups.append(current_group)
            current_group = [i]
            current_heading = chunks[i].heading
        else:
            current_group.append(i)
    if current_group:
        heading_groups.append(current_group)

    # 第二阶段：每组内若 chunk 数过多，按 parent_size 容量二次分组
    max_per_group = max(1, parent_size // 512)

    for group in heading_groups:
        if not group:
            continue
        # 单 chunk 独占组：parent 就是自己
        if len(group) == 1:
            chunks[group[0]].parent_content = chunks[group[0]].content
            continue
        # 多 chunk：若超出容量则二次切分
        for start_idx in range(0, len(group), max_per_group):
            subgroup = group[start_idx:start_idx + max_per_group]
            if len(subgroup) == 1:
                chunks[subgroup[0]].parent_content = chunks[subgroup[0]].content
            else:
                merged = "\n\n".join(chunks[i].content for i in subgroup)
                for i in subgroup:
                    chunks[i].parent_content = merged


# Markdown 标题行检测正则（用于 parent 分组识别章节边界）
_MD_HEADING_PATTERN = re.compile(r"^(#{1,6})\s+(.+)$")


def _group_by_markdown_heading(chunks: List[Chunk], parent_size: int) -> None:
    """Markdown parent: 按 `#` 标题分组，同章节 child 合并为 parent。

    策略：
    - 扫描每个 chunk content 开头的 `#` 标题行，识别章节边界
    - 同一 `#` 标题下的所有 chunk 合并为 parent
    - 无标题的 chunk（开头不是 #）与前一组合并或单独成组
    - 单组 chunk 数过多时按 parent_size 容量二次分组
    """
    if not chunks:
        return

    # 第一阶段：按章节分组
    # 检测每个 chunk 开头是否是 `#` 标题行（章节起点）
    heading_groups: list[list[int]] = []
    current_group: list[int] = [0]
    current_has_heading = bool(_MD_HEADING_PATTERN.match(chunks[0].content.split("\n", 1)[0]))

    for i in range(1, len(chunks)):
        first_line = chunks[i].content.split("\n", 1)[0]
        is_heading = bool(_MD_HEADING_PATTERN.match(first_line))
        # 遇到新标题行 → 开新组
        if is_heading:
            heading_groups.append(current_group)
            current_group = [i]
            current_has_heading = True
        else:
            current_group.append(i)
    if current_group:
        heading_groups.append(current_group)

    # 第二阶段：按容量二次分组
    max_per_group = max(1, parent_size // 512)

    for group in heading_groups:
        if not group:
            continue
        if len(group) == 1:
            chunks[group[0]].parent_content = chunks[group[0]].content
            continue
        for start_idx in range(0, len(group), max_per_group):
            subgroup = group[start_idx:start_idx + max_per_group]
            if len(subgroup) == 1:
                chunks[subgroup[0]].parent_content = chunks[subgroup[0]].content
            else:
                merged = "\n\n".join(chunks[i].content for i in subgroup)
                for i in subgroup:
                    chunks[i].parent_content = merged


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
    pdf_pieces: list[tuple[int, int, str, int, str]] = []
    docx_pieces: list[tuple[int, int, str, str]] = []
    if format_tag == "excel":
        pieces = _chunk_excel(text, chunk_size, chunk_overlap)
    elif format_tag == "ppt":
        pieces = _chunk_ppt(text, chunk_size, chunk_overlap)
    elif format_tag == "markdown":
        pieces = _chunk_markdown(text, chunk_size, chunk_overlap)
    elif format_tag == "pdf":
        # PDF 专用分块，返回 5 元组 (start, end, text, page_num, heading)
        pdf_pieces = _chunk_pdf(text, chunk_size, chunk_overlap)
        pieces = [(s, e, t) for s, e, t, _, _ in pdf_pieces]
    elif format_tag == "docx":
        # DOCX 专用分块，返回 4 元组 (start, end, text, heading)
        docx_pieces = _chunk_docx(text, chunk_size, chunk_overlap)
        pieces = [(s, e, t) for s, e, t, _ in docx_pieces]
    else:
        # image / html / text 沿用通用策略
        pieces = _chunk_text(text, chunk_size, chunk_overlap)

    chunks: list[Chunk] = []
    for idx, (start, end, sub_text) in enumerate(pieces):
        sub_text = sub_text.strip()
        if sub_text:
            page_num = pdf_pieces[idx][3] if pdf_pieces and idx < len(pdf_pieces) else 0
            heading = ""
            if pdf_pieces and idx < len(pdf_pieces):
                heading = pdf_pieces[idx][4]
            elif docx_pieces and idx < len(docx_pieces):
                heading = docx_pieces[idx][3]
            chunks.append(
                Chunk(
                    content=sub_text,
                    index=idx,
                    start_char=start,
                    end_char=end,
                    token_count=_estimate_tokens(sub_text),
                    page_num=page_num,
                    heading=heading,
                )
            )

    # 为每个 chunk 生成 parent_content（small-to-big 检索用）
    _build_parent_chunks(chunks, doc)

    return chunks

"""Parent-Document 上下文扩展（small-to-big 版）：检索小 chunk，返回大上下文。

核心思想（来自 LlamaIndex ParentDocumentRetriever）：
- 检索时用小 chunk（精确匹配，chunk_size=512）
- 返回时扩展为 parent context（与格式结构对齐的大粒度内容）
- 解决"小 chunk 丢失上下文"问题，让 LLM 有更完整的信息做回答

升级版（small-to-big）：
- 入库时每个 chunk 已生成 parent_content（同 sheet/slide/章节的所有 child 合并）
- 检索时优先使用 chunk 自身的 parent_content
- 无 parent_content 时降级到旧的 window 方式（前后各 N 个相邻 chunk 合并）

集成点：RAGChain.ask() 在检索后、构造 prompt 前调用 enrich_results，
把 parent context 附加到 HybridResult.content 后面（用分隔符标记）。
"""
from __future__ import annotations

import logging
from typing import Dict, List, Optional, Tuple

from config import settings

logger = logging.getLogger(__name__)

# 分隔符：区分原始匹配片段和扩展上下文
_PARENT_SEPARATOR = "\n\n[上下文]\n"


def get_parent_context(
    storage,
    doc_id: str,
    chunk_index: int,
    window: int = 1,
) -> str:
    """获取单个 chunk 的 parent context（前后各 window 个相邻 chunk 合并）。

    Args:
        storage: Storage 实例（用于查询 chunks 表）
        doc_id: 文档 ID
        chunk_index: 当前 chunk 在文档中的序号（0-based）
        window: 前后各取多少个相邻 chunk

    Returns:
        合并后的上下文文本（不含当前 chunk 本身），无相邻 chunk 时返回空字符串
    """
    if window <= 0:
        return ""

    try:
        chunks = storage.get_chunks(doc_id)
    except Exception as e:
        logger.warning(f"获取 parent context 失败 doc={doc_id}: {e}")
        return ""

    if not chunks:
        return ""

    # chunks 按 index_in_doc 排序
    start = max(0, chunk_index - window)
    end = min(len(chunks), chunk_index + window + 1)

    # 收集相邻 chunk（排除当前 chunk 本身）
    parts: list[str] = []
    for c in chunks[start:end]:
        if c.index == chunk_index:
            continue
        parts.append(c.content.strip())

    return "\n\n".join(parts) if parts else ""


def enrich_results(
    storage,
    results: List,
    window: Optional[int] = None,
) -> List:
    """批量给检索结果附加 parent context（small-to-big 优先）。

    策略：
    1. 优先使用 chunk 自身的 parent_content（与格式结构对齐的大粒度内容）
    2. 无 parent_content 时降级到 window 方式（前后各 N 个相邻 chunk 合并）

    高效实现：按 doc_id 分组，每组只查一次 chunks，避免 N+1 查询。

    Args:
        storage: Storage 实例
        results: HybridResult 列表（会被原地修改 content）
        window: 前后窗口大小，None 时用 settings.parent_window

    Returns:
        附加了 parent context 的 results（同一列表对象）
    """
    if not results:
        return results

    w = window if window is not None else getattr(settings, "parent_window", 1)

    # 按 doc_id 分组，收集需要查询的 doc_id（保持顺序去重）
    doc_ids = list(dict.fromkeys(r.doc_id for r in results if r.doc_id))
    if not doc_ids:
        return results

    # 批量查询每个 doc 的所有 chunk（按 doc_id 分组，每组一次查询）
    doc_chunks: Dict[str, List] = {}
    for doc_id in doc_ids:
        try:
            doc_chunks[doc_id] = storage.get_chunks(doc_id)
        except Exception as e:
            logger.warning(f"批量查询 chunks 失败 doc={doc_id}: {e}")
            doc_chunks[doc_id] = []

    # 从 chunk_id 解析 index：chunk_id 格式为 "{doc_id}_{index}"
    for r in results:
        if not r.doc_id or not r.chunk_id:
            continue
        chunks = doc_chunks.get(r.doc_id, [])
        if not chunks:
            continue

        # 解析当前 chunk 的 index
        try:
            current_idx = None
            current_chunk = None
            for c in chunks:
                if c.id == r.chunk_id:
                    current_idx = c.index
                    current_chunk = c
                    break
            if current_idx is None:
                # 回退：从 chunk_id 末尾解析
                parts = r.chunk_id.rsplit("_", 1)
                if len(parts) == 2 and parts[0] == r.doc_id:
                    current_idx = int(parts[1])
                else:
                    continue
        except (ValueError, IndexError):
            continue

        # 优先策略 1：使用 chunk 自身的 parent_content（small-to-big）
        # 但对 excel 格式跳过：Excel 每个 chunk 已是完整的行记录，
        # parent_content 是整 sheet 全文，替换后会丢失精确匹配信息
        # （所有 chunk 都被替换成同一份 sheet 全文，再被压缩成相同前缀）
        if current_chunk is not None:
            parent_content = getattr(current_chunk, "parent_content", "")
            if parent_content and parent_content.strip():
                # 检查 format_tag，excel 行级 chunk 不做 parent 替换
                fmt = getattr(r, "format_tag", "") or ""
                if fmt == "excel":
                    continue
                # parent_content 包含当前 chunk 本身，直接替换 content
                # 不再追加，而是用更完整的 parent 替代
                if len(parent_content) > len(r.content):
                    r.content = parent_content.strip()
                continue

        # 降级策略 2：window 方式（前后各 N 个相邻 chunk 合并）
        if w <= 0:
            continue

        start = max(0, current_idx - w)
        end = min(len(chunks), current_idx + w + 1)

        parts: list[str] = []
        for c in chunks[start:end]:
            if c.index == current_idx:
                continue
            text = c.content.strip()
            if text:
                parts.append(text)

        if parts:
            parent_text = "\n\n".join(parts)
            # 附加到 content 后面，用分隔符标记
            r.content = f"{r.content}{_PARENT_SEPARATOR}{parent_text}"

    return results

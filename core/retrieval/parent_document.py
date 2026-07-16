"""Parent-Document 上下文扩展：检索小 chunk，返回大上下文。

核心思想（来自 LlamaIndex ParentDocumentRetriever）：
- 检索时用小 chunk（精确匹配，chunk_size=512）
- 返回时扩展为 parent context（前后各 window 个相邻 chunk 合并）
- 解决"小 chunk 丢失上下文"问题，让 LLM 有更完整的信息做回答

无 schema 变更：利用现有 chunks 表的 doc_id + index_in_doc 计算相邻 chunk。

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
    """批量给检索结果附加 parent context。

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
    if w <= 0:
        return results

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
            # chunk_id = "doc_id_index"，但 doc_id 本身可能含下划线
            # 更可靠的方式：在 chunks 列表中按 chunk_id 查找
            current_idx = None
            for c in chunks:
                if c.id == r.chunk_id:
                    current_idx = c.index
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

        # 收集相邻 chunk
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

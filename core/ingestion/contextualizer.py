"""Contextual Retrieval（Anthropic 2024）实现。

为每个 chunk 用 LLM 生成 50-100 字「该 chunk 在文档中的位置与作用」摘要，
前缀到 chunk content 后再 embed，让向量嵌入感知全局上下文。

效果（Anthropic 官方数据）：
- 检索失败率降低 49%
- 配合 rerank 降低 67%

成本控制：
- 摘要 prompt 简短（< 200 tokens 输入 + < 100 tokens 输出）
- 失败 chunk 跳过（不阻塞入库）
- 可通过开关禁用
"""
from __future__ import annotations

import logging
from typing import List, Optional

from .chunker import Chunk
from .parser import ParsedDocument

logger = logging.getLogger(__name__)


# 摘要 prompt 模板（参考 Anthropic Contextual Retrieval）
_SYSTEM_PROMPT = """你是一个文档分析助手。请用 50-100 字描述以下片段在整个文档中的位置和作用。
重点说明：
1. 该片段讨论的主题
2. 与文档标题的关系
3. 关键信息点

直接输出摘要，不要加前缀和解释。"""

_USER_TEMPLATE = """文档标题：{title}
文档格式：{format_tag}
文档全文（截断到前 2000 字）：
{full_text}

请为以下片段生成摘要：
片段内容：
{chunk_content}

摘要："""


def _truncate(text: str, max_chars: int = 2000) -> str:
    """截断文本到指定字符数。"""
    if len(text) <= max_chars:
        return text
    return text[:max_chars] + "...[截断]"


def generate_context_for_chunk(
    chunk: Chunk,
    doc: ParsedDocument,
    llm_client,
    max_retries: int = 1,
) -> Optional[str]:
    """为单个 chunk 生成上下文摘要。

    Args:
        chunk: 待处理的分块
        doc: 所属文档（提供全文上下文）
        llm_client: LLMClient 实例
        max_retries: 失败重试次数（默认 1）

    Returns:
        上下文摘要文本，失败返回 None
    """
    messages = [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {
            "role": "user",
            "content": _USER_TEMPLATE.format(
                title=doc.title,
                format_tag=getattr(doc, "format_tag", "text"),
                full_text=_truncate(doc.text),
                chunk_content=chunk.content,
            ),
        },
    ]
    try:
        summary = llm_client.chat(
            messages=messages,
            temperature=0.0,  # 摘要要确定性
            max_tokens=150,
            max_retries=max_retries,
        )
        summary = summary.strip()
        if not summary:
            return None
        return summary
    except Exception as e:
        logger.warning(f"为 chunk {chunk.index} 生成上下文摘要失败: {type(e).__name__}: {e}")
        return None


def contextualize_chunks(
    chunks: List[Chunk],
    doc: ParsedDocument,
    llm_client=None,
    enabled: bool = True,
) -> List[Chunk]:
    """为 chunks 列表批量生成上下文摘要并前缀到 content。

    原地修改 chunks 的 content 字段（前缀摘要），返回同一列表。
    失败的 chunk 保持原样（不阻塞入库）。

    Args:
        chunks: 待处理的分块列表
        doc: 所属文档
        llm_client: LLM 客户端（None 时不做处理）
        enabled: 是否启用（默认 True，可通过配置关闭）

    Returns:
        处理后的 chunks 列表（与输入同一对象）
    """
    if not enabled or llm_client is None or not chunks:
        return chunks

    success_count = 0
    for chunk in chunks:
        summary = generate_context_for_chunk(chunk, doc, llm_client)
        if summary:
            # 摘要前缀到 content，用分隔符隔开
            # 注意：BM25 索引也会看到这个前缀（提升关键词召回）
            chunk.content = f"[文档上下文] {summary}\n[内容] {chunk.content}"
            success_count += 1

    logger.info(
        f"Contextual Retrieval 完成: {success_count}/{len(chunks)} chunks 成功生成摘要"
    )
    return chunks

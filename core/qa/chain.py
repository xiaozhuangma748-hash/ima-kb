"""RAG 问答链：混合检索 + LLM 生成 + 引用溯源。

流程（优化后）：
1. 用户提问（可选：带上文摘要做 query expansion）
2. HybridRetriever 检索（BM25 + 向量 + RRF 融合）
3. LLM 重排序（可选，top_n=5）
4. 置信度检查：最高分低于阈值则提示"资料不足"
5. 构造结构化 Prompt（标题 + 摘要 + 原文）
6. LLM 基于资料回答，标注引用编号
7. 返回回答 + 引用列表

支持：
- 多轮对话 query expansion（结合上文）
- 检索置信度阈值（低于阈值主动提示）
- 流式/同步两种模式
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Iterator, List, Optional, Tuple

from config import settings
from core.llm.client import get_llm, LLMError
from core.llm.degrade import get_llm_degrade_message
from core.storage import Storage
from core.retrieval.hybrid import HybridRetriever, HybridResult
from core.retrieval.rerank import Reranker, RerankResult
from core.search.bm25 import BM25Index
from core.retrieval.vector import VectorIndex


@dataclass
class Answer:
    """RAG 问答结果。"""
    question: str
    content: str
    citations: List[dict] = field(default_factory=list)
    retrieved: List[HybridResult] = field(default_factory=list)
    reranked: List[RerankResult] = field(default_factory=list)
    confidence: float = 0.0  # 最高检索结果的分数
    low_confidence: bool = False  # 是否低于置信度阈值

    @property
    def has_answer(self) -> bool:
        return bool(self.content.strip())


# ---- 置信度阈值（可配置） ----
DEFAULT_CONFIDENCE_THRESHOLD = 0.01  # RRF 分数阈值，低于此值认为资料不足


SYSTEM_PROMPT = """你是一个专业的知识库问答助手。请严格根据下面提供的"参考资料"回答用户问题。

回答要求：
1. 只使用参考资料中的信息，不要编造或使用外部知识
2. 如果参考资料不足以回答问题，请明确说明"根据现有资料无法回答该问题，建议入库相关文档"
3. 回答时在相关内容后用 [1] [2] 这样的编号标注引用来源
4. 用中文回答，条理清晰，必要时分点说明
5. 如果问题涉及具体数字、政策、金额，请准确引用原文
6. 参考资料中如果有"摘要"字段，先看摘要判断相关性，再看原文
"""


def _build_user_prompt(
    question: str,
    results: List[HybridResult],
    confidence_threshold: float = DEFAULT_CONFIDENCE_THRESHOLD,
) -> Tuple[str, bool]:
    """构造用户提示词：把检索结果作为参考资料。

    Returns:
        (prompt_text, low_confidence_flag)
    """
    if not results:
        return (
            f"问题：{question}\n\n（未检索到相关资料，请告知用户无法回答）",
            True,
        )

    # 检查置信度
    max_score = results[0].score if results else 0.0
    low_conf = max_score < confidence_threshold

    parts = [f"请根据以下参考资料回答问题。\n"]
    parts.append("=" * 50)
    parts.append("【参考资料】")

    if low_conf:
        parts.append(
            "\n⚠️ 注意：检索结果相关度较低，"
            "请谨慎回答，不确定时告知用户资料不足。\n"
        )

    for i, r in enumerate(results, 1):
        parts.append(f"\n[{i}] 来源：{r.doc_title}")
        parts.append(f"    相关度：{r.score:.4f} (来源: {r.source})")
        parts.append(f"    内容：{r.content}")

    parts.append("\n" + "=" * 50)
    parts.append(f"\n【用户问题】\n{question}")

    return "\n".join(parts), low_conf


def _expand_query(query: str, history: List[dict], max_words: int = 30) -> str:
    """多轮对话 query 扩展：从上文中提取关键词补充到当前查询。

    策略：
    1. 取最近一轮 AI 回答中的关键名词（启发式：提取中文名词片段）
    2. 附加到原 query 后面

    Args:
        query: 当前用户问题
        history: 对话历史（message list）
        max_words: 从上下文中提取的最大词数

    Returns:
        扩展后的查询字符串
    """
    if not history:
        return query

    # 取最近一轮 AI 回答（assistant 消息）
    last_assistant = None
    for msg in reversed(history):
        if msg.get("role") == "assistant":
            last_assistant = msg.get("content", "")
            break

    if not last_assistant:
        return query

    # 简单启发式：从 AI 回答中提取可能的关键词
    # 策略：提取引用过的文档标题中的关键词 + 回答中的名词
    keywords = []

    # 1. 从回答中提取 [n] 引用关联的潜在关键词
    #    （不精确，但比没有好）
    # 2. 取 AI 回答的前 3 个短句（通常包含核心信息）
    sentences = re.split(r'[。！？\n]', last_assistant)
    for s in sentences[:3]:
        s = s.strip()
        if 5 <= len(s) <= max_words:
            keywords.append(s)

    if keywords:
        expanded = query + " " + " ".join(keywords)
        return expanded

    return query


class RAGChain:
    """RAG 问答链（混合检索版）。"""

    def __init__(
        self,
        storage: Optional[Storage] = None,
        hybrid_retriever: Optional[HybridRetriever] = None,
        reranker: Optional[Reranker] = None,
    ) -> None:
        self.storage = storage or Storage()

        # 优先使用传入的混合检索器，否则自建
        if hybrid_retriever is not None:
            self.hybrid = hybrid_retriever
        else:
            self.hybrid = HybridRetriever(
                bm25_index=self.storage.bm25,
                vector_index=self.storage.vector,
            )

        # 重排序器
        if reranker is not None:
            self.reranker = reranker
        else:
            try:
                self.reranker = Reranker(llm=get_llm())
            except LLMError:
                self.reranker = None

        self.llm = get_llm()

    def ask(
        self,
        question: str,
        top_k: Optional[int] = None,
        history: Optional[List[dict]] = None,
    ) -> Answer:
        """同步问答。

        Args:
            question: 用户问题
            top_k: 检索候选数（默认用配置 RAG_TOP_K）
            history: 多轮对话历史（用于 query expansion）

        Returns:
            Answer 对象
        """
        # 1. Query expansion（多轮对话时结合上文）
        query = question
        if history:
            query = _expand_query(question, history)

        # 2. 混合检索
        k = top_k or settings.rag_top_k
        results = self.hybrid.search(query, top_k=k)

        if not results:
            return Answer(
                question=question,
                content="根据现有资料无法回答该问题。建议入库相关文档后再试。",
                low_confidence=True,
            )

        # 3. LLM 重排序（如果可用）
        reranked = []
        if self.reranker:
            try:
                reranked = self.reranker.rerank(query, results, top_n=min(5, len(results)))
            except Exception as e:
                # 重排序失败，保留原混合结果
                reranked = results

        # 4. 确定最终使用的结果
        final_results = reranked if reranked else results

        # 5. 构造 Prompt
        user_prompt, low_conf = _build_user_prompt(
            question, final_results,
            confidence_threshold=settings.rag_top_k * 0.001,  # 动态阈值
        )

        # 6. LLM 生成
        try:
            content = self.llm.chat(
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0.2,
            )
        except LLMError as e:
            degrade_msg = get_llm_degrade_message(
                error=e, has_sources=bool(final_results),
                source_count=len(final_results),
            )
            return Answer(
                question=question, content=degrade_msg,
                retrieved=final_results, reranked=reranked,
                citations=[{"error": str(e)}],
                low_confidence=low_conf,
            )

        # 7. 构造引用列表
        citations = [
            {
                "index": i + 1,
                "doc_title": r.doc_title,
                "doc_id": r.chunk_id,  # HybridResult 的 chunk_id 作为引用标识
                "score": round(r.score, 4),
                "source": r.source,
                "preview": r.content[:150] + ("..." if len(r.content) > 150 else ""),
            }
            for i, r in enumerate(final_results)
        ]

        # 8. 计算置信度
        confidence = final_results[0].score if final_results else 0.0

        return Answer(
            question=question,
            content=content,
            citations=citations,
            retrieved=final_results,
            reranked=reranked,
            confidence=confidence,
            low_confidence=low_conf,
        )

    def ask_stream(
        self,
        question: str,
        top_k: Optional[int] = None,
        history: Optional[List[dict]] = None,
    ) -> Iterator[str]:
        """流式问答。

        Yields:
            文本片段（含进度提示）
        """
        # 1. Query expansion
        query = question
        if history:
            query = _expand_query(question, history)

        # 2. 混合检索
        k = top_k or settings.rag_top_k
        results = self.hybrid.search(query, top_k=k)

        yield f"\n🔍 检索到 {len(results)} 条相关资料：\n"
        for i, r in enumerate(results, 1):
            yield f"   [{i}] {r.doc_title} (相关度 {r.score:.4f}, 来源: {r.source})\n"

        if not results:
            yield "\n🤖 根据现有资料无法回答该问题。\n"
            return

        yield "\n🤖 正在生成回答...\n\n"

        # 3. 重排序
        reranked = []
        if self.reranker:
            try:
                reranked = self.reranker.rerank(query, results, top_n=min(5, len(results)))
            except Exception:
                pass

        final_results = reranked if reranked else results

        # 4. 构造 Prompt
        user_prompt, low_conf = _build_user_prompt(
            question, final_results,
        )
        if low_conf:
            yield "⚠️ 注意：检索结果相关度较低，回答可能不够准确。\n\n"

        # 5. 流式生成
        try:
            for token in self.llm.chat_stream(
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0.2,
            ):
                yield token
        except LLMError as e:
            yield f"\n\n{get_llm_degrade_message(error=e, has_sources=True, source_count=len(final_results))}"

        # 6. 输出引用
        yield "\n\n" + "=" * 50 + "\n"
        yield "📚 引用来源：\n"
        for i, r in enumerate(final_results, 1):
            yield f"   [{i}] {r.doc_title} (相关度 {r.score:.4f})\n"
            yield f"       {r.content[:100]}...\n"

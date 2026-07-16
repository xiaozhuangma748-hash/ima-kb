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
from core.retrieval.rerank import Reranker, RerankResult, create_reranker
from core.retrieval.query_transform import transform_query, QueryTransformResult
from core.retrieval.parent_document import enrich_results as enrich_parent_context
from core.retrieval.context_optimizer import (
    reorder_lost_in_middle,
    compress_results,
)
from core.qa.citation_validator import validate_answer
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
# RRF 分数阈值：低于此值认为资料不足，主动提示用户
# 原 0.01 过低，几乎不触发；0.05 是 RRF K=30 下 top-3 的经验下界
DEFAULT_CONFIDENCE_THRESHOLD = 0.05


SYSTEM_PROMPT = """你是一个专业的知识库问答助手。请严格根据下面提供的"参考资料"回答用户问题。

回答要求：
1. 只使用参考资料中的信息，不要编造或使用外部知识
2. 如果参考资料不足以回答问题，请明确说明"根据现有资料无法回答该问题，建议入库相关文档"
3. 回答时在相关内容后用 [1] [2] 这样的编号标注引用来源
4. 用中文回答，条理清晰，必要时分点说明
5. 如果问题涉及具体数字、政策、金额，请准确引用原文
6. 参考资料中如果有"摘要"字段，先看摘要判断相关性，再看原文
7. 如果参考资料与问题无关，不要用 [n] 标注引用，直接用自身知识回答即可
"""


def _build_user_prompt(
    question: str,
    results: List[HybridResult],
    confidence_threshold: float = DEFAULT_CONFIDENCE_THRESHOLD,
) -> Tuple[str, bool]:
    """构造用户提示词：把检索结果作为参考资料。

    [n] 编号按传入 results 的顺序分配。调用方负责重排和压缩。
    low_conf 用 max(score) 判断，不依赖顺序。

    Returns:
        (prompt_text, low_confidence_flag)
    """
    if not results:
        return (
            f"问题：{question}\n\n（未检索到相关资料，请告知用户无法回答）",
            True,
        )

    # 检查置信度（用最高分，不依赖顺序，重排后也正确）
    max_score = max((r.score for r in results), default=0.0)
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
                storage=self.storage,
            )

        # 重排序器
        if reranker is not None:
            self.reranker = reranker
        else:
            # 通过工厂创建：优先 Cross-Encoder，失败降级 LLM
            self.reranker = create_reranker()

        self.llm = get_llm()

    def _multi_query_retrieve(
        self,
        sub_queries: List[str],
        top_k: int,
        doc_ids: Optional[List[str]] = None,
    ) -> List[HybridResult]:
        """多查询并行检索 + 去重合并。

        对每个子问题分别调用 hybrid.search，按 chunk_id 去重，
        合并后取分数最高的 top_k 条。

        Args:
            sub_queries: 子问题列表
            top_k: 每个子问题检索的候选数
            doc_ids: 元数据预过滤（可选）

        Returns:
            合并去重后的 HybridResult 列表
        """
        if not sub_queries:
            return []
        if len(sub_queries) == 1:
            return self.hybrid.search(sub_queries[0], top_k=top_k, doc_ids=doc_ids)

        from concurrent.futures import ThreadPoolExecutor
        all_results: dict[str, HybridResult] = {}  # chunk_id -> result（保留最高分）

        def _search_one(q: str) -> List[HybridResult]:
            try:
                return self.hybrid.search(q, top_k=top_k, use_cache=False, doc_ids=doc_ids)
            except Exception as e:
                import logging
                logging.getLogger(__name__).warning(f"子问题检索失败 '{q[:30]}': {e}")
                return []

        # 并行检索
        with ThreadPoolExecutor(max_workers=min(4, len(sub_queries))) as ex:
            futures = [ex.submit(_search_one, q) for q in sub_queries]
            for f in futures:
                try:
                    for r in f.result(timeout=30):
                        if r.chunk_id not in all_results or r.score > all_results[r.chunk_id].score:
                            all_results[r.chunk_id] = r
                except Exception:
                    continue

        # 按分数排序取 top_k * 2（多查询召回更多，但 rerank 会精排）
        merged = sorted(all_results.values(), key=lambda r: r.score, reverse=True)
        return merged[:top_k * 2]

    def ask(
        self,
        question: str,
        top_k: Optional[int] = None,
        history: Optional[List[dict]] = None,
        enable_hyde: bool = True,
        enable_decompose: bool = True,
        doc_ids: Optional[List[str]] = None,
    ) -> Answer:
        """同步问答。

        Args:
            question: 用户问题
            top_k: 检索候选数（默认用配置 RAG_TOP_K）
            history: 多轮对话历史（用于 query expansion）
            enable_hyde: 启用 HyDE 假设答案改写
            enable_decompose: 启用子问题分解
            doc_ids: 元数据预过滤，只在这些文档中检索（None 不过滤）

        Returns:
            Answer 对象
        """
        # 1. Query 变换：HyDE + 子问题分解（替代旧的启发式 _expand_query）
        # 旧 _expand_query 仅在有 history 时触发；新机制对所有查询都适用
        try:
            transform_result = transform_query(
                question, llm=self.llm,
                enable_hyde=enable_hyde,
                enable_decompose=enable_decompose,
            )
        except Exception:
            # LLM 不可用时回退到原 query
            transform_result = QueryTransformResult(
                original=question, final_query=question,
                sub_queries=[question], used_hyde=False, used_decompose=False,
            )

        # 2. 混合检索（支持子问题多路并行 + 元数据预过滤）
        k = top_k or settings.rag_top_k
        sub_queries = transform_result.sub_queries
        if len(sub_queries) == 1:
            # 单查询：直接检索
            results = self.hybrid.search(sub_queries[0], top_k=k, doc_ids=doc_ids)
        else:
            # 多子问题：并行检索 + 去重合并
            results = self._multi_query_retrieve(sub_queries, k, doc_ids=doc_ids)

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
                top_n = min(settings.reranker_top_n, len(results))
                # 用原 question 做重排打分（不是改写后的 query）
                reranked = self.reranker.rerank(question, results, top_n=top_n)
            except Exception as e:
                # 重排序失败，保留原混合结果
                reranked = results

        # 4. 确定最终使用的结果
        final_results = reranked if reranked else results

        # 4.5 Parent-Document 上下文扩展
        # 重排后附加，避免 parent context 干扰重排打分
        if self.storage is not None and getattr(settings, "parent_window", 0) > 0:
            final_results = enrich_parent_context(self.storage, final_results)

        # 4.6 Lost in Middle 重排 + Context 压缩
        # 重排：最相关放两端，避免 LLM 忽略中间信息
        final_results = reorder_lost_in_middle(final_results)
        # 压缩：超长 content 截断
        max_chars = getattr(settings, "context_max_chars", 0)
        if max_chars > 0:
            compress_results(final_results, max_chars=max_chars)

        # 5. 构造 Prompt
        user_prompt, low_conf = _build_user_prompt(
            question, final_results,
            confidence_threshold=DEFAULT_CONFIDENCE_THRESHOLD,
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

        # 7. 构造引用列表（验证引用合法性后只保留 LLM 实际引用的文档）
        valid_citations, invalid_citations, citation_warning = validate_answer(
            content, len(final_results)
        )
        valid_set = set(valid_citations)
        citations = [
            {
                "index": i + 1,
                "doc_title": r.doc_title,
                "doc_id": r.chunk_id,
                "score": round(r.score, 4),
                "source": r.source,
                "preview": r.content[:150] + ("..." if len(r.content) > 150 else ""),
            }
            for i, r in enumerate(final_results)
            if (i + 1) in valid_set
        ]

        # 7.1 越界引用存在时，在答案末尾追加提示
        if invalid_citations:
            content = content + (
                f"\n\n（已忽略越界引用标记 {invalid_citations}，"
                f"参考资料共 {len(final_results)} 条）"
            )

        # 7.2 答案有实质内容但无合法引用时追加缺失提示
        if citation_warning:
            content = content + "\n\n" + citation_warning

        # 8. 计算置信度（用最高分，不依赖重排后的顺序）
        confidence = max((r.score for r in final_results), default=0.0) if final_results else 0.0

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
        enable_hyde: bool = True,
        enable_decompose: bool = True,
        doc_ids: Optional[List[str]] = None,
    ) -> Iterator[str]:
        """流式问答。

        Yields:
            文本片段（含进度提示）
        """
        # 1. Query 变换：HyDE + 子问题分解
        try:
            transform_result = transform_query(
                question, llm=self.llm,
                enable_hyde=enable_hyde,
                enable_decompose=enable_decompose,
            )
        except Exception:
            transform_result = QueryTransformResult(
                original=question, final_query=question,
                sub_queries=[question], used_hyde=False, used_decompose=False,
            )

        if transform_result.used_hyde:
            yield "🔧 已用 HyDE 改写查询\n"
        if transform_result.used_decompose:
            yield f"🔧 拆分为 {len(transform_result.sub_queries)} 个子问题\n"

        # 2. 混合检索（支持子问题多路并行 + 元数据预过滤）
        k = top_k or settings.rag_top_k
        sub_queries = transform_result.sub_queries
        if len(sub_queries) == 1:
            results = self.hybrid.search(sub_queries[0], top_k=k, doc_ids=doc_ids)
        else:
            results = self._multi_query_retrieve(sub_queries, k, doc_ids=doc_ids)

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
                top_n = min(settings.reranker_top_n, len(results))
                # 用原 question 做重排打分
                reranked = self.reranker.rerank(question, results, top_n=top_n)
            except Exception:
                pass

        final_results = reranked if reranked else results

        # 3.5 Parent-Document 上下文扩展
        if self.storage is not None and getattr(settings, "parent_window", 0) > 0:
            final_results = enrich_parent_context(self.storage, final_results)

        # 3.6 Lost in Middle 重排 + Context 压缩
        final_results = reorder_lost_in_middle(final_results)
        max_chars = getattr(settings, "context_max_chars", 0)
        if max_chars > 0:
            compress_results(final_results, max_chars=max_chars)

        # 4. 构造 Prompt
        user_prompt, low_conf = _build_user_prompt(
            question, final_results,
        )
        if low_conf:
            yield "⚠️ 注意：检索结果相关度较低，回答可能不够准确。\n\n"

        # 5. 流式生成（收集完整回答以过滤引用）
        full_content = []
        try:
            for token in self.llm.chat_stream(
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0.2,
            ):
                full_content.append(token)
                yield token
        except LLMError as e:
            yield f"\n\n{get_llm_degrade_message(error=e, has_sources=True, source_count=len(final_results))}"
            return

        # 6. 输出引用（验证引用合法性后只保留实际引用的文档）
        answer_text = "".join(full_content)
        valid_citations, invalid_citations, citation_warning = validate_answer(
            answer_text, len(final_results)
        )
        valid_set = set(valid_citations)
        cited_results = [
            r for i, r in enumerate(final_results)
            if (i + 1) in valid_set
        ]
        # 6.1 越界引用提示
        if invalid_citations:
            yield (
                f"\n\n（已忽略越界引用标记 {invalid_citations}，"
                f"参考资料共 {len(final_results)} 条）"
            )
        # 6.2 缺失引用提示
        if citation_warning:
            yield "\n\n" + citation_warning
        # 6.3 引用列表
        if cited_results:
            yield "\n\n" + "=" * 50 + "\n"
            yield "📚 引用来源：\n"
            for i, r in enumerate(cited_results, 1):
                yield f"   [{i}] {r.doc_title} (相关度 {r.score:.4f})\n"
                yield f"       {r.content[:100]}...\n"

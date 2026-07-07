"""RAG 问答链：检索 + LLM 生成 + 引用溯源。

流程：
1. 用户提问
2. BM25 检索 Top-K 相关分块
3. 构造 Prompt：把分块作为"参考资料"喂给 LLM
4. LLM 基于资料回答，标注引用编号
5. 返回回答 + 引用列表
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterator, List, Optional

from config import settings
from core.llm.client import get_llm, LLMError
from core.llm.degrade import get_llm_degrade_message
from core.storage import Storage
from core.search.bm25 import SearchResult


@dataclass
class Answer:
    """RAG 问答结果。"""
    question: str                                # 用户问题
    content: str                                 # LLM 回答内容
    citations: List[dict] = field(default_factory=list)  # 引用列表
    retrieved: List[SearchResult] = field(default_factory=list)  # 检索到的分块

    @property
    def has_answer(self) -> bool:
        return bool(self.content.strip())


SYSTEM_PROMPT = """你是一个专业的知识库问答助手。请严格根据下面提供的"参考资料"回答用户问题。

回答要求：
1. 只使用参考资料中的信息，不要编造或使用外部知识
2. 如果参考资料不足以回答问题，请明确说明"根据现有资料无法回答该问题"
3. 回答时在相关内容后用 [1] [2] 这样的编号标注引用来源
4. 用中文回答，条理清晰，必要时分点说明
5. 如果问题涉及具体数字、政策、金额，请准确引用原文
"""


def _build_user_prompt(question: str, results: List[SearchResult]) -> str:
    """构造用户提示词：把检索结果作为参考资料。"""
    if not results:
        return f"问题：{question}\n\n（未检索到相关资料，请告知用户无法回答）"

    parts = ["请根据以下参考资料回答问题。\n"]
    parts.append("=" * 50)
    parts.append("【参考资料】")
    for i, r in enumerate(results, 1):
        parts.append(f"\n[{i}] 来源：{r.doc_title}")
        parts.append(f"    内容：{r.content}")
    parts.append("\n" + "=" * 50)
    parts.append(f"\n【用户问题】\n{question}")
    return "\n".join(parts)


class RAGChain:
    """RAG 问答链。"""

    def __init__(self, storage: Optional[Storage] = None) -> None:
        self.storage = storage or Storage()
        self.llm = get_llm()

    def ask(self, question: str, top_k: Optional[int] = None) -> Answer:
        """同步问答。

        Args:
            question: 用户问题
            top_k: 检索候选数（默认用配置 RAG_TOP_K）

        Returns:
            Answer 对象
        """
        # 1. BM25 检索
        k = top_k or settings.rag_top_k
        results = self.storage.bm25_search(question, top_k=k)

        # 2. 构造 Prompt
        user_prompt = _build_user_prompt(question, results)

        # 3. LLM 生成
        try:
            content = self.llm.chat(
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0.2,  # 低温度，让回答更确定
            )
        except LLMError as e:
            # 降级：用统一文案填充 content，让调用方能感知失败原因
            degrade_msg = get_llm_degrade_message(
                error=e, has_sources=bool(results), source_count=len(results),
            )
            return Answer(question=question, content=degrade_msg, retrieved=results,
                          citations=[{"error": str(e)}])

        # 4. 构造引用列表
        citations = [
            {
                "index": i + 1,
                "doc_title": r.doc_title,
                "doc_id": r.doc_id,
                "chunk_id": r.chunk_id,
                "score": round(r.score, 3),
                "preview": r.content[:150] + ("..." if len(r.content) > 150 else ""),
            }
            for i, r in enumerate(results)
        ]

        return Answer(
            question=question,
            content=content,
            citations=citations,
            retrieved=results,
        )

    def ask_stream(self, question: str, top_k: Optional[int] = None) -> Iterator[str]:
        """流式问答：先输出检索信息，再流式输出 LLM 回答。

        Yields:
            文本片段（含进度提示）
        """
        # 1. 检索
        k = top_k or settings.rag_top_k
        results = self.storage.bm25_search(question, top_k=k)

        yield f"\n🔍 检索到 {len(results)} 条相关资料：\n"
        for i, r in enumerate(results, 1):
            yield f"   [{i}] {r.doc_title} (相关度 {r.score:.2f})\n"
        yield "\n🤖 正在生成回答...\n\n"

        if not results:
            yield "根据现有资料无法回答该问题。\n"
            return

        # 2. 构造 Prompt
        user_prompt = _build_user_prompt(question, results)

        # 3. 流式生成
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
            yield f"\n\n{get_llm_degrade_message(error=e, has_sources=bool(results), source_count=len(results))}"

        # 4. 输出引用
        yield "\n\n" + "=" * 50 + "\n"
        yield "📚 引用来源：\n"
        for i, r in enumerate(results, 1):
            yield f"   [{i}] {r.doc_title}\n"
            yield f"       {r.content[:100]}...\n"

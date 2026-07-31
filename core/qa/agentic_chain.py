"""Agentic RAG 链：多轮检索 + 反思。

组合模式包装 RAGChain：
1. 调用父类 ask() 获取首轮答案
2. Self-RAG 验证检测到幻觉 / 答案不充分时，LLM 反思改写 query
3. 用改写后的 query 再次调用父类 ask()
4. 最多 max_rounds 轮，防止死循环

不修改父类 RAGChain，零回归风险。
"""
from __future__ import annotations

import logging
from typing import List, Optional

from config import settings
from core.qa.chain import RAGChain, Answer
from core.qa.agentic_reflect import should_retry, reflect_and_rewrite_query

logger = logging.getLogger(__name__)


class AgenticRAGChain:
    """Agentic RAG 链（组合 RAGChain）。

    用法：
        chain = AgenticRAGChain(storage=storage)  # 自动读配置
        answer = chain.ask("问题")
    """

    def __init__(
        self,
        storage=None,
        chain: Optional[RAGChain] = None,
        enable_agentic: Optional[bool] = None,
        max_rounds: Optional[int] = None,
    ) -> None:
        # 创建或复用底层 RAGChain
        self.chain = chain or RAGChain(storage=storage)

        # 配置（None 时读 settings）
        if enable_agentic is None:
            enable_agentic = getattr(settings, "enable_agentic_rag", False)
        self.enable_agentic = enable_agentic

        if max_rounds is None:
            max_rounds = getattr(settings, "agentic_max_rounds", 2)
        self.max_rounds = max(max_rounds, 1)

    def _reflect(self, question: str, previous_answer: str, issues: str) -> str:
        """反思改写 query（包一层方便测试 mock）。"""
        return reflect_and_rewrite_query(
            question=question,
            previous_answer=previous_answer,
            issues=issues,
            llm=self.chain.llm,
        )

    def ask(
        self,
        question: str,
        top_k: Optional[int] = None,
        history: Optional[List[dict]] = None,
        enable_hyde: bool = True,
        enable_decompose: bool = True,
        doc_ids: Optional[List[str]] = None,
        cross_session_context: Optional[str] = None,
        summary: Optional[str] = None,
    ) -> Answer:
        """同步问答（支持多轮检索+反思）。

        参数与 RAGChain.ask() 完全一致，额外行为：
        - 当 enable_agentic=True 且 Self-RAG 检测到幻觉/答案不充分时，
          LLM 反思改写 query 重检索，最多 max_rounds 轮。
        """
        # 关闭 agentic 或 max_rounds=1：直接走单轮
        if not self.enable_agentic or self.max_rounds <= 1:
            return self.chain.ask(
                question=question,
                top_k=top_k,
                history=history,
                enable_hyde=enable_hyde,
                enable_decompose=enable_decompose,
                doc_ids=doc_ids,
                cross_session_context=cross_session_context,
                summary=summary,
            )

        # Agentic 多轮检索
        current_query = question
        current_answer: Optional[Answer] = None

        for round_num in range(1, self.max_rounds + 1):
            # 调用父类 ask（用当前 query）
            current_answer = self.chain.ask(
                question=current_query,
                top_k=top_k,
                history=history,
                enable_hyde=enable_hyde,
                enable_decompose=enable_decompose,
                doc_ids=doc_ids,
                cross_session_context=cross_session_context,
                summary=summary,
            )

            # 从 Answer 提取验证信息
            # Answer 不直接暴露 verify_result，但 RAGChain.ask 内部做完 Self-RAG
            # 验证后会把结果挂到 _verify_result（需要 RAGChain 配合）
            # 这里优先读 _verify_result，没有则用 content 中的 ⚠️ 标记判断
            verify_result = getattr(current_answer, "_verify_result", None)
            max_score = max(
                (getattr(r, "score", 0.0) for r in (current_answer.retrieved or [])),
                default=0.0,
            )

            # 判断是否需要重试
            if not should_retry(
                question=question,
                answer=current_answer.content or "",
                verify_result=verify_result,
                max_score=max_score,
                round_num=round_num,
                max_rounds=self.max_rounds,
            ):
                break

            # 反思改写 query
            issues = "答案检测到幻觉" if (verify_result and verify_result.has_hallucination) else "答案无法回答用户问题"
            logger.info(f"Agentic RAG 第 {round_num} 轮反思，原 query: {question[:30]}")
            current_query = self._reflect(
                question=question,
                previous_answer=current_answer.content or "",
                issues=issues,
            )
            logger.info(f"Agentic RAG 改写后 query: {current_query[:30]}")

        # 恢复原始 question（Answer.question 应为用户原始问题，不是改写后的 query）
        if current_answer is not None:
            current_answer.question = question
        return current_answer

    def ask_stream(self, question: str, **kwargs):
        """流式问答（Agentic RAG 不支持流式，直接转发父类）。

        Agentic 多轮检索需要完整答案才能判断是否反思，
        流式版退化为单轮（与关闭 agentic 等价）。
        """
        return self.chain.ask_stream(question=question, **kwargs)

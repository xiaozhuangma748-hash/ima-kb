"""Token 预算分配器。

按模型窗口大小分配 token 预算，超预算时自动截断。

优先级（截断时从低优先级开始截）：
1. system prompt（不动）
2. user query（不动）
3. retrieval context（按分数排序保留 top-N）
4. history（从最早开始截断）
5. summary / cross_session（超预算时整体丢弃）

tiktoken 不可用时降级为字符估算：
- 中文 1 字 ≈ 1.5 token
- 英文 4 字符 ≈ 1 token
- 混合文本按 len * 1.2 估算（保守值）
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

logger = logging.getLogger(__name__)


# ---- tiktoken 懒加载（失败降级字符估算） ----
_tiktoken_encoder = None
_tiktoken_available: Optional[bool] = None


def _get_tiktoken_encoder():
    """懒加载 tiktoken encoder（失败返回 None，降级字符估算）。"""
    global _tiktoken_encoder, _tiktoken_available
    if _tiktoken_available is False:
        return None
    if _tiktoken_encoder is not None:
        return _tiktoken_encoder
    try:
        import tiktoken
        # cl100k_base 是 GPT-4/4o 等主流模型的 tokenizer
        # 对中文 token 数估算比字符数准确得多
        _tiktoken_encoder = tiktoken.get_encoding("cl100k_base")
        _tiktoken_available = True
        logger.info("tiktoken 已加载，token 计数使用精确模式")
        return _tiktoken_encoder
    except Exception as e:
        _tiktoken_available = False
        logger.info(f"tiktoken 不可用，降级字符估算: {e}")
        return None


def count_tokens(text: str) -> int:
    """计算文本的 token 数。

    tiktoken 可用时用精确计数，否则用字符数估算（保守值）。

    Args:
        text: 文本

    Returns:
        token 数
    """
    if not text:
        return 0
    enc = _get_tiktoken_encoder()
    if enc is not None:
        try:
            return len(enc.encode(text))
        except Exception:
            pass
    # 降级估算：中文字符约占 1.5 token，英文 4 字符约 1 token
    # 用 len * 1.2 作为保守估算（混合文本）
    return int(len(text) * 1.2)


def truncate_to_tokens(text: str, max_tokens: int) -> str:
    """把文本截断到 max_tokens 以内（保留头部）。

    tiktoken 可用时精确截断，否则按字符数估算截断位置。

    Args:
        text: 原文本
        max_tokens: 最大 token 数

    Returns:
        截断后的文本
    """
    if not text or max_tokens <= 0:
        return text
    enc = _get_tiktoken_encoder()
    if enc is not None:
        try:
            tokens = enc.encode(text)
            if len(tokens) <= max_tokens:
                return text
            return enc.decode(tokens[:max_tokens])
        except Exception:
            pass
    # 降级：按字符数估算（1 token ≈ 0.83 字符，取 0.8 保守）
    max_chars = int(max_tokens / 1.2)
    if len(text) <= max_chars:
        return text
    return text[:max_chars]


@dataclass
class BudgetAllocation:
    """Token 预算分配结果。"""
    system_tokens: int = 0
    retrieval_tokens: int = 0
    history_tokens: int = 0
    summary_tokens: int = 0
    cross_session_tokens: int = 0
    user_query_tokens: int = 0
    margin_tokens: int = 0
    total_budget: int = 0

    @property
    def total_allocated(self) -> int:
        return (
            self.system_tokens + self.retrieval_tokens + self.history_tokens
            + self.summary_tokens + self.cross_session_tokens
            + self.user_query_tokens + self.margin_tokens
        )


class TokenBudget:
    """Token 预算分配器。

    按模型窗口大小分配 token 预算给各组件，超预算时自动截断。

    默认分配（4096 token 窗口）：
    - system_prompt:   800 token（固定）
    - retrieval_context: 2000 token（动态，按相关性保留）
    - history:          800 token（滚动截断）
    - summary:          300 token（超预算时整体丢弃）
    - cross_session:    200 token（超预算时整体丢弃）
    - user_query:       200 token（保留）
    - margin:           296 token（安全边距，给模型生成留空间）

    用法：
        budget = TokenBudget(total=4096)
        allocation = budget.allocate(
            system_prompt=SYSTEM_PROMPT,
            user_query=question,
            retrieval_results=results,
            history=history,
            summary=summary,
            cross_session=cross_ctx,
        )
        # 用 allocation 指导各组件截断
    """

    # 默认分配比例（占 total 的百分比）
    DEFAULT_RATIOS = {
        "system": 0.20,        # 20% 给 system prompt
        "retrieval": 0.50,     # 50% 给检索资料（最大头）
        "history": 0.20,       # 20% 给多轮历史
        "summary": 0.07,       # 7% 给对话摘要
        "cross_session": 0.05, # 5% 给跨会话记忆
        "margin": 0.07,        # 7% 安全边距
    }
    # user_query 单独保留，不参与比例分配（通常 < 200 token）

    def __init__(
        self,
        total: int = 4096,
        ratios: Optional[dict] = None,
        user_query_reserve: int = 200,
    ) -> None:
        """初始化预算分配器。

        Args:
            total: 总 token 预算（默认 4096）
            ratios: 各组件分配比例（默认 DEFAULT_RATIOS）
            user_query_reserve: 给 user query 预留的 token 数
        """
        self.total = total
        self.ratios = ratios or self.DEFAULT_RATIOS
        self.user_query_reserve = user_query_reserve

    def allocate(
        self,
        system_prompt: str,
        user_query: str,
        retrieval_results: Optional[List] = None,
        history: Optional[List[dict]] = None,
        summary: Optional[str] = None,
        cross_session: Optional[str] = None,
    ) -> Tuple[BudgetAllocation, dict]:
        """分配 token 预算，返回分配结果和截断后的各组件。

        Args:
            system_prompt: system prompt 文本（不截断）
            user_query: 用户问题（不截断）
            retrieval_results: 检索结果列表（按 score 排序保留 top-N）
            history: 对话历史 message list
            summary: 对话摘要
            cross_session: 跨会话记忆

        Returns:
            (BudgetAllocation, {
                "system": str,
                "user_query": str,
                "retrieval": List,  # 截断后的结果列表
                "history": List[dict],  # 截断后的历史
                "summary": str,  # 可能被整体丢弃（返回 ""）
                "cross_session": str,  # 可能被整体丢弃
            })
        """
        # 1. 计算固定部分
        system_tokens = count_tokens(system_prompt)
        user_query_tokens = count_tokens(user_query)

        # 2. 剩余预算
        remaining = self.total - system_tokens - user_query_tokens - int(self.total * self.ratios["margin"])
        if remaining <= 0:
            # 极端情况：system + query 就超预算，只保留固定部分
            return (
                BudgetAllocation(
                    system_tokens=system_tokens,
                    user_query_tokens=user_query_tokens,
                    margin_tokens=int(self.total * self.ratios["margin"]),
                    total_budget=self.total,
                ),
                {
                    "system": system_prompt,
                    "user_query": user_query,
                    "retrieval": [],
                    "history": [],
                    "summary": "",
                    "cross_session": "",
                },
            )

        # 3. 按比例分配剩余预算
        # 归一化比例（排除 margin，因为已经扣除了）
        active_ratios = {k: v for k, v in self.ratios.items() if k != "margin"}
        ratio_sum = sum(active_ratios.values())
        if ratio_sum <= 0:
            ratio_sum = 1

        retrieval_budget = int(remaining * self.ratios["retrieval"] / ratio_sum)
        history_budget = int(remaining * self.ratios["history"] / ratio_sum)
        summary_budget = int(remaining * self.ratios["summary"] / ratio_sum)
        cross_session_budget = int(remaining * self.ratios["cross_session"] / ratio_sum)

        # 4. 截断各组件
        # 4.1 retrieval: 按 score 排序，逐条累加 token，超预算停止
        truncated_retrieval: List = []
        retrieval_used = 0
        if retrieval_results:
            # 按 score 降序排序（最高分优先保留）
            sorted_results = sorted(
                retrieval_results,
                key=lambda r: getattr(r, "score", 0.0),
                reverse=True,
            )
            for r in sorted_results:
                content = getattr(r, "content", "") or ""
                r_tokens = count_tokens(content)
                if retrieval_used + r_tokens > retrieval_budget:
                    # 尝试截断这一条（保留头部）
                    remaining_budget = retrieval_budget - retrieval_used
                    if remaining_budget > 50:  # 至少留 50 token 才值得截断
                        truncated_content = truncate_to_tokens(content, remaining_budget)
                        if truncated_content:
                            r.content = truncated_content
                            truncated_retrieval.append(r)
                            retrieval_used += count_tokens(truncated_content)
                    break
                truncated_retrieval.append(r)
                retrieval_used += r_tokens
            # 恢复原始顺序（按重排后的顺序，不是 score 顺序）
            # 用 chunk_id 集合过滤
            kept_ids = {getattr(r, "chunk_id", "") for r in truncated_retrieval}
            truncated_retrieval = [
                r for r in retrieval_results
                if getattr(r, "chunk_id", "") in kept_ids
            ]

        # 4.2 history: 从最近开始保留，超预算从最早截断
        truncated_history: List[dict] = []
        history_used = 0
        if history:
            for msg in reversed(history):
                content = (msg.get("content") or "") if isinstance(msg, dict) else str(msg)
                msg_tokens = count_tokens(content)
                if history_used + msg_tokens > history_budget:
                    break
                truncated_history.insert(0, msg)
                history_used += msg_tokens

        # 4.3 summary: 超预算整体丢弃
        truncated_summary = ""
        summary_used = 0
        if summary:
            summary_used = count_tokens(summary)
            if summary_used <= summary_budget:
                truncated_summary = summary
            else:
                # 尝试截断
                truncated_summary = truncate_to_tokens(summary, summary_budget)
                summary_used = count_tokens(truncated_summary)

        # 4.4 cross_session: 超预算整体丢弃
        truncated_cross = ""
        cross_used = 0
        if cross_session:
            cross_used = count_tokens(cross_session)
            if cross_used <= cross_session_budget:
                truncated_cross = cross_session
            else:
                truncated_cross = truncate_to_tokens(cross_session, cross_session_budget)
                cross_used = count_tokens(truncated_cross)

        allocation = BudgetAllocation(
            system_tokens=system_tokens,
            retrieval_tokens=retrieval_used,
            history_tokens=history_used,
            summary_tokens=summary_used,
            cross_session_tokens=cross_used,
            user_query_tokens=user_query_tokens,
            margin_tokens=int(self.total * self.ratios["margin"]),
            total_budget=self.total,
        )

        return allocation, {
            "system": system_prompt,
            "user_query": user_query,
            "retrieval": truncated_retrieval,
            "history": truncated_history,
            "summary": truncated_summary,
            "cross_session": truncated_cross,
        }

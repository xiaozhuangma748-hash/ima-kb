"""LLM 重排序：让 LLM 对候选打分（0-10）。"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import List, Optional

from core.retrieval.hybrid import HybridResult
from core.llm.client import LLMClient

logger = logging.getLogger(__name__)


@dataclass
class RerankResult:
    """重排序结果。"""
    chunk_id: str
    doc_id: str
    score: float                    # 原 hybrid 分数
    source: str
    content: str
    doc_title: str
    relevance_score: float          # LLM 打分（0-10）
    reason: str                     # LLM 相关性理由


class Reranker:
    """LLM 重排序器。"""

    def __init__(self, llm: LLMClient) -> None:
        self.llm = llm

    def rerank(
        self,
        query: str,
        candidates: List[HybridResult],
        top_n: int = 5,
    ) -> List[RerankResult]:
        """对候选列表用 LLM 打分并重排。

        Args:
            query: 用户查询
            candidates: 混合检索结果
            top_n: 返回前 N 个

        Returns:
            重排序后的结果列表，降级时保留原顺序
        """
        if not candidates:
            return []

        try:
            scores = self._call_llm_for_scores(query, candidates)
        except Exception as e:
            logger.warning(f"LLM 重排失败，保留原顺序: {e}")
            return self._fallback_results(candidates, top_n)

        # 合并分数并排序
        results = []
        for i, c in enumerate(candidates):
            score_data = scores.get(i, {"score": 0, "reason": ""})
            results.append(RerankResult(
                chunk_id=c.chunk_id,
                doc_id=c.doc_id,
                score=c.score,
                source=c.source,
                content=c.content,
                doc_title=c.doc_title,
                relevance_score=score_data.get("score", 0),
                reason=score_data.get("reason", ""),
            ))

        # 按 relevance_score 降序
        results.sort(key=lambda r: r.relevance_score, reverse=True)
        return results[:top_n]

    def _call_llm_for_scores(self, query: str, candidates: List[HybridResult]) -> dict:
        """调用 LLM 对候选批量打分。

        Returns:
            {index: {"score": float, "reason": str}}
        """
        # 构造候选列表文本
        candidate_texts = []
        for i, c in enumerate(candidates):
            # 截取前 200 字避免 token 过长；超出部分用省略号标记
            if c.content:
                snippet = c.content[:200] + ("..." if len(c.content) > 200 else "")
            else:
                snippet = ""
            candidate_texts.append(f"[{i}] {c.doc_title}: {snippet}")

        prompt = f"""请对以下候选文档与查询的相关性打分（0-10 分，10 最相关）。

查询：{query}

候选文档：
{chr(10).join(candidate_texts)}

请只返回 JSON 数组，格式如下：
[{{"index": 0, "score": 8.5, "reason": "高度相关"}}]

不要返回其他内容。"""

        messages = [{"role": "user", "content": prompt}]
        response = self.llm.chat(messages, temperature=0.0, max_tokens=1000)

        # 解析 JSON
        data = json.loads(response)
        scores = {}
        for item in data:
            idx = item.get("index")
            if idx is not None:
                scores[idx] = {
                    "score": float(item.get("score", 0)),
                    "reason": item.get("reason", ""),
                }
        return scores

    def _fallback_results(
        self,
        candidates: List[HybridResult],
        top_n: int,
    ) -> List[RerankResult]:
        """降级：保留原顺序，relevance_score=0。"""
        return [
            RerankResult(
                chunk_id=c.chunk_id,
                doc_id=c.doc_id,
                score=c.score,
                source=c.source,
                content=c.content,
                doc_title=c.doc_title,
                relevance_score=0,
                reason="",
            )
            for c in candidates[:top_n]
        ]

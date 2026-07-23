"""LLM 重排序：让 LLM 对候选打分（0-10）。"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from typing import List, Optional, Union

from config import settings
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
    paragraph_num: int = 0          # 真实段落号（从 HybridResult 透传）


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
        """对候选列表用 LLM 打分并重排。"""
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
                paragraph_num=getattr(c, "paragraph_num", 0),
            ))

        results.sort(key=lambda r: r.relevance_score, reverse=True)
        return results[:top_n]

    def _call_llm_for_scores(self, query: str, candidates: List[HybridResult]) -> dict:
        """调用 LLM 对候选批量打分。

        Returns:
            {index: {"score": float, "reason": str}}
        """
        candidate_texts = []
        for i, c in enumerate(candidates):
            # 不再截断到 200 字符，保留完整 chunk（chunk_size=512，LLM 能处理）
            snippet = c.content or ""
            candidate_texts.append(f"[{i}] {c.doc_title}: {snippet}")

        prompt = f"""请对以下候选文档与查询的相关性打分（0-10 分，10 最相关）。

查询：{query}

候选文档：
{chr(10).join(candidate_texts)}

请只返回一个 JSON 对象，格式如下：
{{"results": [{{"index": 0, "score": 8.5, "reason": "高度相关"}}]}}

不要返回其他内容。"""

        # 加一个精简 system 角色明确"只返回 JSON 对象"，并启用 JSON 模式
        # （部分 OpenAI 兼容端点不支持 response_format，失败则忽略该参数回退普通调用）
        messages = [
            {"role": "system", "content": "你是一个相关性打分器。只返回 JSON 对象（含 results 数组），不要任何解释或 markdown 代码块。"},
            {"role": "user", "content": prompt},
        ]
        try:
            response = self.llm.chat(
                messages,
                temperature=0.0,
                max_tokens=1000,
                response_format={"type": "json_object"},
            )
        except Exception:
            # 端点不支持 response_format 时回退普通调用
            response = self.llm.chat(messages, temperature=0.0, max_tokens=1000)

        # 健壮解析：先尝试直接解析，失败则提取 JSON 片段
        return self._parse_scores(response)

    @staticmethod
    def _parse_scores(response: str) -> dict:
        """从 LLM 响应中解析打分 JSON，支持多种格式。

        策略：
        1. 直接 json.loads（支持 {"results": [...]} 或裸数组/字典）
        2. 提取第一个 [...] 或 {...} 片段
        3. 清理 markdown code block 标记
        """
        # 1. 直接尝试
        try:
            data = json.loads(response)
            # 兼容 {"results": [...]} 包裹形式
            if isinstance(data, dict) and "results" in data and isinstance(data["results"], list):
                data = data["results"]
            return Reranker._normalize_scores(data)
        except (json.JSONDecodeError, TypeError):
            pass

        # 2. 提取 JSON 数组或对象
        # 先尝试匹配 [...].pattern
        match = re.search(r'(\[.*\])', response, re.DOTALL)
        if match:
            try:
                data = json.loads(match.group(1))
                return Reranker._normalize_scores(data)
            except (json.JSONDecodeError, TypeError):
                pass

        # 3. 尝试匹配 {...}
        match = re.search(r'(\{.*\})', response, re.DOTALL)
        if match:
            try:
                data = json.loads(match.group(1))
                return Reranker._normalize_scores(data)
            except (json.JSONDecodeError, TypeError):
                pass

        raise ValueError(f"无法从 LLM 响应中提取 JSON: {response[:200]}")

    @staticmethod
    def _normalize_scores(data) -> dict:
        """标准化 LLM 返回的数据结构。

        支持：
        - [{"index": 0, "score": 8.5}, ...]  列表格式
        - {"0": 8.5, "1": 9.0}              字典格式
        - 其他 → 返回空 dict（降级）
        """
        scores = {}

        if isinstance(data, list):
            for item in data:
                if isinstance(item, dict):
                    idx = item.get("index")
                    if idx is not None:
                        scores[int(idx)] = {
                            "score": float(item.get("score", 0)),
                            "reason": item.get("reason", ""),
                        }
        elif isinstance(data, dict):
            for key, val in data.items():
                try:
                    idx = int(key)
                    if isinstance(val, dict):
                        scores[idx] = {
                            "score": float(val.get("score", 0)),
                            "reason": val.get("reason", ""),
                        }
                    elif isinstance(val, (int, float)):
                        scores[idx] = {
                            "score": float(val),
                            "reason": "",
                        }
                except (ValueError, TypeError):
                    continue

        return scores

    def _fallback_results(
        self,
        candidates: List[HybridResult],
        top_n: int,
    ) -> List[RerankResult]:
        """降级：保留原顺序。"""
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


# ============================================================
# Reranker 工厂：根据配置选择 Cross-Encoder 或 LLM
# ============================================================

# 类型别名：所有 reranker 都实现 rerank(query, candidates, top_n) -> List[RerankResult]
RerankerType = Union["Reranker", "CrossEncoderReranker", None]


def create_reranker(llm: Optional[LLMClient] = None) -> RerankerType:
    """根据配置创建重排序器。

    优先级：
    1. settings.reranker_type == 'cross_encoder'：尝试 Cross-Encoder，加载失败自动降级 LLM
    2. settings.reranker_type == 'llm'：直接用 LLM Reranker
    3. settings.reranker_type == 'none'：返回 None（不重排）
    4. LLM 不可用且 Cross-Encoder 不可用：返回 None

    Args:
        llm: 可选的 LLM 客户端实例，未提供时按需创建

    Returns:
        Reranker / CrossEncoderReranker / None
    """
    reranker_type = (settings.reranker_type or "cross_encoder").lower().strip()

    if reranker_type == "none":
        return None

    if reranker_type == "cross_encoder":
        # 尝试 Cross-Encoder
        try:
            from .cross_encoder import CrossEncoderReranker
            ce = CrossEncoderReranker()
            if ce.is_available():
                ce.warmup()  # 预热，避免首次查询慢
                logger.info("使用 Cross-Encoder 重排序器（bge-reranker-v2-m3）")
                return ce
            logger.info("Cross-Encoder 不可用（模型未下载），降级为 LLM Reranker")
        except Exception as e:
            logger.info(f"Cross-Encoder 加载失败，降级为 LLM Reranker: {e}")

    # LLM Reranker
    try:
        if llm is None:
            from core.llm.client import get_llm
            llm = get_llm()
        logger.info("使用 LLM 重排序器")
        return Reranker(llm=llm)
    except Exception as e:
        logger.warning(f"LLM Reranker 也不可用，跳过重排: {e}")
        return None

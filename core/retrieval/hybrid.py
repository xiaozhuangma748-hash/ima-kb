"""混合检索：BM25 + 向量 + RRF 融合。"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional

from core.search.bm25 import BM25Index, SearchResult
from core.retrieval.vector import VectorIndex, VectorResult


# RRF 参数：k 越大，排名差异的影响越小
RRF_K = 60


@dataclass
class HybridResult:
    """混合检索结果。"""
    chunk_id: str
    doc_id: str
    score: float
    source: str           # "bm25" / "vector" / "both"
    content: str = ""
    doc_title: str = ""
    paragraph_num: int = 0  # 真实段落号（chunk 的 index_in_doc + 1，由 storage.enrich_hybrid_results 填充）


class HybridRetriever:
    """混合检索器：BM25 + 向量并行检索，RRF 融合。"""

    def __init__(
        self,
        bm25_index: BM25Index,
        vector_index: VectorIndex,
        storage=None,
    ) -> None:
        self.bm25 = bm25_index
        self.vector = vector_index
        # 可选：传入 Storage 实例后，检索结果会自动从 SQLite 补全
        # content/doc_title/paragraph_num（修复引用溯源标题缺失问题）
        self.storage = storage

    def search(self, query: str, top_k: int = 10) -> List[HybridResult]:
        """混合检索：BM25 + 向量 + RRF 融合。

        Args:
            query: 查询文本
            top_k: 返回结果数量

        Returns:
            融合后的结果列表，按 RRF 分数降序。若构造时传入了 storage，
            结果会自动补全 content/doc_title/paragraph_num 并过滤过期 chunk。
        """
        # 1. BM25 检索
        bm25_results = self.bm25.search(query, top_k=top_k)

        # 2. 向量检索（不可用时降级为纯 BM25）
        if not self.vector.is_available():
            results = self._bm25_only_results(bm25_results, top_k)
        else:
            vector_results = self.vector.search(query, top_k=top_k)
            # 3. RRF 融合
            results = self._rrf_fusion(bm25_results, vector_results, top_k)

        # 4. 若有 storage 引用，批量补全 content/doc_title/paragraph_num
        if self.storage is not None and results:
            results = self.storage.enrich_hybrid_results(results)
        return results

    def _bm25_only_results(self, bm25_results: List[SearchResult], top_k: int) -> List[HybridResult]:
        """纯 BM25 降级结果。"""
        results = [
            HybridResult(
                chunk_id=r.chunk_id,
                doc_id=r.doc_id,
                score=r.score,
                source="bm25",
                content=getattr(r, "content", ""),
                doc_title=getattr(r, "doc_title", ""),
            )
            for r in bm25_results[:top_k]
        ]
        return results

    def _rrf_fusion(
        self,
        bm25_results: List[SearchResult],
        vector_results: List[VectorResult],
        top_k: int,
    ) -> List[HybridResult]:
        """RRF 融合：score = Σ 1/(k + rank)。"""
        # 收集所有 chunk_id
        bm25_ids = {r.chunk_id for r in bm25_results}
        vector_ids = {r.chunk_id for r in vector_results}
        all_ids = bm25_ids | vector_ids

        # 计算 RRF 分数
        scores = {}
        sources = {}
        for rank, r in enumerate(bm25_results, 1):
            scores[r.chunk_id] = scores.get(r.chunk_id, 0) + 1.0 / (RRF_K + rank)
            sources[r.chunk_id] = "bm25"
        for rank, r in enumerate(vector_results, 1):
            scores[r.chunk_id] = scores.get(r.chunk_id, 0) + 1.0 / (RRF_K + rank)
            if r.chunk_id in sources:
                sources[r.chunk_id] = "both"
            else:
                sources[r.chunk_id] = "vector"

        # 构建 doc_id 和 content 映射
        doc_map = {}
        for r in bm25_results:
            doc_map[r.chunk_id] = (r.doc_id, getattr(r, "content", ""), getattr(r, "doc_title", ""))
        for r in vector_results:
            if r.chunk_id not in doc_map:
                doc_map[r.chunk_id] = (r.doc_id, "", "")

        # 排序并取 top_k
        sorted_ids = sorted(all_ids, key=lambda cid: scores[cid], reverse=True)
        results = []
        for cid in sorted_ids[:top_k]:
            doc_id, content, doc_title = doc_map.get(cid, ("", "", ""))
            results.append(HybridResult(
                chunk_id=cid,
                doc_id=doc_id,
                score=scores[cid],
                source=sources[cid],
                content=content,
                doc_title=doc_title,
            ))
        return results

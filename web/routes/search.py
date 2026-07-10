"""搜索 — 混合检索 API。

GET /api/search?q=...&tags=...&use_vector=true&use_rerank=true&sort=score&limit=10
"""
from __future__ import annotations

from typing import Optional, List
from fastapi import APIRouter, Query

from config import settings
from core.storage import Storage

router = APIRouter(tags=["search"])


@router.get("/search")
async def search(
    q: str = Query(..., description="搜索关键词"),
    tags: Optional[str] = Query(None, description="逗号分隔标签"),
    use_vector: bool = Query(True, description="启用向量检索"),
    use_rerank: bool = Query(True, description="启用 LLM 重排序"),
    sort: str = Query("score", description="排序: score|date|name"),
    limit: int = Query(10, description="返回条数"),
):
    """混合检索。"""
    import time
    t0 = time.time()

    storage = Storage()
    tag_list = [t.strip() for t in tags.split(",") if t.strip()] if tags else []

    results = []
    try:
        if use_vector:
            from core.retrieval.hybrid import HybridRetriever
            from core.retrieval.vector import VectorIndex
            vector_index = VectorIndex()
            hybrid = HybridRetriever(bm25_index=storage.bm25, vector_index=vector_index)
            raw_results = hybrid.search(q, top_k=limit * 2)
        else:
            raw_results = storage.bm25_search(q, top_k=limit * 2)
    except Exception:
        raw_results = storage.bm25_search(q, top_k=limit * 2)

    # LLM 重排序
    if use_rerank and len(raw_results) > limit and settings.has_llm():
        try:
            from core.retrieval.rerank import Reranker
            from core.llm.client import get_llm
            reranker = Reranker(get_llm())
            raw_results = reranker.rerank(q, raw_results)
        except Exception:
            pass

    # 标签筛选
    if tag_list:
        tagged_docs = set()
        for t in tag_list:
            docs = storage.list_documents_by_tag(t)
            tagged_docs.update(d.id for d in docs)
        raw_results = [r for r in raw_results if r.get("doc_id", "") in tagged_docs]

    # 构造结果（兼容 dict 和各类 search result 对象）
    for r in raw_results[:limit]:
        if isinstance(r, dict):
            content = r.get("content", "") or r.get("text", "") or ""
            doc_title = r.get("doc_title", r.get("title", ""))
            score = r.get("score", 0)
            doc_id = r.get("doc_id", "")
        else:
            content = getattr(r, "content", None) or getattr(r, "text", None) or ""
            doc_title = getattr(r, "doc_title", None) or getattr(r, "title", None) or ""
            score = getattr(r, "score", 0)
            doc_id = getattr(r, "doc_id", "")

        # 从 storage 回填缺失的文档元数据
        doc_tags = []
        file_type = ""
        created_at = ""
        if doc_id:
            doc = storage.get_document(doc_id)
            if doc:
                doc_tags = doc.tags or []
                file_type = doc.file_type or ""
                created_at = str(doc.created_at) if doc.created_at else ""
                # 如果搜索结果中 doc_title 为空，从文档元数据取
                if not doc_title and doc.title:
                    doc_title = doc.title
                # 如果搜索结果中 content 为空，从文档分块取
                if not content:
                    try:
                        chunks = storage.get_chunks(doc_id)
                        if chunks:
                            content = chunks[0].content or ""
                    except Exception:
                        pass

        snippet = content[:300]

        results.append({
            "doc_id": doc_id,
            "doc_title": doc_title or "未知文档",
            "snippet": snippet,
            "content": content[:500],
            "score": round(score, 4) if isinstance(score, (int, float)) else 0,
            "tags": doc_tags,
            "file_type": file_type,
            "created_at": created_at,
        })

    elapsed = round((time.time() - t0) * 1000, 1)

    return {
        "results": results,
        "total": len(results),
        "time_ms": elapsed,
    }

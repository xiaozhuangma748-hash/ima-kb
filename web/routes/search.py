"""搜索 — 混合检索 API。

GET /api/search?q=...&tags=...&use_vector=true&use_rerank=true&sort=score&limit=10
"""
from __future__ import annotations

from typing import Optional, List
from fastapi import APIRouter, Query, Request

from config import settings
from core.storage import Storage

router = APIRouter(tags=["search"])


@router.get("/search")
async def search(
    request: Request,
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

    from web.app import _get_shared_storage, _get_shared_vector_index

    storage = _get_shared_storage(request.app)
    tag_list = [t.strip() for t in tags.split(",") if t.strip()] if tags else []

    results = []
    try:
        if use_vector:
            from core.retrieval.hybrid import HybridRetriever
            vector_index = _get_shared_vector_index(request.app)
            if vector_index and vector_index.is_available():
                hybrid = HybridRetriever(bm25_index=storage.bm25, vector_index=vector_index, storage=storage)
                raw_results = hybrid.search(q, top_k=limit * 2)
            else:
                raw_results = storage.bm25_search(q, top_k=limit * 2)
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
    # 先收集所有 doc_id，批量查询文档元数据（避免 N+1 查询）
    top_results = raw_results[:limit]
    all_doc_ids = set()
    parsed_results = []
    for r in top_results:
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
        parsed_results.append({
            "content": content,
            "doc_title": doc_title,
            "score": score,
            "doc_id": doc_id,
        })
        if doc_id:
            all_doc_ids.add(doc_id)

    # 一次查询所有文档元数据
    docs_map = storage.get_documents_batch(list(all_doc_ids)) if all_doc_ids else {}

    # 对缺少 content 的结果，批量查第一个 chunk
    missing_content_doc_ids = [
        p["doc_id"] for p in parsed_results
        if not p["content"] and p["doc_id"]
    ]

    for p in parsed_results:
        doc_id = p["doc_id"]
        doc = docs_map.get(doc_id) if doc_id else None
        if doc:
            p["doc_tags"] = doc.tags or []
            p["file_type"] = doc.file_type or ""
            p["created_at"] = str(doc.created_at) if doc.created_at else ""
            if not p["doc_title"] and doc.title:
                p["doc_title"] = doc.title
        else:
            p["doc_tags"] = []
            p["file_type"] = ""
            p["created_at"] = ""

        # 如果 content 为空，从文档分块取第一个
        if not p["content"] and doc_id:
            try:
                first_chunk = storage.get_first_chunk(doc_id)
                if first_chunk:
                    p["content"] = first_chunk.content or ""
            except Exception:
                pass

        snippet = p["content"][:300]

        results.append({
            "doc_id": doc_id,
            "doc_title": p["doc_title"] or "未知文档",
            "snippet": snippet,
            "content": p["content"][:500],
            "score": round(p["score"], 4) if isinstance(p["score"], (int, float)) else 0,
            "tags": p["doc_tags"],
            "file_type": p["file_type"],
            "created_at": p["created_at"],
        })

    elapsed = round((time.time() - t0) * 1000, 1)

    return {
        "results": results,
        "total": len(results),
        "time_ms": elapsed,
    }

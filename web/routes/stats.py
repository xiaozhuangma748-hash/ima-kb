"""仪表盘 — 知识库统计数据。

GET /api/stats  返回仪表盘所需全部数据。
"""
from __future__ import annotations

from fastapi import APIRouter, Request

from core.storage import Storage

router = APIRouter(tags=["stats"])


@router.get("/stats")
async def stats(request: Request):
    """知识库仪表盘数据。"""
    from web.app import _get_shared_storage, _get_shared_graph_store, _get_health_cache

    storage = _get_shared_storage(request.app)
    s = storage.stats()

    # 按类型分布
    by_type = s.get("by_type", {})

    # 标签 Top N
    tags = storage.list_all_tags()
    top_tags = sorted(tags.items(), key=lambda x: -x[1])[:10]
    top_tags_data = [{"name": t, "count": c} for t, c in top_tags]

    # 最近入库
    docs = storage.list_documents(limit=5)
    recent_docs = [
        {
            "title": d.title,
            "file_type": d.file_type,
            "tags": d.tags or [],
            "chunk_count": d.chunk_count,
            "created_at": d.created_at[:19] if d.created_at else "",
            "doc_id": d.id[:8],
        }
        for d in docs
    ]

    # 质量告警（使用缓存）
    alerts = []
    health = _get_health_cache(request.app)
    health_score = health.get("health_score", 100)
    health_alerts = health.get("alerts", {})
    if health_alerts:
        for issue, count in health_alerts.items():
            severity = "error" if "空" in issue else "warning"
            alerts.append({
                "severity": severity,
                "message": f"{issue}: {count} 个",
            })

    # 图谱统计（使用共享实例）
    graph_nodes = 0
    graph_edges = 0
    gs = _get_shared_graph_store(request.app)
    if gs:
        try:
            gs_stats = gs.stats()
            graph_nodes = gs_stats["nodes"]
            graph_edges = gs_stats["edges"]
        except Exception:
            pass

    return {
        "documents": s["documents"],
        "chunks": s["chunks"],
        "total_tokens": s["total_tokens"],
        "total_size_mb": s.get("total_size_mb", 0),
        "tags_count": len(tags),
        "graph_nodes": graph_nodes,
        "graph_edges": graph_edges,
        "by_type": by_type,
        "top_tags": top_tags_data,
        "alerts": alerts,
        "health_score": health_score,
        "recent_docs": recent_docs,
    }

"""仪表盘 — 知识库统计数据。

GET /api/stats  返回仪表盘所需全部数据。
"""
from __future__ import annotations

from fastapi import APIRouter

from core.storage import Storage

router = APIRouter(tags=["stats"])


@router.get("/stats")
async def stats():
    """知识库仪表盘数据。"""
    storage = Storage()
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

    # 质量告警
    alerts = []
    health_score = 100
    try:
        from core.sync.checker import QualityChecker
        checker = QualityChecker()
        all_docs = storage.list_documents(limit=1000)
        all_issues = []
        for doc in all_docs:
            chunks = storage.get_chunks(doc.id)
            issues = checker.check_document(chunks)
            all_issues.extend(issues)
        report = checker.generate_report(all_issues)
        health_score = report.health_score
        if report.issues_detail:
            for issue, count in report.issues_detail.items():
                severity = "error" if "空" in issue else "warning"
                alerts.append({
                    "severity": severity,
                    "message": f"{issue}: {count} 个",
                })
    except Exception:
        pass

    # 图谱统计
    graph_nodes = 0
    graph_edges = 0
    try:
        from core.graph.store import GraphStore
        gs = GraphStore()
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

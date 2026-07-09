"""知识图谱 — 数据查询 + 可视化导出。

GET  /api/graph/data              图谱数据（vis.js 格式）
GET  /api/graph/neighbors/{name}  节点邻居查询
POST /api/graph/build             重建图谱
GET  /api/graph/export            导出 HTML
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import HTMLResponse, FileResponse
from pydantic import BaseModel

from config import settings

router = APIRouter(tags=["graph"])


@router.get("/graph/data")
async def graph_data():
    """返回知识图谱数据（vis.js 可用格式）。"""
    try:
        from core.graph.store import GraphStore

        gs = GraphStore()
        if gs.graph.number_of_nodes() == 0:
            return {"elements": {"nodes": [], "edges": []}, "stats": gs.stats()}

        cytoscape = gs.to_cytoscape()
        elements = cytoscape.get("elements", {})
        return {
            "elements": elements,
            "stats": gs.stats(),
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"图谱加载失败: {e}")


@router.get("/graph/neighbors/{name}")
async def graph_neighbors(name: str):
    """查询节点的邻居关系。"""
    try:
        from core.graph.store import GraphStore

        gs = GraphStore()

        # 精确匹配或模糊搜索
        if name not in gs.graph:
            matches = gs.search_nodes(name)
            if not matches:
                raise HTTPException(status_code=404, detail=f"未找到节点: {name}")
            return {
                "found": False,
                "matches": matches[:10],
                "hint": f"用确切名称重试，如: {matches[0]['label']}",
            }

        neighbors = gs.neighbors(name)
        node_data = gs.graph.nodes[name]
        return {
            "found": True,
            "node": {
                "label": name,
                "type": node_data.get("type", ""),
                "doc_count": node_data.get("doc_count", 0),
                "degree": len(neighbors),
            },
            "neighbors": neighbors,
        }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"查询失败: {e}")


class GraphBuildBody(BaseModel):
    force: bool = False


@router.post("/graph/build")
async def graph_build(body: GraphBuildBody):
    """重新构建知识图谱（调用 LLM 抽取实体关系）。"""
    if not settings.has_llm():
        raise HTTPException(status_code=400, detail="LLM 未配置，请在 .env 中设置 AGNES_API_KEY")

    try:
        from core.graph.extractor import GraphExtractor
        from core.graph.store import GraphStore
        from core.storage import Storage

        storage = Storage()
        graph_store = GraphStore()

        if body.force:
            graph_store.clear()

        extractor = GraphExtractor()
        all_docs = storage.list_documents(limit=1000)

        existing_ids = set()
        for n, d in graph_store.graph.nodes(data=True):
            existing_ids.update(d.get("doc_ids", []))

        target_docs = [d for d in all_docs if d.id not in existing_ids]

        if not target_docs:
            return {"status": "no_new", "message": "没有需要抽取的文档"}

        success = 0
        for doc in target_docs:
            try:
                chunks = storage.get_chunks(doc.id)
                content = "\n".join(c.content for c in chunks)
                result = extractor.extract_from_document(doc.id, doc.title, content)
                if result.entities:
                    graph_store.add_extraction(result)
                    graph_store.save()
                    success += 1
            except Exception:
                pass

        return {
            "status": "done",
            "processed": success,
            "total": len(target_docs),
            "stats": graph_store.stats(),
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"构建失败: {e}")


@router.get("/graph/export")
async def graph_export():
    """导出知识图谱自包含 HTML。"""
    try:
        from core.graph.store import GraphStore
        from core.graph.visualizer import generate_html

        gs = GraphStore()
        if gs.graph.number_of_nodes() == 0:
            raise HTTPException(status_code=404, detail="图谱为空")

        output_path = generate_html(gs)
        return FileResponse(
            output_path,
            media_type="text/html",
            filename="知识图谱.html",
        )

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"导出失败: {e}")

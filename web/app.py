"""FastAPI 应用工厂。

路由注册、模板配置、静态文件挂载。
"""
from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.middleware.cors import CORSMiddleware

WEB_DIR = Path(__file__).resolve().parent
TEMPLATES_DIR = WEB_DIR / "templates"
STATIC_DIR = WEB_DIR / "static"

templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


def create_app() -> FastAPI:
    """创建并配置 FastAPI 应用。"""
    app = FastAPI(
        title="IMA 知识库 · Web 后台",
        version="1.0.0",
        docs_url=None,       # 内网环境不需要文档
        redoc_url=None,
    )

    # CORS — 内网访问允许跨域
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # 静态文件
    if STATIC_DIR.exists():
        app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    # 注册路由
    from web.routes.qa import router as qa_router
    from web.routes.ingest import router as ingest_router
    from web.routes.search import router as search_router
    from web.routes.analyze import router as analyze_router
    from web.routes.stats import router as stats_router
    from web.routes.graph import router as graph_router
    from web.routes.pet import router as pet_router

    app.include_router(qa_router, prefix="/api")
    app.include_router(ingest_router, prefix="/api")
    app.include_router(search_router, prefix="/api")
    app.include_router(analyze_router, prefix="/api")
    app.include_router(stats_router, prefix="/api")
    app.include_router(graph_router, prefix="/api")
    app.include_router(pet_router, prefix="/api")

    # 首页 — 单页 HTML
    @app.get("/")
    async def index(request: Request):
        """渲染单页 Web 后台。注入初始统计数据。"""
        from config import settings
        from core.storage import Storage

        storage = Storage()
        s = storage.stats()
        tags = storage.list_all_tags()

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

        # 健康检查
        health_score = 100
        health_alerts = []
        try:
            from core.sync.checker import QualityChecker
            checker = QualityChecker()
            docs = storage.list_documents(limit=1000)
            all_issues = []
            for doc in docs:
                chunks = storage.get_chunks(doc.id)
                issues = checker.check_document(chunks)
                all_issues.extend(issues)
            report = checker.generate_report(all_issues)
            health_score = report.health_score
            health_alerts = report.issues_detail or {}
        except Exception:
            pass

        return templates.TemplateResponse("index.html", {
            "request": request,
            "page_title": "IMA 知识库",
            "initial_stats": {
                "documents": s["documents"],
                "chunks": s["chunks"],
                "total_tokens": s["total_tokens"],
                "tags_count": len(tags),
                "graph_nodes": graph_nodes,
                "graph_edges": graph_edges,
                "health_score": health_score,
            },
            "initial_alerts": health_alerts,
            "api_key_configured": settings.has_llm(),
        })

    return app

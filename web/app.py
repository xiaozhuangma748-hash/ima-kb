"""FastAPI 应用工厂。

路由注册、模板配置、静态文件挂载。

性能优化：
- 全局共享 Storage / VectorIndex / GraphStore 等重组件，避免每请求重建
- 健康分数缓存化，避免首页同步遍历所有文档
"""
from __future__ import annotations

import logging
import threading
from pathlib import Path
from typing import Any, Optional

from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.middleware.cors import CORSMiddleware

WEB_DIR = Path(__file__).resolve().parent
TEMPLATES_DIR = WEB_DIR / "templates"
STATIC_DIR = WEB_DIR / "static"

templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

logger = logging.getLogger(__name__)


def _get_shared_storage(app: FastAPI):
    """获取全局共享的 Storage（懒加载，线程安全）。"""
    if not getattr(app.state, "storage", None):
        with app.state._storage_lock:
            if not getattr(app.state, "storage", None):
                from core.storage import Storage
                app.state.storage = Storage()
    return app.state.storage


def _get_shared_vector_index(app: FastAPI):
    """获取全局共享的 VectorIndex（懒加载，失败返回 None）。"""
    if getattr(app.state, "_vector_init_failed", False):
        return None
    if not getattr(app.state, "vector_index", None):
        with app.state._vector_lock:
            if not getattr(app.state, "vector_index", None):
                try:
                    from core.retrieval.vector import VectorIndex
                    app.state.vector_index = VectorIndex()
                except Exception as e:
                    logger.warning(f"向量索引初始化失败: {e}")
                    app.state._vector_init_failed = True
                    return None
    return app.state.vector_index


def _get_shared_graph_store(app: FastAPI):
    """获取全局共享的 GraphStore（懒加载，失败返回 None）。"""
    if getattr(app.state, "_graph_init_failed", False):
        return None
    if not getattr(app.state, "graph_store", None):
        with app.state._graph_lock:
            if not getattr(app.state, "graph_store", None):
                try:
                    from core.graph.store import GraphStore
                    app.state.graph_store = GraphStore()
                except Exception as e:
                    logger.warning(f"图谱初始化失败: {e}")
                    app.state._graph_init_failed = True
                    return None
    return app.state.graph_store


def _get_health_cache(app: FastAPI) -> dict:
    """获取缓存的健康分数（10 分钟刷新一次，入库/删除时清空）。"""
    import time
    cache = getattr(app.state, "_health_cache", None)
    if cache and (time.time() - cache.get("ts", 0) < 600):
        return cache
    # 重新计算
    cache = _compute_health_cache(app)
    app.state._health_cache = cache
    return cache


def _compute_health_cache(app: FastAPI) -> dict:
    """计算健康分数和告警（同步，但被缓存）。"""
    storage = _get_shared_storage(app)
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
        return {
            "ts": __import__("time").time(),
            "health_score": report.health_score,
            "alerts": report.issues_detail or {},
        }
    except Exception as e:
        logger.warning(f"健康检查失败: {e}")
        return {"ts": __import__("time").time(), "health_score": 100, "alerts": {}}


def invalidate_health_cache(app: FastAPI) -> None:
    """入库/删除文档时调用，清空健康缓存。"""
    app.state._health_cache = None


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

    # 全局共享组件状态（懒加载）
    app.state.storage = None
    app.state.vector_index = None
    app.state.graph_store = None
    app.state._vector_init_failed = False
    app.state._graph_init_failed = False
    app.state._health_cache = None
    app.state._storage_lock = threading.Lock()
    app.state._vector_lock = threading.Lock()
    app.state._graph_lock = threading.Lock()

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

        storage = _get_shared_storage(request.app)
        s = storage.stats()
        tags = storage.list_all_tags()

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

        # 健康检查（缓存化，避免每次开页都遍历所有文档）
        health = _get_health_cache(request.app)
        health_score = health.get("health_score", 100)
        health_alerts = health.get("alerts", {})

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

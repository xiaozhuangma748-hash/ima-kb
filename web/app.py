"""FastAPI 应用工厂。

路由注册、模板配置、静态文件挂载。

性能优化：
- 全局共享 Storage / VectorIndex / GraphStore 等重组件，避免每请求重建
- 健康分数缓存化，避免首页同步遍历所有文档
"""
from __future__ import annotations

import logging
import threading
import time
from pathlib import Path
from typing import Any, Optional

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from starlette.responses import Response
from fastapi.middleware.cors import CORSMiddleware

WEB_DIR = Path(__file__).resolve().parent
STATIC_DIR = WEB_DIR / "static"
FRONTEND_DIST_DIR = WEB_DIR / "frontend" / "dist"

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


def _get_shared_hybrid_retriever(app: FastAPI):
    """获取全局共享的 HybridRetriever(懒加载,线程安全)。

    性能优化:共享实例避免每个请求重建 SemanticCache。
    若每请求新建,缓存命中率=0%,QA 响应时间无法受益于语义缓存。
    共享后预期 QA 提速 30-50%。
    """
    if not getattr(app.state, "hybrid_retriever", None):
        with app.state._hybrid_lock:
            if not getattr(app.state, "hybrid_retriever", None):
                from core.retrieval.hybrid import HybridRetriever
                storage = _get_shared_storage(app)
                vector_index = _get_shared_vector_index(app)
                app.state.hybrid_retriever = HybridRetriever(
                    bm25_index=storage.bm25,
                    vector_index=vector_index,
                    storage=storage,
                )
    return app.state.hybrid_retriever


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

    # 静态文件（禁用缓存，确保前端代码更新后立即生效）
    if STATIC_DIR.exists():
        class NoCacheStaticFiles(StaticFiles):
            async def get_response(self, path, scope):
                response = await super().get_response(path, scope)
                response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
                response.headers["Pragma"] = "no-cache"
                response.headers["Expires"] = "0"
                return response
        app.mount("/static", NoCacheStaticFiles(directory=str(STATIC_DIR)), name="static")

    # React 前端产物（Vite build → web/frontend/dist）
    if FRONTEND_DIST_DIR.exists():
        app.mount("/assets", NoCacheStaticFiles(directory=str(FRONTEND_DIST_DIR / "assets")), name="assets")
        app.mount("/vendor", NoCacheStaticFiles(directory=str(FRONTEND_DIST_DIR / "vendor")), name="vendor")

    # 全局共享组件状态（懒加载）
    app.state.storage = None
    app.state.vector_index = None
    app.state.graph_store = None
    app.state.hybrid_retriever = None
    app.state._vector_init_failed = False
    app.state._graph_init_failed = False
    app.state._health_cache = None
    app.state._storage_lock = threading.Lock()
    app.state._vector_lock = threading.Lock()
    app.state._graph_lock = threading.Lock()
    app.state._hybrid_lock = threading.Lock()

    # 注册路由
    from web.routes.qa import router as qa_router
    from web.routes.ingest import router as ingest_router
    from web.routes.search import router as search_router
    from web.routes.analyze import router as analyze_router
    from web.routes.stats import router as stats_router
    from web.routes.graph import router as graph_router
    from web.routes.pet import router as pet_router
    from web.routes.settings import router as settings_router

    app.include_router(qa_router, prefix="/api")
    app.include_router(ingest_router, prefix="/api")
    app.include_router(search_router, prefix="/api")
    app.include_router(analyze_router, prefix="/api")
    app.include_router(stats_router, prefix="/api")
    app.include_router(graph_router, prefix="/api")
    app.include_router(pet_router, prefix="/api")
    app.include_router(settings_router, prefix="/api")

    # 前端 — React 单页（Vite 构建产物）
    index_html = FRONTEND_DIST_DIR / "index.html"

    @app.get("/")
    async def index():
        """返回 React 前端入口。"""
        if not index_html.exists():
            return Response("前端尚未构建，请运行 `cd web/frontend && npm install && npm run build`", status_code=503)
        return Response(index_html.read_bytes(), media_type="text/html")

    # SPA 回退：非 /api 路径全部返回 index.html（供浏览器直接刷新子路径）
    @app.get("/{full_path:path}")
    async def spa_fallback(full_path: str):
        if full_path.startswith("api/"):
            from fastapi import HTTPException
            raise HTTPException(status_code=404, detail="接口不存在")
        if not index_html.exists():
            return Response("前端尚未构建，请运行 `cd web/frontend && npm install && npm run build`", status_code=503)
        return Response(index_html.read_bytes(), media_type="text/html")

    return app

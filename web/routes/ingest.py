"""文档入库 — 文件上传 / URL / 剪贴板。

POST /api/ingest/upload   multipart 文件上传（支持批量）
POST /api/ingest/url      JSON {url}
POST /api/ingest/clip     剪贴板入库 {title, content}
"""
from __future__ import annotations

import tempfile
from pathlib import Path
from typing import List, Optional

from fastapi import APIRouter, UploadFile, File, Request
from pydantic import BaseModel

from config import settings
from services.ingest_service import IngestService

router = APIRouter(tags=["ingest"])


@router.post("/ingest/upload")
async def ingest_upload(request: Request, files: List[UploadFile] = File(...)):
    """多文件上传入库。"""
    from web.app import _get_shared_storage, invalidate_health_cache

    storage = _get_shared_storage(request.app)
    service = IngestService(storage=storage)
    # 上传文件大小上限(字节): 100MB,防止 OOM
    MAX_UPLOAD_SIZE = 100 * 1024 * 1024

    results = []
    for f in files:
        raw_name = f.filename or "unknown"
        # 安全:取纯文件名,防止路径遍历(../.. / 绝对路径)
        safe_name = Path(raw_name).name
        if not safe_name or safe_name in (".", ".."):
            safe_name = "unknown"
        suffix = Path(safe_name).suffix
        tmp_path: Optional[Path] = None
        try:
            with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
                # 流式落盘,避免大文件 OOM
                total = 0
                while True:
                    chunk = await f.read(64 * 1024)
                    if not chunk:
                        break
                    total += len(chunk)
                    if total > MAX_UPLOAD_SIZE:
                        raise ValueError(f"文件超过大小限制 {MAX_UPLOAD_SIZE // 1024 // 1024}MB")
                    tmp.write(chunk)
                tmp_path = Path(tmp.name)
        except Exception as e:
            results.append({
                "filename": safe_name, "status": "failed",
                "error": f"保存临时文件失败: {e}", "error_type": "unknown",
            })
            if tmp_path:
                try:
                    tmp_path.unlink()
                except Exception:
                    pass
            continue

        # 修复冗余复制（P1-架构 统一入库路径）：
        # 原实现先把 tmp 复制到 uploads/quick/<safe_name>，再调 ingest_file
        # (copy_file=True 默认) 又复制到 uploads/<doc_id[:2]>/，
        # 导致 quick 目录留下孤儿文件。
        # 现在：直接让 IngestService 处理复制（copy_file=True 默认），
        # original_name 仅用作显示名，不影响实际存储路径。

        result = service.ingest_file(tmp_path, original_name=safe_name)
        results.append({
            "filename": result.filename,
            "status": result.status,
            "doc_id": result.doc_id,
            "title": result.title,
            "tags": result.tags,
            "chunks": result.chunks,
            "tokens": result.tokens,
            "error": result.error,
            "error_type": result.error_type,
        })

        try:
            tmp_path.unlink()
        except Exception:
            pass

    invalidate_health_cache(request.app)
    return {"results": results}


class URLIngestBody(BaseModel):
    url: str


@router.post("/ingest/url")
async def ingest_url(body: URLIngestBody, request: Request):
    """URL 网页入库。"""
    from web.app import _get_shared_storage, invalidate_health_cache
    from core.ingestion.quick import save_url

    url = body.url
    if not (url.startswith("http://") or url.startswith("https://")):
        url = "https://" + url

    storage = _get_shared_storage(request.app)
    service = IngestService(storage=storage)
    try:
        file_path = save_url(url)
    except Exception as e:
        return {
            "status": "failed",
            "error": f"抓取失败: {type(e).__name__}: {e}",
            "error_type": "unknown",
        }

    result = service.ingest_file(file_path, original_name=url)
    invalidate_health_cache(request.app)
    return {
        "status": result.status,
        "doc_id": result.doc_id,
        "title": result.title,
        "tags": result.tags,
        "chunks": result.chunks,
        "tokens": result.tokens,
        "error": result.error,
        "error_type": result.error_type,
    }


class ClipIngestBody(BaseModel):
    title: str = ""
    content: str


@router.post("/ingest/clip")
async def ingest_clip(body: ClipIngestBody, request: Request):
    """剪贴板文本入库。"""
    from web.app import _get_shared_storage, invalidate_health_cache

    storage = _get_shared_storage(request.app)
    service = IngestService(storage=storage)

    result = service.ingest_text(
        content=body.content,
        title=body.title,
        source="clipboard",
    )
    invalidate_health_cache(request.app)
    return {
        "status": result.status,
        "doc_id": result.doc_id,
        "title": result.title,
        "tags": result.tags,
        "chunks": result.chunks,
        "tokens": result.tokens,
        "error": result.error,
        "error_type": result.error_type,
    }


@router.get("/documents")
async def list_documents(request: Request, limit: int = 200, offset: int = 0):
    """返回已入库文档列表（按时间倒序）。"""
    from web.app import _get_shared_storage

    storage = _get_shared_storage(request.app)
    docs = storage.list_documents(limit=limit, offset=offset)
    return {
        "total": len(docs),
        "documents": [
            {
                "id": d.id,
                "title": d.title,
                "file_name": d.file_name,
                "file_type": d.file_type,
                "file_size": d.file_size,
                "language": d.language,
                "created_at": d.created_at,
                "chunk_count": d.chunk_count,
                "total_tokens": d.total_tokens,
                "tags": d.tags,
            }
            for d in docs
        ],
    }


@router.get("/documents/{doc_id}/content")
async def get_document_content(doc_id: str, request: Request):
    """按 doc_id 获取文档完整内容（用于引用查看）。"""
    from fastapi import HTTPException

    from web.app import _get_shared_storage

    storage = _get_shared_storage(request.app)
    doc = storage.get_document(doc_id)
    if not doc:
        raise HTTPException(status_code=404, detail="文档不存在")
    chunks = storage.get_chunks(doc.id)
    content = "\n".join(c.content for c in chunks)
    return {
        "doc_id": doc.id,
        "title": doc.title,
        "file_name": doc.file_name,
        "chunk_count": doc.chunk_count,
        "content": content,
    }


@router.delete("/documents/{doc_id}")
async def delete_documents(doc_id: str, request: Request):
    """删除已入库文档（含分块、原文件、向量、索引）。"""
    from fastapi import HTTPException

    from web.app import _get_shared_storage, invalidate_health_cache

    storage = _get_shared_storage(request.app)
    ok = storage.delete_document(doc_id)
    if not ok:
        raise HTTPException(status_code=404, detail="文档不存在")
    invalidate_health_cache(request.app)
    return {"deleted": doc_id}

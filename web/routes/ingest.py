"""文档入库 — 文件上传 / URL / 剪贴板。

POST /api/ingest/upload   multipart 文件上传（支持批量）
POST /api/ingest/url      JSON {url}
POST /api/ingest/clip     剪贴板入库 {title, content}
"""
from __future__ import annotations

import tempfile
import shutil
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

        # 保留一份到 quick 目录(使用安全文件名)
        quick_dir = Path(settings.storage_path) / "uploads" / "quick"
        quick_dir.mkdir(parents=True, exist_ok=True)
        dest = quick_dir / safe_name
        try:
            shutil.copy(tmp_path, dest)
        except Exception:
            pass

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

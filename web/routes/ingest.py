"""文档入库 — 文件上传 / URL / 剪贴板。

POST /api/ingest/upload   multipart 文件上传
POST /api/ingest/url      JSON {url}
POST /api/ingest/clip     剪贴板入库
"""
from __future__ import annotations

import hashlib
import tempfile
import shutil
from pathlib import Path
from typing import List

from fastapi import APIRouter, UploadFile, File, Form, HTTPException, Request
from pydantic import BaseModel

from config import settings
from core.storage import Storage
from core.ingestion.parser import parse, is_supported, ParseError
from core.ingestion.chunker import chunk_document

router = APIRouter(tags=["ingest"])


class IngestResult(BaseModel):
    filename: str
    status: str  # "success" | "failed" | "skipped"
    doc_id: str = ""
    title: str = ""
    tags: list = []
    chunks: int = 0
    error: str = ""


def _ingest_file(file_path: Path, storage: Storage) -> IngestResult:
    """入库单个文件，返回结果。"""

    if not is_supported(file_path):
        return IngestResult(
            filename=file_path.name,
            status="skipped",
            error="不支持的格式",
        )

    try:
        parsed = parse(file_path)
        if not parsed.text.strip():
            return IngestResult(
                filename=file_path.name,
                status="skipped",
                error="空内容" if not parsed.meta.get("ocr_unavailable") else "OCR 未安装",
            )

        chunks = chunk_document(parsed, chunk_size=settings.chunk_size, chunk_overlap=settings.chunk_overlap)

        # 去重
        content_hash = hashlib.sha256(parsed.text.encode("utf-8")).hexdigest()
        doc_id = content_hash[:32]
        if storage.get_document(doc_id) is not None:
            return IngestResult(
                filename=file_path.name,
                status="skipped",
                doc_id=doc_id,
                error="已存在（重复内容）",
            )

        # 自动标签
        tags = []
        if settings.has_llm():
            try:
                from core.classify.tagger import Tagger
                tagger = Tagger()
                tags = tagger.generate_tags_for_document(parsed)
            except Exception:
                pass

        record = storage.save_document(parsed, chunks, copy_file=True, tags=tags)
        return IngestResult(
            filename=file_path.name,
            status="success",
            doc_id=record.id,
            title=record.title,
            tags=tags,
            chunks=record.chunk_count,
        )

    except ParseError as e:
        return IngestResult(filename=file_path.name, status="failed", error=str(e))
    except Exception as e:
        return IngestResult(filename=file_path.name, status="failed", error=f"{type(e).__name__}: {e}")


@router.post("/ingest/upload")
async def ingest_upload(request: Request, files: List[UploadFile] = File(...)):
    """多文件上传入库。"""
    from web.app import _get_shared_storage, invalidate_health_cache

    storage = _get_shared_storage(request.app)
    results = []
    for f in files:
        # 保存临时文件
        suffix = Path(f.filename or "unknown").suffix
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
            content = await f.read()
            tmp.write(content)
            tmp_path = Path(tmp.name)

        # 也保存到 quick 目录
        quick_dir = Path(settings.storage_path) / "uploads" / "quick"
        quick_dir.mkdir(parents=True, exist_ok=True)
        dest = quick_dir / (f.filename or "unknown")
        shutil.copy(tmp_path, dest)

        result = _ingest_file(tmp_path, storage)
        results.append(result.model_dump())

        # 清理
        try:
            tmp_path.unlink()
        except Exception:
            pass

    # 入库后清空健康缓存
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

    quick_dir = Path(settings.storage_path) / "uploads" / "quick"
    quick_dir.mkdir(parents=True, exist_ok=True)

    storage = _get_shared_storage(request.app)
    file_path = save_url(url)
    result = _ingest_file(file_path, storage)

    # 入库后清空健康缓存
    invalidate_health_cache(request.app)
    return {
        "status": result.status,
        "doc_id": result.doc_id,
        "title": result.title,
        "tags": result.tags,
        "chunks": result.chunks,
    }

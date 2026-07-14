"""文档入库 — 文件上传 / URL / 剪贴板。

POST /api/ingest/upload   multipart 文件上传（支持批量）
POST /api/ingest/url      JSON {url}
POST /api/ingest/clip     剪贴板入库 {title, content}
"""
from __future__ import annotations

import hashlib
import tempfile
import shutil
from pathlib import Path
from typing import List

from fastapi import APIRouter, UploadFile, File, Request
from pydantic import BaseModel

from config import settings
from core.storage import Storage
from core.ingestion.parser import parse, is_supported, ParseError, ParsedDocument
from core.ingestion.chunker import chunk_document

router = APIRouter(tags=["ingest"])


class IngestResult(BaseModel):
    filename: str
    status: str  # "success" | "failed" | "skipped"
    doc_id: str = ""
    title: str = ""
    tags: list = []
    chunks: int = 0
    tokens: int = 0
    error: str = ""
    error_type: str = ""  # "unsupported" | "empty" | "duplicate" | "parse" | "unknown"


def _ingest_file(file_path: Path, storage: Storage, original_name: str = "") -> IngestResult:
    """入库单个文件，返回结果。"""

    display_name = original_name or file_path.name

    if not is_supported(file_path):
        return IngestResult(
            filename=display_name,
            status="skipped",
            error=f"不支持的格式 ({file_path.suffix})",
            error_type="unsupported",
        )

    try:
        parsed = parse(file_path)
        if not parsed.text.strip():
            reason = "OCR 未安装" if parsed.meta.get("ocr_unavailable") else "内容为空"
            return IngestResult(
                filename=display_name,
                status="skipped",
                error=reason,
                error_type="empty",
            )

        chunks = chunk_document(parsed, chunk_size=settings.chunk_size, chunk_overlap=settings.chunk_overlap)

        # 去重
        content_hash = hashlib.sha256(parsed.text.encode("utf-8")).hexdigest()
        doc_id = content_hash[:32]
        if storage.get_document(doc_id) is not None:
            return IngestResult(
                filename=display_name,
                status="skipped",
                doc_id=doc_id,
                error="已存在（重复内容）",
                error_type="duplicate",
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
            filename=display_name,
            status="success",
            doc_id=record.id,
            title=record.title,
            tags=tags,
            chunks=record.chunk_count,
            tokens=record.total_tokens,
        )

    except ParseError as e:
        return IngestResult(filename=display_name, status="failed", error=str(e), error_type="parse")
    except Exception as e:
        return IngestResult(
            filename=display_name,
            status="failed",
            error=f"{type(e).__name__}: {e}",
            error_type="unknown",
        )


@router.post("/ingest/upload")
async def ingest_upload(request: Request, files: List[UploadFile] = File(...)):
    """多文件上传入库。"""
    from web.app import _get_shared_storage, invalidate_health_cache

    storage = _get_shared_storage(request.app)
    results = []
    for f in files:
        original_name = f.filename or "unknown"
        suffix = Path(original_name).suffix
        try:
            with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
                content = await f.read()
                tmp.write(content)
                tmp_path = Path(tmp.name)
        except Exception as e:
            results.append(IngestResult(
                filename=original_name, status="failed",
                error=f"保存临时文件失败: {e}", error_type="unknown",
            ).model_dump())
            continue

        # 保留一份到 quick 目录
        quick_dir = Path(settings.storage_path) / "uploads" / "quick"
        quick_dir.mkdir(parents=True, exist_ok=True)
        dest = quick_dir / original_name
        try:
            shutil.copy(tmp_path, dest)
        except Exception:
            pass

        result = _ingest_file(tmp_path, storage, original_name=original_name)
        results.append(result.model_dump())

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
    try:
        file_path = save_url(url)
    except Exception as e:
        return {
            "status": "failed",
            "error": f"抓取失败: {type(e).__name__}: {e}",
            "error_type": "unknown",
        }

    result = _ingest_file(file_path, storage, original_name=url)
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

    content = body.content.strip()
    if not content:
        return {
            "status": "skipped",
            "error": "内容为空",
            "error_type": "empty",
        }

    title = body.title.strip() or f"剪贴板_{hashlib.md5(content.encode()).hexdigest()[:6]}"

    storage = _get_shared_storage(request.app)

    # 构造 ParsedDocument 直接入库（不走文件解析）
    tmp_path = Path(settings.storage_path) / "uploads" / "quick" / f"{title}.txt"
    tmp_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path.write_text(content, encoding="utf-8")

    parsed = ParsedDocument(
        text=content,
        title=title,
        file_path=tmp_path,
        file_type=".txt",
        language="zh",
        meta={"source": "clipboard"},
    )

    content_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
    doc_id = content_hash[:32]
    if storage.get_document(doc_id) is not None:
        return {
            "status": "skipped",
            "doc_id": doc_id,
            "error": "已存在（重复内容）",
            "error_type": "duplicate",
        }

    chunks = chunk_document(parsed, chunk_size=settings.chunk_size, chunk_overlap=settings.chunk_overlap)
    tags = []
    if settings.has_llm():
        try:
            from core.classify.tagger import Tagger
            tagger = Tagger()
            tags = tagger.generate_tags_for_document(parsed)
        except Exception:
            pass

    record = storage.save_document(parsed, chunks, copy_file=False, tags=tags)
    invalidate_health_cache(request.app)
    return {
        "status": "success",
        "doc_id": record.id,
        "title": record.title,
        "tags": tags,
        "chunks": record.chunk_count,
        "tokens": record.total_tokens,
    }

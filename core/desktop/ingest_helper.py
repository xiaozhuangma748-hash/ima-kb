"""桌面宠物入库辅助（Task 1）。

零侵入约束：
- 本模块属于 ``core/desktop/`` 新增模块，不修改项目任何现有文件。
- 复用 ``core.parser`` / ``core.chunking`` / ``core.storage`` 的公开 API，
  不调用 ``run._ingest_one``（其 rich 控制台输出不适合桌面静默场景）。

设计：
- ``ingest_file`` 为纯函数式入库：解析 → 分块 → 去重 → 标签 → 保存。
- 全程无控制台输出，结果以 dict 返回（供 bridge 推 JS 气泡提示）。
- 已入库（内容哈希相同）返回 ``error="already_exists"``，由调用方友好提示。
"""
from __future__ import annotations

import hashlib
import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

__all__ = ["ingest_file"]


def _is_supported(file_path: Path) -> bool:
    """复用 run.is_supported（若可用），否则按扩展名白名单兜底。"""
    try:
        from run import is_supported  # type: ignore
        return bool(is_supported(file_path))
    except Exception:
        pass
    # 兜底：常见可解析扩展名
    exts = {
        ".pdf", ".docx", ".doc", ".pptx", ".ppt", ".xlsx", ".xls",
        ".md", ".markdown", ".txt", ".py", ".js", ".ts", ".java",
        ".html", ".htm", ".png", ".jpg", ".jpeg", ".webp", ".csv",
    }
    return file_path.suffix.lower() in exts


def ingest_file(file_path: str, storage=None, auto_tag: bool = True) -> dict:
    """入库单个文件（桌面宠物拖拽场景，静默无控制台输出）。

    Args:
        file_path: 本地文件绝对路径（已去除 file:// 前缀）。
        storage: ``Storage`` 实例；为 None 时内部新建。
        auto_tag: 是否调用 LLM 自动打标签（失败静默，不影响入库）。

    Returns:
        dict:
            success (bool): 是否成功。
            error (str|None): 失败原因；``already_exists`` 表示已入库。
            file_name (str): 文件名。
            doc_id (str|None): 文档 ID（内容哈希前 32 位）。
            chunk_count (int): 分块数。
    """
    result = {
        "success": False,
        "error": None,
        "file_name": "",
        "doc_id": None,
        "chunk_count": 0,
    }

    path = Path(file_path)
    result["file_name"] = path.name

    if not path.exists():
        result["error"] = f"文件不存在: {path.name}"
        return result
    if not path.is_file():
        result["error"] = "不是文件（不支持文件夹）"
        return result
    if not _is_supported(path):
        result["error"] = f"不支持的格式: {path.suffix or '无扩展名'}"
        return result

    try:
        from config import settings
        from core.ingestion.parser import parse, ParseError
        from core.ingestion.chunker import chunk_document

        if storage is None:
            from core.storage import Storage
            storage = Storage()

        # 1. 解析
        try:
            parsed = parse(path)
        except ParseError as e:
            result["error"] = f"解析失败: {e}"
            return result

        if not parsed.text.strip():
            if parsed.meta.get("ocr_unavailable"):
                result["error"] = "图片需 OCR（brew install tesseract tesseract-lang）"
            else:
                result["error"] = "未解析到文本内容"
            return result

        # 2. 分块
        chunks = chunk_document(
            parsed,
            chunk_size=settings.chunk_size,
            chunk_overlap=settings.chunk_overlap,
        )

        # 3. 去重（内容哈希）
        content_hash = hashlib.sha256(parsed.text.encode("utf-8")).hexdigest()
        doc_id = content_hash[:32]
        result["doc_id"] = doc_id
        if storage.get_document(doc_id) is not None:
            result["error"] = "already_exists"
            return result

        # 4. 自动标签（可选，失败静默）
        tags = []
        if auto_tag and getattr(settings, "has_llm", lambda: False)():
            try:
                from core.classify.tagger import Tagger
                tags = Tagger().generate_tags_for_document(parsed) or []
            except Exception as e:
                logger.info(f"标签生成失败（不影响入库）: {e}")

        # 5. 保存
        record = storage.save_document(parsed, chunks, copy_file=True, tags=tags)
        result["chunk_count"] = getattr(record, "chunk_count", len(chunks))
        result["success"] = True
        return result

    except Exception as e:
        logger.error(f"入库失败: {type(e).__name__}: {e}")
        result["error"] = f"{type(e).__name__}: {e}"
        return result

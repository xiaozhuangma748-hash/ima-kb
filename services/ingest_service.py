"""文档入库服务：解析 + 分块 + 去重 + 标签 + 保存。

CLI (run.py _ingest_one) 和 Web (web/routes/ingest.py _ingest_file) 共用此服务，
消除两处重复的入库流程代码。
"""
from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, List

from config import settings
from core.storage import Storage
from core.ingestion.parser import parse, is_supported, ParseError, ParsedDocument
from core.ingestion.chunker import chunk_document

logger = logging.getLogger(__name__)


@dataclass
class IngestResult:
    """入库结果。"""
    filename: str
    status: str  # "success" | "failed" | "skipped"
    doc_id: str = ""
    title: str = ""
    tags: list = field(default_factory=list)
    chunks: int = 0
    tokens: int = 0
    error: str = ""
    error_type: str = ""  # "unsupported" | "empty" | "duplicate" | "parse" | "unknown"


class IngestService:
    """文档入库服务。

    封装解析 → 分块 → 去重 → 标签 → 保存的完整流程，
    CLI 和 Web 共用同一套逻辑。
    """

    def __init__(self, storage: Optional[Storage] = None) -> None:
        """初始化入库服务。

        Args:
            storage: 存储实例（不传则自动创建）
        """
        self.storage = storage or Storage()

    def ingest_file(
        self,
        file_path: Path,
        original_name: str = "",
        auto_tag: bool = True,
        copy_file: bool = True,
    ) -> IngestResult:
        """入库单个文件。

        Args:
            file_path: 文件路径
            original_name: 显示用的原始文件名（Web 上传时与临时文件名不同）
            auto_tag: 是否调用 LLM 自动打标签
            copy_file: 是否复制原文件到 uploads 目录

        Returns:
            IngestResult
        """
        display_name = original_name or file_path.name

        # 1. 格式检查
        if not is_supported(file_path):
            return IngestResult(
                filename=display_name,
                status="skipped",
                error=f"不支持的格式 ({file_path.suffix})",
                error_type="unsupported",
            )

        try:
            # 2. 解析
            parsed = parse(file_path)
            if not parsed.text.strip():
                reason = "OCR 未安装" if parsed.meta.get("ocr_unavailable") else "内容为空"
                return IngestResult(
                    filename=display_name,
                    status="skipped",
                    error=reason,
                    error_type="empty",
                )

            # 3. 分块
            chunks = chunk_document(
                parsed,
                chunk_size=settings.chunk_size,
                chunk_overlap=settings.chunk_overlap,
            )

            # 4. 去重
            content_hash = hashlib.sha256(parsed.text.encode("utf-8")).hexdigest()
            doc_id = content_hash[:32]
            if self.storage.get_document(doc_id) is not None:
                return IngestResult(
                    filename=display_name,
                    status="skipped",
                    doc_id=doc_id,
                    error="已存在（重复内容）",
                    error_type="duplicate",
                )

            # 5. 自动标签
            tags = []
            if auto_tag and settings.has_llm():
                try:
                    from core.classify.tagger import Tagger
                    tagger = Tagger()
                    tags = tagger.generate_tags_for_document(parsed)
                except Exception as e:
                    logger.warning(f"标签生成失败: {e}")

            # 6. 保存
            record = self.storage.save_document(
                parsed, chunks, copy_file=copy_file, tags=tags,
            )
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
            return IngestResult(
                filename=display_name, status="failed",
                error=str(e), error_type="parse",
            )
        except Exception as e:
            logger.exception(f"入库失败: {display_name}")
            return IngestResult(
                filename=display_name, status="failed",
                error=f"{type(e).__name__}: {e}", error_type="unknown",
            )

    def ingest_text(
        self,
        content: str,
        title: str = "",
        source: str = "clipboard",
        auto_tag: bool = True,
    ) -> IngestResult:
        """文本直入库（剪贴板 / 笔记 / URL 提取正文）。

        Args:
            content: 文本内容
            title: 标题（不传则自动生成）
            source: 来源标记
            auto_tag: 是否自动打标签

        Returns:
            IngestResult
        """
        content = content.strip()
        if not content:
            return IngestResult(
                filename=title or "未命名", status="skipped",
                error="内容为空", error_type="empty",
            )

        if not title:
            title = f"剪贴板_{hashlib.md5(content.encode()).hexdigest()[:6]}"

        # 构造 ParsedDocument（不走文件解析）
        tmp_path = Path(settings.storage_path) / "uploads" / "quick" / f"{title}.txt"
        tmp_path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path.write_text(content, encoding="utf-8")

        parsed = ParsedDocument(
            text=content,
            title=title,
            file_path=tmp_path,
            file_type=".txt",
            language="zh",
            meta={"source": source},
        )

        # 去重
        content_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
        doc_id = content_hash[:32]
        if self.storage.get_document(doc_id) is not None:
            return IngestResult(
                filename=title, status="skipped",
                doc_id=doc_id, error="已存在（重复内容）", error_type="duplicate",
            )

        # 分块
        chunks = chunk_document(
            parsed,
            chunk_size=settings.chunk_size,
            chunk_overlap=settings.chunk_overlap,
        )

        # 标签
        tags = []
        if auto_tag and settings.has_llm():
            try:
                from core.classify.tagger import Tagger
                tagger = Tagger()
                tags = tagger.generate_tags_for_document(parsed)
            except Exception as e:
                logger.warning(f"标签生成失败: {e}")

        # 保存
        record = self.storage.save_document(parsed, chunks, copy_file=False, tags=tags)
        return IngestResult(
            filename=title, status="success",
            doc_id=record.id, title=record.title,
            tags=tags, chunks=record.chunk_count, tokens=record.total_tokens,
        )

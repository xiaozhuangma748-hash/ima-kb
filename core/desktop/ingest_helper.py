"""桌面宠物入库辅助（Task 1）。

零侵入约束：
- 本模块属于 ``core/desktop/`` 新增模块，不修改项目任何现有文件。
- 复用 ``IngestService`` 的完整入库流程（解析 → 分块 → Contextual Retrieval →
  去重 → 标签 → 保存），与 CLI / Web 路径行为一致。

设计：
- ``ingest_file`` 为薄包装：调用 IngestService.ingest_file，把 IngestResult 转 dict
  返回（供 bridge 推 JS 气泡提示）。
- 全程无控制台输出，结果以 dict 返回。
- 已入库（内容哈希相同）返回 ``error="already_exists"``，由调用方友好提示。

统一入库路径改造（P1-架构）：
- 原实现独立完成"解析→分块→去重→标签→保存"，缺失 Contextual Retrieval。
- 改为调用 IngestService，自动获得 Contextual Retrieval 能力，
  并与 CLI/Web 路径行为对齐。
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

__all__ = ["ingest_file"]


def ingest_file(file_path: str, storage=None, auto_tag: bool = True) -> dict:
    """入库单个文件（桌面宠物拖拽场景，静默无控制台输出）。

    Args:
        file_path: 本地文件绝对路径（已去除 file:// 前缀）。
        storage: ``Storage`` 实例；为 None 时由 IngestService 内部新建。
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

    try:
        from services.ingest_service import IngestService

        service = IngestService(storage=storage)
        ingest_result = service.ingest_file(
            path, auto_tag=auto_tag, copy_file=True,
        )

        # 把 IngestResult 转 dict（保持原接口兼容）
        result["doc_id"] = ingest_result.doc_id or None
        result["chunk_count"] = ingest_result.chunks

        if ingest_result.status == "success":
            result["success"] = True
            return result

        # 失败/跳过：映射 error 字段
        if ingest_result.status == "skipped":
            if ingest_result.error_type == "duplicate":
                result["error"] = "already_exists"
            elif ingest_result.error_type == "empty":
                # 区分 OCR 未安装和真空内容
                result["error"] = ingest_result.error or "未解析到文本内容"
            elif ingest_result.error_type == "unsupported":
                result["error"] = f"不支持的格式: {path.suffix or '无扩展名'}"
            else:
                result["error"] = ingest_result.error or "跳过"
        else:
            result["error"] = ingest_result.error or "入库失败"
        return result

    except Exception as e:
        logger.error(f"入库失败: {type(e).__name__}: {e}")
        result["error"] = f"{type(e).__name__}: {e}"
        return result

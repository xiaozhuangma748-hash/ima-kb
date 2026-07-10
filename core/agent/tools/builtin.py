"""内置工具集：从 ``agent.py`` 迁移的 6 个工具。

每个工具用 ``@register_tool`` 装饰，自动注册到全局 Registry。
文案与逻辑与原 ``_tool_*`` 方法逐字一致；依赖通过 ``ToolContext`` 注入。
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional, Tuple, Type

from pydantic import BaseModel

from .base import Tool, ToolContext, register_tool


__all__ = [
    "SearchArgs",
    "SearchTool",
    "ListDocsArgs",
    "ListDocsTool",
    "GetDocArgs",
    "GetDocTool",
    "AnalyzeArgs",
    "AnalyzeTool",
    "ReadArgs",
    "ReadTool",
    "ReadMultiArgs",
    "ReadMultiTool",
]


# ============================================================
# 1. search — BM25 搜索知识库
# ============================================================

class SearchArgs(BaseModel):
    query: str


@register_tool
@dataclass
class SearchTool(Tool):
    name: str = "search"
    description: str = "BM25 搜索知识库（按关键词找内容）"
    args_schema: Optional[Type[BaseModel]] = SearchArgs
    prompt_block: str = (
        'search — BM25 搜索知识库（按关键词找内容）\n'
        '   {"tool": "search", "args": "搜索关键词"}'
    )

    def _parse_args_str(self, args_str: str) -> Tuple[Dict[str, Any], Optional[str]]:
        query = args_str.strip()
        if not query:
            return {}, "[错误] 搜索关键词不能为空"
        return {"query": query}, None

    def execute(self, context: Optional[ToolContext] = None, *, query: str, **_: Any) -> str:
        results = context.storage.bm25_search(query, top_k=5)
        if not results:
            return "[无结果] 未找到相关内容"

        lines = [f"找到 {len(results)} 条结果：\n"]
        for i, r in enumerate(results, 1):
            lines.append(f"[{i}] {r.doc_title} (相关度 {r.score:.2f})")
            lines.append(f"    {r.content[:200]}...")
        return "\n".join(lines)


# ============================================================
# 2. list_docs — 列出所有已入库文档
# ============================================================

class ListDocsArgs(BaseModel):
    pass


@register_tool
@dataclass
class ListDocsTool(Tool):
    name: str = "list_docs"
    description: str = "列出所有已入库文档"
    args_schema: Optional[Type[BaseModel]] = ListDocsArgs
    prompt_block: str = (
        'list_docs — 列出所有已入库文档\n'
        '   {"tool": "list_docs", "args": ""}'
    )

    def _parse_args_str(self, args_str: str) -> Tuple[Dict[str, Any], Optional[str]]:
        # 原实现忽略参数
        return {}, None

    def execute(self, context: Optional[ToolContext] = None, **_: Any) -> str:
        docs = context.storage.list_documents()
        if not docs:
            return "[空] 知识库中没有文档"

        lines = [f"共 {len(docs)} 篇文档：\n"]
        for d in docs:
            lines.append(
                f"  {d.id[:8]}  {d.title}  "
                f"[{d.chunk_count}段] [{','.join(d.tags[:3])}]"
            )
        return "\n".join(lines)


# ============================================================
# 3. get_doc — 查看文档详情和前 3 段预览
# ============================================================

class GetDocArgs(BaseModel):
    doc_id: str


@register_tool
@dataclass
class GetDocTool(Tool):
    name: str = "get_doc"
    description: str = "查看文档详情和前 3 段预览"
    args_schema: Optional[Type[BaseModel]] = GetDocArgs
    prompt_block: str = (
        'get_doc — 查看文档详情和前 3 段预览\n'
        '   {"tool": "get_doc", "args": "文档ID前8位"}'
    )

    def _parse_args_str(self, args_str: str) -> Tuple[Dict[str, Any], Optional[str]]:
        args = args_str.strip()
        if not args:
            return {}, "[错误] 请指定文档ID"
        return {"doc_id": args[:8]}, None

    def execute(self, context: Optional[ToolContext] = None, *, doc_id: str, **_: Any) -> str:
        doc = context.storage.get_document(doc_id)
        if not doc:
            return f"[错误] 文档不存在: {doc_id}"

        # 获取前 3 段预览（保留原调用；注意：原代码即如此调用）
        chunks = context.storage.get_chunks_by_doc(doc_id, limit=3)
        preview = "\n".join(
            f"  第{i+1}段：{c.content[:200]}..."
            for i, c in enumerate(chunks)
        )

        return (
            f"文档: {doc.title}\n"
            f"ID: {doc.id}\n"
            f"标签: {', '.join(doc.tags)}\n"
            f"总段落: {doc.chunk_count}\n"
            f"总字数: {doc.total_tokens}\n\n"
            f"前 3 段预览：\n{preview}"
        )


# ============================================================
# 4. read — 读取文档指定段落的原文（1000 字）
# ============================================================

class ReadArgs(BaseModel):
    doc_id: str
    chunk_num: int = 1


@register_tool
@dataclass
class ReadTool(Tool):
    name: str = "read"
    description: str = "读取文档指定段落的原文（1000 字）"
    args_schema: Optional[Type[BaseModel]] = ReadArgs
    prompt_block: str = (
        'read — 读取文档指定段落的原文（1000 字）\n'
        '   {"tool": "read", "args": "文档ID前8位 段落号"}\n'
        '   段落号从 1 开始，如 "862e0973 3" 读第 3 段'
    )

    def _parse_args_str(self, args_str: str) -> Tuple[Dict[str, Any], Optional[str]]:
        args = args_str.strip()
        if not args:
            return {}, "[错误] 请指定文档ID，格式: 文档ID 段落号"

        parts = args.split(None, 1)
        doc_id = parts[0].strip()
        chunk_num = 1
        if len(parts) > 1:
            try:
                chunk_num = int(parts[1].strip())
                if chunk_num < 1:
                    chunk_num = 1
            except ValueError:
                return {}, f"[错误] 段落号必须是数字: {parts[1]}"
        return {"doc_id": doc_id, "chunk_num": chunk_num}, None

    def execute(
        self,
        context: Optional[ToolContext] = None,
        *,
        doc_id: str,
        chunk_num: int = 1,
        **_: Any,
    ) -> str:
        try:
            from core.reader.reader import SmartReader

            sr = SmartReader(storage=context.storage)
            state = sr.open(doc_id)
            total = state.total_chunks
            if chunk_num > total:
                return f"[错误] 该文档共 {total} 段，你请求第 {chunk_num} 段（超出范围）"
            sr.goto(chunk_num - 1)
            chunk = sr.current_chunk()
            return (
                f"文档: {state.doc_title} (共 {total} 段)\n\n"
                f"第 {chunk_num} 段内容：\n{chunk.content[:1000]}"
            )
        except Exception as e:
            return f"阅读失败: {e}"


# ============================================================
# 5. read_multi — 一次读取多段（高效）
# ============================================================

class ReadMultiArgs(BaseModel):
    doc_id: str
    start: int
    end: int


@register_tool
@dataclass
class ReadMultiTool(Tool):
    name: str = "read_multi"
    description: str = "一次读取多段（高效！比逐段 read 省步数）"
    args_schema: Optional[Type[BaseModel]] = ReadMultiArgs
    prompt_block: str = (
        'read_multi — 一次读取多段（高效！比逐段 read 省步数）\n'
        '   {"tool": "read_multi", "args": "文档ID前8位 起始段-结束段"}\n'
        '   如 "862e0973 1-5" 读第 1 到 5 段'
    )

    def _parse_args_str(self, args_str: str) -> Tuple[Dict[str, Any], Optional[str]]:
        args = args_str.strip()
        if not args:
            return {}, "[错误] 格式: 文档ID 起始段-结束段，如 862e0973 1-5"

        parts = args.split(None, 1)
        if len(parts) < 2:
            return {}, "[错误] 请指定段落范围，如 862e0973 1-5"
        doc_id = parts[0].strip()
        range_str = parts[1].strip()

        range_match = re.match(r"^(\d+)\s*[-~]\s*(\d+)$", range_str)
        if not range_match:
            return {}, f"[错误] 段落范围格式错误: {range_str}，应为 起始-结束，如 1-5"

        start = int(range_match.group(1))
        end = int(range_match.group(2))
        if start < 1:
            start = 1
        if end < start:
            return {}, f"[错误] 结束段 {end} 小于起始段 {start}"
        return {"doc_id": doc_id, "start": start, "end": end}, None

    def execute(
        self,
        context: Optional[ToolContext] = None,
        *,
        doc_id: str,
        start: int,
        end: int,
        **_: Any,
    ) -> str:
        try:
            from core.reader.reader import SmartReader

            sr = SmartReader(storage=context.storage)
            state = sr.open(doc_id)
            total = state.total_chunks
            if start > total:
                return f"[错误] 起始段 {start} 超出范围（共 {total} 段）"
            if end > total:
                end = total
            if end - start + 1 > 8:
                end = start + 7

            lines = [f"文档: {state.doc_title} (共 {total} 段，读取 {start}-{end} 段)\n"]
            for i in range(start, end + 1):
                sr.goto(i - 1)
                chunk = sr.current_chunk()
                lines.append(f"--- 第 {i} 段 ---\n{chunk.content[:500]}\n")
            return "\n".join(lines)
        except Exception as e:
            return f"阅读失败: {e}"


# ============================================================
# 6. analyze — 数据表分析（Excel/CSV/JSON）
# ============================================================

class AnalyzeArgs(BaseModel):
    file_path: str


@register_tool
@dataclass
class AnalyzeTool(Tool):
    name: str = "analyze"
    description: str = "数据表分析（Excel/CSV/JSON）"
    args_schema: Optional[Type[BaseModel]] = AnalyzeArgs
    prompt_block: str = (
        'analyze — 数据表分析（Excel/CSV/JSON）\n'
        '   {"tool": "analyze", "args": "文件路径"}'
    )

    def _parse_args_str(self, args_str: str) -> Tuple[Dict[str, Any], Optional[str]]:
        # 原实现只 strip，不检查空值
        return {"file_path": args_str.strip()}, None

    def execute(self, context: Optional[ToolContext] = None, *, file_path: str, **_: Any) -> str:
        path = Path(file_path).expanduser().resolve()
        if not path.exists():
            return f"文件不存在: {path}"

        try:
            from core.analyze.analyzer import DataAnalyzer

            az = DataAnalyzer()
            result = az.analyze(path)
            return (
                f"文件: {result.file_name}\n"
                f"规模: {result.rows} 行 × {result.cols} 列\n"
                f"字段: {', '.join(result.columns[:8])}\n"
                f"数值列描述: {list(result.describe.keys())}\n"
                f"缺失值: {sum(1 for v in result.missing.values() if v > 0)} 列有缺失\n"
                f"\nAI 洞察：\n{result.insights}"
            )
        except Exception as e:
            return f"分析失败: {e}"

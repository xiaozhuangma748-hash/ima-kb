"""存储层：SQLite 元数据 + 原文件存储。

表结构：
- documents: 文档元信息（一个文件一条）
- chunks: 文档分块（一个文档多条）
- tags: 标签（P3 阶段扩展用）

提供 Storage 类统一管理。

性能优化：
- SQLite WAL 模式，支持并发读写
- 线程局部连接复用，避免频繁开关
"""
from __future__ import annotations

import hashlib
import json
import shutil
import sqlite3
import threading
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional

from config import settings
from .ingestion.parser import ParsedDocument
from .ingestion.chunker import Chunk
from .search.bm25 import BM25Index, SearchResult


# ============================================================
# 数据模型
# ============================================================

@dataclass
class DocumentRecord:
    """文档记录（对应 documents 表一行）。"""
    id: str                        # SHA256(文件路径+内容)
    title: str
    file_name: str
    file_path: str                 # 原始路径
    file_type: str                 # 扩展名
    file_size: int
    content_hash: str              # 内容 SHA256，用于去重
    language: str = "unknown"
    meta: Dict[str, str] = field(default_factory=dict)
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    chunk_count: int = 0
    total_tokens: int = 0
    tags: List[str] = field(default_factory=list)  # 主题标签（LLM 生成）


@dataclass
class ChunkRecord:
    """分块记录（对应 chunks 表一行）。"""
    id: str                        # f"{doc_id}_{chunk_index}"
    doc_id: str
    index: int
    content: str
    token_count: int
    start_char: int
    end_char: int


# ============================================================
# Storage 主类
# ============================================================

class Storage:
    """本地存储管理：SQLite + 文件。"""

    def __init__(self, storage_path: Optional[Path] = None) -> None:
        self.storage_path = storage_path or settings.storage_path
        self.uploads_dir = self.storage_path / "uploads"
        self.db_path = self.storage_path / "metadata.db"
        self.bm25 = BM25Index()
        # 可选的向量索引引用（由外部通过 attach_vector_index 注入）
        # 注入后 save_document / delete_document 会自动同步向量索引
        self._vector_index = None
        # 线程局部连接，避免频繁开关
        self._tls = threading.local()
        self._init_schema()
        self._sync_bm25_from_db()

    def attach_vector_index(self, vector_index) -> None:
        """注入向量索引实例，使后续 save/delete 自动同步向量索引。

        Args:
            vector_index: VectorIndex 实例（或任何实现了 add_chunks_batch/delete_document 的对象）
        """
        self._vector_index = vector_index

    def detach_vector_index(self) -> None:
        """解除向量索引绑定。"""
        self._vector_index = None

    # ---- 初始化 ----

    def _init_schema(self) -> None:
        """创建目录和数据库表。"""
        self.storage_path.mkdir(parents=True, exist_ok=True)
        self.uploads_dir.mkdir(parents=True, exist_ok=True)
        with self._conn() as conn:
            # 启用 WAL 模式，支持并发读写
            conn.execute("PRAGMA journal_mode=WAL")
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS documents (
                    id            TEXT PRIMARY KEY,
                    title         TEXT NOT NULL,
                    file_name     TEXT NOT NULL,
                    file_path     TEXT NOT NULL,
                    file_type     TEXT NOT NULL,
                    file_size     INTEGER NOT NULL,
                    content_hash  TEXT NOT NULL,
                    language      TEXT DEFAULT 'unknown',
                    meta          TEXT DEFAULT '{}',
                    created_at    TEXT NOT NULL,
                    chunk_count   INTEGER DEFAULT 0,
                    total_tokens  INTEGER DEFAULT 0,
                    tags          TEXT DEFAULT '[]'
                );
                CREATE INDEX IF NOT EXISTS idx_documents_hash ON documents(content_hash);

                CREATE TABLE IF NOT EXISTS chunks (
                    id            TEXT PRIMARY KEY,
                    doc_id        TEXT NOT NULL,
                    index_in_doc  INTEGER NOT NULL,
                    content       TEXT NOT NULL,
                    token_count   INTEGER DEFAULT 0,
                    start_char    INTEGER DEFAULT 0,
                    end_char      INTEGER DEFAULT 0,
                    created_at    TEXT NOT NULL,
                    FOREIGN KEY (doc_id) REFERENCES documents(id) ON DELETE CASCADE
                );
                CREATE INDEX IF NOT EXISTS idx_chunks_doc ON chunks(doc_id);
                """
            )
            # 迁移：给已存在的 documents 表加 tags 列（SQLite 用 PRAGMA 检测列是否存在）
            cols = conn.execute("PRAGMA table_info(documents)").fetchall()
            col_names = {c["name"] for c in cols}
            if "tags" not in col_names:
                conn.execute("ALTER TABLE documents ADD COLUMN tags TEXT DEFAULT '[]'")

    @contextmanager
    def _conn(self) -> Iterator[sqlite3.Connection]:
        """获取数据库连接（线程局部复用，WAL 模式）。

        连接复用策略：每个线程首次调用时创建连接并缓存到 thread local，
        后续调用直接复用，避免频繁 connect/close 的开销。
        """
        conn = getattr(self._tls, "conn", None)
        if conn is None:
            conn = sqlite3.connect(self.db_path, check_same_thread=False)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA foreign_keys = ON")
            self._tls.conn = conn
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise

    # ---- 写入 ----

    def save_document(
        self,
        parsed: ParsedDocument,
        chunks: List[Chunk],
        copy_file: bool = True,
        tags: Optional[List[str]] = None,
    ) -> DocumentRecord:
        """保存一份文档（含分块）到存储。

        Args:
            parsed: 解析后的文档
            chunks: 分块列表
            copy_file: 是否把原文件复制到 uploads 目录
            tags: 主题标签列表（可选，由 tagger 生成）

        Returns:
            DocumentRecord
        """
        # 1. 计算文档 ID 和内容 hash
        content_bytes = parsed.text.encode("utf-8")
        content_hash = hashlib.sha256(content_bytes).hexdigest()
        doc_id = content_hash[:32]  # 用内容 hash 前 32 位作为 ID

        # 2. 检查是否已存在（去重）
        existing = self.get_document(doc_id)
        if existing is not None:
            return existing

        # 3. 复制原文件到 uploads（按 doc_id 子目录组织）
        saved_path: Optional[Path] = None
        if copy_file and parsed.file_path.exists():
            target_dir = self.uploads_dir / doc_id[:2]  # 二级目录避免单目录文件过多
            target_dir.mkdir(parents=True, exist_ok=True)
            saved_path = target_dir / parsed.file_path.name
            if not saved_path.exists():
                shutil.copy2(parsed.file_path, saved_path)

        file_size = parsed.file_path.stat().st_size if parsed.file_path.exists() else 0

        # 4. 写入数据库
        record = DocumentRecord(
            id=doc_id,
            title=parsed.title,
            file_name=parsed.file_path.name,
            file_path=str(parsed.file_path),
            file_type=parsed.file_type,
            file_size=file_size,
            content_hash=content_hash,
            language=parsed.language,
            meta={**parsed.meta, "saved_path": str(saved_path) if saved_path else ""},
            chunk_count=len(chunks),
            total_tokens=sum(c.token_count for c in chunks),
            tags=tags or [],
        )

        now = datetime.now().isoformat()
        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO documents
                    (id, title, file_name, file_path, file_type, file_size,
                     content_hash, language, meta, created_at, chunk_count, total_tokens, tags)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.id, record.title, record.file_name, record.file_path,
                    record.file_type, record.file_size, record.content_hash,
                    record.language, json.dumps(record.meta, ensure_ascii=False),
                    record.created_at, record.chunk_count, record.total_tokens,
                    json.dumps(record.tags, ensure_ascii=False),
                ),
            )
            # 批量插入 chunks
            conn.executemany(
                """
                INSERT INTO chunks
                    (id, doc_id, index_in_doc, content, token_count, start_char, end_char, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        f"{doc_id}_{c.index}", doc_id, c.index, c.content,
                        c.token_count, c.start_char, c.end_char, now,
                    )
                    for c in chunks
                ],
            )

        # 5. 同步到 BM25 索引并持久化
        for c in chunks:
            self.bm25.add(chunk_id=f"{doc_id}_{c.index}", doc_id=doc_id, content=c.content)
        self.bm25.save()

        # 6. 同步到向量索引（如果已注入）
        if self._vector_index is not None:
            try:
                vector_chunks = [
                    {"chunk_id": f"{doc_id}_{c.index}", "doc_id": doc_id, "content": c.content}
                    for c in chunks
                ]
                self._vector_index.add_chunks_batch(vector_chunks)
            except Exception as e:
                # 向量索引同步失败不应阻塞入库（BM25 仍可用）
                import logging
                logging.getLogger(__name__).warning(f"向量索引同步失败: {e}")

        return record

    # ---- 查询 ----

    def get_document(self, doc_id: str) -> Optional[DocumentRecord]:
        """按 ID 查文档。"""
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM documents WHERE id = ?", (doc_id,)
            ).fetchone()
        return self._row_to_doc(row) if row else None

    def list_documents(self, limit: int = 100, offset: int = 0) -> List[DocumentRecord]:
        """列出文档（按时间倒序）。"""
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM documents ORDER BY created_at DESC LIMIT ? OFFSET ?",
                (limit, offset),
            ).fetchall()
        return [self._row_to_doc(r) for r in rows]

    def get_chunks(self, doc_id: str) -> List[ChunkRecord]:
        """获取某文档的所有分块。"""
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM chunks WHERE doc_id = ? ORDER BY index_in_doc",
                (doc_id,),
            ).fetchall()
        return [
            ChunkRecord(
                id=r["id"],
                doc_id=r["doc_id"],
                index=r["index_in_doc"],
                content=r["content"],
                token_count=r["token_count"],
                start_char=r["start_char"],
                end_char=r["end_char"],
            )
            for r in rows
        ]

    def get_documents_batch(self, doc_ids: List[str]) -> Dict[str, DocumentRecord]:
        """批量查询多个文档的元数据（避免 N+1 查询）。

        Args:
            doc_ids: 文档 ID 列表

        Returns:
            {doc_id: DocumentRecord} 字典
        """
        if not doc_ids:
            return {}
        with self._conn() as conn:
            placeholders = ",".join("?" * len(doc_ids))
            rows = conn.execute(
                f"SELECT * FROM documents WHERE id IN ({placeholders})",
                doc_ids,
            ).fetchall()
        return {r["id"]: self._row_to_doc(r) for r in rows}

    def get_first_chunk(self, doc_id: str) -> Optional[ChunkRecord]:
        """获取文档的第一个分块（用于搜索结果回填摘要）。"""
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM chunks WHERE doc_id = ? ORDER BY index_in_doc LIMIT 1",
                (doc_id,),
            ).fetchone()
        if row is None:
            return None
        return ChunkRecord(
            id=row["id"],
            doc_id=row["doc_id"],
            index=row["index_in_doc"],
            content=row["content"],
            token_count=row["token_count"],
            start_char=row["start_char"],
            end_char=row["end_char"],
        )

    def search_chunks(self, keyword: str, limit: int = 20) -> List[ChunkRecord]:
        """关键词搜索分块（LIKE 模糊匹配，P2 会换成向量检索）。"""
        with self._conn() as conn:
            rows = conn.execute(
                """
                SELECT c.* FROM chunks c
                JOIN documents d ON c.doc_id = d.id
                WHERE c.content LIKE ?
                ORDER BY d.created_at DESC
                LIMIT ?
                """,
                (f"%{keyword}%", limit),
            ).fetchall()
        return [
            ChunkRecord(
                id=r["id"],
                doc_id=r["doc_id"],
                index=r["index_in_doc"],
                content=r["content"],
                token_count=r["token_count"],
                start_char=r["start_char"],
                end_char=r["end_char"],
            )
            for r in rows
        ]

    # ---- 统计 ----

    def stats(self) -> Dict[str, Any]:
        """知识库统计信息。"""
        with self._conn() as conn:
            doc_count = conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0]
            chunk_count = conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
            total_tokens = conn.execute(
                "SELECT COALESCE(SUM(total_tokens), 0) FROM documents"
            ).fetchone()[0]
            total_size = conn.execute(
                "SELECT COALESCE(SUM(file_size), 0) FROM documents"
            ).fetchone()[0]
            # 按类型分布
            type_rows = conn.execute(
                """
                SELECT file_type, COUNT(*) as cnt
                FROM documents GROUP BY file_type ORDER BY cnt DESC
                """
            ).fetchall()
        return {
            "documents": doc_count,
            "chunks": chunk_count,
            "total_tokens": total_tokens,
            "total_size_mb": round(total_size / 1024 / 1024, 2),
            "by_type": {r["file_type"]: r["cnt"] for r in type_rows},
        }

    # ---- 删除 ----

    def delete_document(self, doc_id: str) -> bool:
        """删除文档（含分块、原文件副本、BM25 索引、向量索引）。"""
        doc = self.get_document(doc_id)
        if doc is None:
            return False
        # 删除原文件副本目录
        saved_path_str = doc.meta.get("saved_path", "")
        if saved_path_str:
            saved_path = Path(saved_path_str)
            if saved_path.exists():
                saved_path.unlink(missing_ok=True)
        # 删除 BM25 索引中该文档所有 chunk
        chunks = self.get_chunks(doc_id)
        for c in chunks:
            self.bm25.remove(c.id)
        self.bm25.save()
        # 删除向量索引中该文档所有向量（如果已注入）
        if self._vector_index is not None:
            try:
                self._vector_index.delete_document(doc_id)
            except Exception as e:
                import logging
                logging.getLogger(__name__).warning(f"向量索引删除失败 {doc_id}: {e}")
        # 删除数据库记录
        with self._conn() as conn:
            conn.execute("DELETE FROM chunks WHERE doc_id = ?", (doc_id,))
            conn.execute("DELETE FROM documents WHERE id = ?", (doc_id,))
        return True

    # ---- BM25 检索 ----

    def bm25_search(self, query: str, top_k: int = 10) -> List[SearchResult]:
        """BM25 语义检索：返回带内容的搜索结果。

        Args:
            query: 查询文本
            top_k: 返回前 K 条

        Returns:
            SearchResult 列表（content 和 doc_title 已填充）
        """
        results = self.bm25.search(query, top_k=top_k)
        if not results:
            return []

        # 批量查询 chunk 内容和文档标题
        chunk_ids = [r.chunk_id for r in results]
        doc_ids = list({r.doc_id for r in results})

        with self._conn() as conn:
            # 查 chunk 内容
            placeholders = ",".join("?" * len(chunk_ids))
            rows = conn.execute(
                f"SELECT id, content FROM chunks WHERE id IN ({placeholders})",
                chunk_ids,
            ).fetchall()
            chunk_content = {r["id"]: r["content"] for r in rows}

            # 查文档标题
            placeholders = ",".join("?" * len(doc_ids))
            rows = conn.execute(
                f"SELECT id, title FROM documents WHERE id IN ({placeholders})",
                doc_ids,
            ).fetchall()
            doc_title = {r["id"]: r["title"] for r in rows}

        # 填充内容，过滤掉查不到内容的过期条目
        filled = []
        for r in results:
            content = chunk_content.get(r.chunk_id, "")
            if not content:
                # BM25 索引中的过期条目，chunk_id 已不在数据库中
                continue
            r.content = content
            r.doc_title = doc_title.get(r.doc_id, "")
            filled.append(r)
        return filled

    # ---- 索引维护 ----

    def rebuild_bm25_index(self) -> int:
        """从数据库重建 BM25 索引（修复/迁移用）。

        Returns:
            重建的 chunk 数量
        """
        self.bm25.clear()
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT id, doc_id, content FROM chunks"
            ).fetchall()
        for r in rows:
            self.bm25.add(chunk_id=r["id"], doc_id=r["doc_id"], content=r["content"])
        self.bm25.save()
        return len(rows)

    def rebuild_vector_index(self, vector_index) -> int:
        """从数据库全量重建向量索引。

        Args:
            vector_index: VectorIndex 实例（必须已初始化）

        Returns:
            重建的 chunk 数量（-1 表示向量索引不可用）
        """
        if not vector_index.is_available():
            return -1
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT id, doc_id, content FROM chunks ORDER BY doc_id, index_in_doc"
            ).fetchall()
        chunks = [
            {"chunk_id": r["id"], "doc_id": r["doc_id"], "content": r["content"]}
            for r in rows
        ]
        vector_index.build_index(chunks)
        return len(chunks)

    def _sync_bm25_from_db(self) -> None:
        """启动时同步 BM25 索引。

        策略：
        - 索引数量匹配 → 直接用
        - 数量不匹配 → 增量修复：删除过期 ID + 补充缺失 ID
        - pickle 里的 ID 全部过期 → 全量重建
        """
        import logging
        logger = logging.getLogger(__name__)

        with self._conn() as conn:
            db_chunk_count = conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
        if db_chunk_count == 0:
            return
        # 数量匹配，直接用
        if len(self.bm25) == db_chunk_count:
            return

        if len(self.bm25) == 0:
            # 索引为空，全量重建
            logger.info(f"BM25 索引为空，全量重建中...")
            self.rebuild_bm25_index()
            logger.info(f"BM25 索引重建完成：{len(self.bm25)} 条")
            return

        # 数量不匹配，增量修复
        bm25_ids = set(self.bm25._docs.keys())
        with self._conn() as conn:
            db_ids = set(row[0] for row in conn.execute("SELECT id FROM chunks").fetchall())

        expired_ids = bm25_ids - db_ids
        missing_ids = db_ids - bm25_ids

        if not expired_ids and not missing_ids:
            return  # 理论上不会到这里，但安全起见

        if not expired_ids:
            # 只有缺失 ID，补充即可
            logger.info(f"BM25 索引缺少 {len(missing_ids)} 条，增量补充中...")
            self._add_missing_bm25_chunks(missing_ids)
            logger.info(f"BM25 索引同步完成：{len(self.bm25)} 条")
            return

        # 有过期 ID
        if len(expired_ids) == len(bm25_ids):
            # 全部过期 → 清空 + 从数据库全部补入
            logger.info(
                f"BM25 索引清理 {len(self.bm25)} 条过期 ID，从数据库重建中..."
            )
            self.bm25.clear()
            self._add_missing_bm25_chunks(db_ids)
            self.bm25.save()
            logger.info(f"BM25 索引同步完成：{len(self.bm25)} 条")
            return

        # 部分过期，增量修复
        logger.info(
            f"BM25 索引不同步：{len(expired_ids)} 条过期，{len(missing_ids)} 条缺失，增量修复中..."
        )
        for eid in expired_ids:
            self.bm25.remove(eid)
        self._add_missing_bm25_chunks(missing_ids)
        self.bm25.save()
        logger.info(f"BM25 索引同步完成：{len(self.bm25)} 条")

    def _add_missing_bm25_chunks(self, missing_ids: set) -> None:
        """补充缺失的 chunk 到 BM25 索引。"""
        with self._conn() as conn:
            placeholders = ",".join("?" * len(missing_ids))
            rows = conn.execute(
                f"SELECT id, doc_id, content FROM chunks WHERE id IN ({placeholders})",
                list(missing_ids),
            ).fetchall()
        for row in rows:
            self.bm25.add(chunk_id=row["id"], doc_id=row["doc_id"], content=row["content"])

    # ---- 私有辅助 ----

    @staticmethod
    def _row_to_doc(row: sqlite3.Row) -> DocumentRecord:
        return DocumentRecord(
            id=row["id"],
            title=row["title"],
            file_name=row["file_name"],
            file_path=row["file_path"],
            file_type=row["file_type"],
            file_size=row["file_size"],
            content_hash=row["content_hash"],
            language=row["language"],
            meta=json.loads(row["meta"] or "{}"),
            created_at=row["created_at"],
            chunk_count=row["chunk_count"],
            total_tokens=row["total_tokens"],
            tags=json.loads(row["tags"] or "[]") if "tags" in row.keys() else [],
        )

    # ---- 标签管理 ----

    def update_document_tags(self, doc_id: str, tags: List[str]) -> bool:
        """更新文档的标签。

        Args:
            doc_id: 文档 ID
            tags: 标签列表

        Returns:
            True 成功 / False 文档不存在
        """
        with self._conn() as conn:
            cur = conn.execute(
                "UPDATE documents SET tags = ? WHERE id = ?",
                (json.dumps(tags, ensure_ascii=False), doc_id),
            )
            return cur.rowcount > 0

    def update_document_title(self, doc_id: str, title: str) -> bool:
        """更新文档标题。

        Args:
            doc_id: 文档 ID
            title: 新标题（非空）

        Returns:
            True 成功 / False 文档不存在
        """
        title = title.strip()
        if not title:
            return False
        with self._conn() as conn:
            cur = conn.execute(
                "UPDATE documents SET title = ? WHERE id = ?",
                (title, doc_id),
            )
            return cur.rowcount > 0

    def list_all_tags(self) -> Dict[str, int]:
        """统计所有标签及其文档数。

        Returns:
            {tag_name: doc_count} 按出现次数倒序
        """
        with self._conn() as conn:
            rows = conn.execute("SELECT tags FROM documents").fetchall()
        counter: Dict[str, int] = {}
        for r in rows:
            try:
                tags = json.loads(r["tags"] or "[]")
            except json.JSONDecodeError:
                tags = []
            for t in tags:
                t = t.strip()
                if t:
                    counter[t] = counter.get(t, 0) + 1
        # 按次数倒序
        return dict(sorted(counter.items(), key=lambda x: -x[1]))

    def list_documents_by_tag(self, tag: str) -> List[DocumentRecord]:
        """按标签筛选文档。

        Args:
            tag: 标签名（精确匹配，大小写敏感）

        Returns:
            DocumentRecord 列表
        """
        # JSON 数组的 LIKE 匹配不够精确，这里在 Python 层过滤
        with self._conn() as conn:
            rows = conn.execute(
                """
                SELECT * FROM documents
                WHERE tags LIKE ?
                ORDER BY created_at DESC
                """,
                (f'%"{tag}"%',),
            ).fetchall()
        docs = [self._row_to_doc(r) for r in rows]
        # Python 层精确过滤（避免子串误伤）
        return [d for d in docs if tag in d.tags]

    def rename_tag(self, old_tag: str, new_tag: str) -> int:
        """重命名标签（影响所有包含该标签的文档）。

        Args:
            old_tag: 原标签名
            new_tag: 新标签名

        Returns:
            受影响的文档数
        """
        old_tag = old_tag.strip()
        new_tag = new_tag.strip()
        if not old_tag or not new_tag:
            return 0
        affected = 0
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT id, tags FROM documents WHERE tags LIKE ?",
                (f'%"{old_tag}"%',),
            ).fetchall()
            for r in rows:
                try:
                    tags = json.loads(r["tags"] or "[]")
                except json.JSONDecodeError:
                    tags = []
                if old_tag in tags:
                    # 替换（如果新标签已存在则不重复添加）
                    if new_tag in tags:
                        tags = [t for t in tags if t != old_tag]
                    else:
                        tags = [new_tag if t == old_tag else t for t in tags]
                    conn.execute(
                        "UPDATE documents SET tags = ? WHERE id = ?",
                        (json.dumps(tags, ensure_ascii=False), r["id"]),
                    )
                    affected += 1
        return affected

    def merge_tag(self, source_tag: str, target_tag: str) -> int:
        """合并标签：把 source_tag 合并到 target_tag。

        Args:
            source_tag: 被合并的标签（合并后删除）
            target_tag: 目标标签（合并后保留）

        Returns:
            受影响的文档数
        """
        source_tag = source_tag.strip()
        target_tag = target_tag.strip()
        if not source_tag or not target_tag or source_tag == target_tag:
            return 0
        affected = 0
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT id, tags FROM documents WHERE tags LIKE ?",
                (f'%"{source_tag}"%',),
            ).fetchall()
            for r in rows:
                try:
                    tags = json.loads(r["tags"] or "[]")
                except json.JSONDecodeError:
                    tags = []
                if source_tag in tags:
                    # 移除 source，添加 target（如不存在）
                    tags = [t for t in tags if t != source_tag]
                    if target_tag not in tags:
                        tags.append(target_tag)
                    conn.execute(
                        "UPDATE documents SET tags = ? WHERE id = ?",
                        (json.dumps(tags, ensure_ascii=False), r["id"]),
                    )
                    affected += 1
        return affected

    def delete_chunk(self, chunk_id: str) -> bool:
        """删除单个 chunk。

        Args:
            chunk_id: chunk 的 ID

        Returns:
            True 表示删除成功
        """
        with self._conn() as conn:
            cur = conn.execute("DELETE FROM chunks WHERE id = ?", (chunk_id,))
            return cur.rowcount > 0

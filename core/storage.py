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
    parent_content: str = ""       # small-to-big 检索用的父级内容
    page_num: int = 0              # PDF 页码（1-based，0 表示非 PDF 或未标记）
    heading: str = ""              # 所属章节标题


@dataclass
class KeyFactRecord:
    """跨会话关键事实记录（对应 key_facts 表一行）。"""
    id: str                        # UUID
    session: str                   # 所属会话名（空字符串表示全局）
    fact: str                      # 关键事实文本
    created_at: str
    updated_at: str
    source: str                    # 来源轮次简要说明


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

    @property
    def vector(self):
        """公开访问器：返回已注入的向量索引（未注入时为 None）。

        RAGChain / HybridRetriever 等上层组件通过 `storage.vector` 访问，
        与 `attach_vector_index` 注入的 `_vector_index` 保持连通。
        """
        return self._vector_index

    def attach_vector_index(self, vector_index) -> None:
        """注入向量索引实例，使后续 save/delete 自动同步向量索引。

        注入后会自动检查向量索引与数据库的一致性：
        - 过期 chunk（在向量索引但不在数据库）→ 自动删除
        - 缺失 chunk（在数据库但不在向量索引）→ 自动补充嵌入

        这解决了重新入库时向量索引未清理导致的检索结果过期问题。

        Args:
            vector_index: VectorIndex 实例（或任何实现了 add_chunks_batch/delete_document 的对象）
        """
        self._vector_index = vector_index
        # 注入后立即同步，确保向量索引与数据库一致
        try:
            self._sync_vector_from_db()
        except Exception as e:
            import logging
            logging.getLogger(__name__).warning(f"向量索引同步失败（非致命）: {e}")

    def detach_vector_index(self) -> None:
        """解除向量索引绑定。"""
        self._vector_index = None

    def _sync_vector_from_db(self) -> None:
        """同步向量索引与数据库 chunks 表。

        策略（类似 _sync_bm25_from_db）：
        - 数量匹配且 ID 集合一致 → 直接用
        - 有过期 chunk（在向量索引但不在数据库）→ 删除
        - 有缺失 chunk（在数据库但不在向量索引）→ 补充嵌入
        - 向量索引为空 → 全量重建

        本方法在 attach_vector_index 时自动调用，也可手动调用修复。
        """
        import logging
        logger = logging.getLogger(__name__)

        if self._vector_index is None or not self._vector_index.is_available():
            return

        with self._conn() as conn:
            db_chunk_count = conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]

        if db_chunk_count == 0:
            return

        # 获取向量索引中所有 chunk_id
        try:
            all_vec = self._vector_index._collection.get(include=["metadatas"])
            vec_chunk_ids = set(all_vec["ids"])
        except Exception as e:
            logger.warning(f"读取向量索引失败，跳过同步: {e}")
            return

        # 向量索引为空，全量重建
        if not vec_chunk_ids:
            logger.info(f"向量索引为空，全量重建中...")
            count = self.rebuild_vector_index(self._vector_index)
            logger.info(f"向量索引重建完成：{count} 条")
            return

        # 数量匹配，可能一致
        if len(vec_chunk_ids) == db_chunk_count:
            # 进一步检查 ID 集合
            with self._conn() as conn:
                db_ids = set(row[0] for row in conn.execute("SELECT id FROM chunks").fetchall())
            if vec_chunk_ids == db_ids:
                return  # 完全一致
            # ID 不一致但数量相同，按增量修复
            logger.info("向量索引数量匹配但 ID 不一致，增量修复中...")

        # 获取数据库 ID 集合
        with self._conn() as conn:
            db_ids = set(row[0] for row in conn.execute("SELECT id FROM chunks").fetchall())

        expired_ids = vec_chunk_ids - db_ids
        missing_ids = db_ids - vec_chunk_ids

        if not expired_ids and not missing_ids:
            return  # 一致

        # 全部过期 → 全量重建（避免逐个删除慢）
        if len(expired_ids) == len(vec_chunk_ids):
            logger.info(
                f"向量索引清理 {len(vec_chunk_ids)} 条过期 chunk，从数据库全量重建中..."
            )
            count = self.rebuild_vector_index(self._vector_index)
            logger.info(f"向量索引重建完成：{count} 条")
            return

        # 增量修复：先删除过期，再补充缺失
        if expired_ids:
            logger.info(f"向量索引删除 {len(expired_ids)} 条过期 chunk...")
            # chromadb delete 支持批量
            expired_list = list(expired_ids)
            batch_size = 500
            for i in range(0, len(expired_list), batch_size):
                batch = expired_list[i:i + batch_size]
                try:
                    self._vector_index._collection.delete(ids=batch)
                except Exception as e:
                    logger.warning(f"批量删除向量失败（{len(batch)} 条）: {e}")

        if missing_ids:
            logger.info(f"向量索引补充 {len(missing_ids)} 条缺失 chunk...")
            with self._conn() as conn:
                placeholders = ",".join("?" * len(missing_ids))
                rows = conn.execute(
                    f"SELECT id, doc_id, content FROM chunks WHERE id IN ({placeholders})",
                    list(missing_ids),
                ).fetchall()
            chunks_to_add = [
                {"chunk_id": r["id"], "doc_id": r["doc_id"], "content": r["content"]}
                for r in rows
            ]
            try:
                self._vector_index.add_chunks_batch(chunks_to_add)
            except Exception as e:
                logger.warning(f"补充向量失败（{len(chunks_to_add)} 条）: {e}")

        logger.info(
            f"向量索引同步完成：删除 {len(expired_ids)} 过期，补充 {len(missing_ids)} 缺失"
        )

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
                    parent_content TEXT DEFAULT '',
                    page_num      INTEGER DEFAULT 0,
                    heading       TEXT DEFAULT '',
                    created_at    TEXT NOT NULL,
                    FOREIGN KEY (doc_id) REFERENCES documents(id) ON DELETE CASCADE
                );
                CREATE INDEX IF NOT EXISTS idx_chunks_doc ON chunks(doc_id);

                CREATE TABLE IF NOT EXISTS key_facts (
                    id          TEXT PRIMARY KEY,
                    session     TEXT NOT NULL DEFAULT '',
                    fact        TEXT NOT NULL,
                    created_at  TEXT NOT NULL,
                    updated_at  TEXT NOT NULL,
                    source      TEXT DEFAULT ''
                );
                CREATE INDEX IF NOT EXISTS idx_key_facts_session ON key_facts(session);
                CREATE INDEX IF NOT EXISTS idx_key_facts_fact ON key_facts(fact);
                """
            )
            # 迁移：给已存在的 documents 表加 tags 列（SQLite 用 PRAGMA 检测列是否存在）
            cols = conn.execute("PRAGMA table_info(documents)").fetchall()
            col_names = {c["name"] for c in cols}
            if "tags" not in col_names:
                conn.execute("ALTER TABLE documents ADD COLUMN tags TEXT DEFAULT '[]'")

            # 迁移：给 chunks 表加 parent_content 列（small-to-big 检索用）
            chunk_cols = conn.execute("PRAGMA table_info(chunks)").fetchall()
            chunk_col_names = {c["name"] for c in chunk_cols}
            if "parent_content" not in chunk_col_names:
                conn.execute("ALTER TABLE chunks ADD COLUMN parent_content TEXT DEFAULT ''")
            # 迁移：给 chunks 表加 page_num / heading 列（PDF 结构感知分块用）
            if "page_num" not in chunk_col_names:
                conn.execute("ALTER TABLE chunks ADD COLUMN page_num INTEGER DEFAULT 0")
            if "heading" not in chunk_col_names:
                conn.execute("ALTER TABLE chunks ADD COLUMN heading TEXT DEFAULT ''")

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
                    (id, doc_id, index_in_doc, content, token_count, start_char, end_char, parent_content, page_num, heading, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        f"{doc_id}_{c.index}", doc_id, c.index, c.content,
                        c.token_count, c.start_char, c.end_char,
                        getattr(c, "parent_content", ""),
                        getattr(c, "page_num", 0),
                        getattr(c, "heading", ""),
                        now,
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
        """按 ID 查文档（支持前缀匹配）。"""
        with self._conn() as conn:
            # 如果输入长度小于 32 位，使用前缀匹配
            if len(doc_id) < 32:
                row = conn.execute(
                    "SELECT * FROM documents WHERE id LIKE ?", (doc_id + "%",)
                ).fetchone()
            else:
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
        result: list[ChunkRecord] = []
        for r in rows:
            keys = r.keys()
            result.append(ChunkRecord(
                id=r["id"],
                doc_id=r["doc_id"],
                index=r["index_in_doc"],
                content=r["content"],
                token_count=r["token_count"],
                start_char=r["start_char"],
                end_char=r["end_char"],
                parent_content=r["parent_content"] if "parent_content" in keys else "",
                page_num=r["page_num"] if "page_num" in keys else 0,
                heading=r["heading"] if "heading" in keys else "",
            ))
        return result

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
            parent_content=row["parent_content"] if "parent_content" in row.keys() else "",
        )

    def get_first_chunks_batch(self, doc_ids: List[str]) -> Dict[str, ChunkRecord]:
        """批量获取多个文档的第一个分块(避免 N+1 查询)。

        Args:
            doc_ids: 文档 ID 列表

        Returns:
            {doc_id: ChunkRecord} 字典(无分块的文档不出现在结果中)
        """
        if not doc_ids:
            return {}
        # 用 GROUP BY/MIN 取每个 doc_id 的最小 index_in_doc 行
        # SQLite 支持 MIN() 选项 + 子查询取完整行
        with self._conn() as conn:
            placeholders = ",".join("?" * len(doc_ids))
            rows = conn.execute(
                f"""SELECT c.* FROM chunks c
                    INNER JOIN (
                        SELECT doc_id, MIN(index_in_doc) AS min_idx
                        FROM chunks
                        WHERE doc_id IN ({placeholders})
                        GROUP BY doc_id
                    ) m ON c.doc_id = m.doc_id AND c.index_in_doc = m.min_idx
                """,
                doc_ids,
            ).fetchall()
        return {
            r["doc_id"]: ChunkRecord(
                id=r["id"],
                doc_id=r["doc_id"],
                index=r["index_in_doc"],
                content=r["content"],
                token_count=r["token_count"],
                start_char=r["start_char"],
                end_char=r["end_char"],
                parent_content=r["parent_content"] if "parent_content" in r.keys() else "",
            )
            for r in rows
        }

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
                parent_content=r["parent_content"] if "parent_content" in r.keys() else "",
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
            # 查 chunk 内容和章节标题
            placeholders = ",".join("?" * len(chunk_ids))
            rows = conn.execute(
                f"SELECT id, content, heading FROM chunks WHERE id IN ({placeholders})",
                chunk_ids,
            ).fetchall()
            chunk_content = {r["id"]: r["content"] for r in rows}
            chunk_heading = {r["id"]: (r["heading"] or "") for r in rows}

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
            r.heading = chunk_heading.get(r.chunk_id, "")
            filled.append(r)

        # 精确匹配重排序：对包含查询区分性词的结果加分
        filled = self._rerank_by_exact_match(query, filled)
        return filled

    def _rerank_by_exact_match(
        self,
        query: str,
        results: List,
        score_attr: str = "score",
        content_attr: str = "content",
    ) -> List:
        """精确匹配重排序：对包含查询区分性词的结果加分，不包含的降分。

        解决 BM25/向量检索无法区分同名实体的问题：
        - 查询"白杨街道晨光社区居家养老服务照料中心"
        - BM25 返回多个"白杨街道XX社区"（词频相似）
        - 但只有"晨光社区"包含区分性词"晨光"
        - 重排序后"晨光社区"分数翻倍，其他社区降半，排名更准确

        算法：
        1. 对查询分词，统计每个 token 在结果集中的出现频率
        2. 识别区分性词（出现率 < 70% 的词，即不是所有结果都包含的词）
        3. 对每个结果计算区分性词匹配率 (0.0 ~ 1.0)
        4. 调整 score: new = old * (0.5 + match_ratio)
           - match_ratio=1.0 (全命中) → score × 1.5
           - match_ratio=0.5 (半命中) → score × 1.0 (不变)
           - match_ratio=0.0 (全 miss) → score × 0.5 (降半)
        5. 按新 score 重新排序

        Args:
            query: 查询文本
            results: 结果列表（需已有 content）
            score_attr: score 属性名
            content_attr: content 属性名

        Returns:
            重排序后的结果列表（原地修改 score，重新排序）
        """
        if not results or len(results) == 1:
            return results

        from .search.bm25 import tokenize

        query_tokens = tokenize(query)
        if len(query_tokens) < 2:
            return results  # 查询太短，无法识别区分性词

        # 对每个结果的 content 做分词，生成 token 集合（避免子串误匹配）
        # 原来用 `tok in content` 子串匹配会跨词边界误命中：
        #   "养老" in "养老保险基金" → True（语义无关）
        # 改为 token 集合包含判断，更精确
        #
        # PDF rerank 增强：注入 doc_title + heading 前缀
        # PDF chunk content 可能不含文档标题/章节标题词，导致 reranker 无法匹配
        # 查询中的标题词。注入后 token 集合扩展，让 reranker 能识别"查询词出现在
        # 文档标题/章节标题"的情况。对 xlsx 等已有 doc_title 在 content 中的格式，
        # 集合去重使其成为 no-op（安全无副作用）。
        result_token_sets: list[set[str]] = []
        for r in results:
            content = getattr(r, content_attr, "") or ""
            doc_title = getattr(r, "doc_title", "") or ""
            heading = getattr(r, "heading", "") or ""
            if doc_title or heading:
                expanded = f"{doc_title} {heading} {content}".strip()
                result_token_sets.append(set(tokenize(expanded)))
            else:
                result_token_sets.append(set(tokenize(content)))

        # 统计每个 query token 在结果中出现的频率
        total = len(results)
        token_doc_count: Dict[str, int] = {tok: 0 for tok in query_tokens}
        for tok_set in result_token_sets:
            for tok in query_tokens:
                if tok in tok_set:
                    token_doc_count[tok] += 1

        # 识别区分性词：至少出现1次，但出现率 < 70%
        # （出现率 100% 的词是通用词，如"社区""服务"，无区分价值）
        # 过滤单字 token：单字（如"中""心"）语义模糊，不作为区分性词
        distinctive_tokens = [
            tok for tok, cnt in token_doc_count.items()
            if 0 < cnt < total * 0.7 and len(tok) > 1
        ]

        if not distinctive_tokens:
            return results  # 没有区分性词，不重排序

        # 对每个结果计算区分性词匹配率，调整 score
        for i, r in enumerate(results):
            tok_set = result_token_sets[i]
            matched = sum(1 for tok in distinctive_tokens if tok in tok_set)
            match_ratio = matched / len(distinctive_tokens)
            old_score = getattr(r, score_attr)
            setattr(r, score_attr, old_score * (0.5 + match_ratio))

        # 重新排序
        results.sort(key=lambda x: getattr(x, score_attr), reverse=True)
        return results

    def enrich_hybrid_results(self, results: List) -> List:
        """批量补全混合检索结果的 content/doc_title/paragraph_num。

        BM25 的 _DocEntry 不存 content/title，VectorResult 也没有这些字段，
        所以混合检索后的 HybridResult 可能 content/doc_title 为空。
        此方法用 chunk_id 批量从 SQLite 查出真实内容、文档标题和段落号。

        同时过滤掉数据库中已不存在的过期 chunk（避免引用溯源显示空标题）。

        Args:
            results: HybridResult 列表（content/doc_title 可能为空）

        Returns:
            补全后的 HybridResult 列表（过滤掉过期条目）
        """
        if not results:
            return results
        chunk_ids = [r.chunk_id for r in results]
        doc_ids = list({r.doc_id for r in results if r.doc_id})

        with self._conn() as conn:
            placeholders = ",".join("?" * len(chunk_ids))
            rows = conn.execute(
                f"SELECT id, content, index_in_doc, heading FROM chunks WHERE id IN ({placeholders})",
                chunk_ids,
            ).fetchall()
            chunk_map = {
                r["id"]: (r["content"], r["index_in_doc"], r["heading"] or "")
                for r in rows
            }

            doc_title = {}
            doc_file_type: Dict[str, str] = {}
            if doc_ids:
                placeholders = ",".join("?" * len(doc_ids))
                rows = conn.execute(
                    f"SELECT id, title, file_type FROM documents WHERE id IN ({placeholders})",
                    doc_ids,
                ).fetchall()
                doc_title = {r["id"]: r["title"] for r in rows}
                doc_file_type = {r["id"]: r["file_type"] for r in rows}

        # file_type → format_tag 映射
        _FILE_TYPE_TO_FORMAT = {
            ".xlsx": "excel",
            ".pptx": "ppt",
            ".pdf": "pdf",
            ".docx": "docx",
            ".doc": "docx",
            ".md": "markdown",
            ".markdown": "markdown",
            ".html": "html",
            ".htm": "html",
            ".png": "image",
            ".jpg": "image",
            ".jpeg": "image",
            ".txt": "text",
            ".log": "text",
        }

        filled = []
        for r in results:
            entry = chunk_map.get(r.chunk_id)
            if entry is None:
                # 过期 chunk，跳过
                continue
            r.content = entry[0]
            r.paragraph_num = entry[1] + 1  # 0-based → 1-based 段落号
            r.heading = entry[2]
            r.doc_title = doc_title.get(r.doc_id, "") or r.doc_title
            # 从 file_type 映射 format_tag
            ft = doc_file_type.get(r.doc_id, "")
            r.format_tag = _FILE_TYPE_TO_FORMAT.get(ft, "text")
            filled.append(r)
        return filled

    # ---- 索引维护 ----

    def migrate_xlsx_chunks_inject_doc_title(self) -> int:
        """迁移：给 xlsx 文档的 chunks 注入「文档=DocTitle |」前缀。

        背景：
            xlsx parser 早期版本生成的 chunk content 只有 sheet 名前缀，
            缺文档标题语义。导致 BM25 无法命中"智能终端怎么安装"类查询
            （"智能"二字只在文档标题里，不在 chunk content）。

        本方法幂等：
            - 已含 `文档=` 前缀的 chunk 跳过
            - 仅对 xlsx 文档的 chunks 操作
            - 修改 chunk content 后重建 BM25 索引

        Returns:
            被修改的 chunk 数量
        """
        import logging
        logger = logging.getLogger(__name__)

        modified = 0
        with self._conn() as conn:
            # 找出所有 xlsx 文档
            xlsx_docs = conn.execute(
                "SELECT id, title FROM documents WHERE file_type = '.xlsx'"
            ).fetchall()
            if not xlsx_docs:
                return 0

            for doc in xlsx_docs:
                doc_id = doc["id"]
                doc_title = doc["title"]
                # 查询该文档的所有 chunks
                rows = conn.execute(
                    "SELECT id, content FROM chunks WHERE doc_id = ?",
                    (doc_id,),
                ).fetchall()
                for r in rows:
                    content = r["content"]
                    # 幂等：已含前缀则跳过
                    if "] 文档=" in content or content.startswith("文档="):
                        continue
                    # 注入前缀：把 "[SheetName] xxx" 改为 "[SheetName] 文档=DocTitle | xxx"
                    import re
                    new_content = re.sub(
                        r"^(\[[^\]]+\])\s+",
                        rf"\1 文档={doc_title} | ",
                        content,
                        count=1,
                    )
                    if new_content != content:
                        conn.execute(
                            "UPDATE chunks SET content = ? WHERE id = ?",
                            (new_content, r["id"]),
                        )
                        modified += 1

            if modified > 0:
                conn.commit()

        if modified > 0:
            logger.info(f"xlsx 文档标题迁移完成：修改 {modified} 条 chunk，重建 BM25 索引")
            self.rebuild_bm25_index()
        return modified

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

    # ---- 跨会话关键事实 ----

    def add_key_fact(self, fact: str, session: str = "", source: str = "") -> Optional[str]:
        """添加一条跨会话关键事实到 SQLite。

        JSON 中的 cross_session.json 仍保留全量记忆；key_facts 表只补充
        关键事实，便于后续检索、引用和按会话查询。

        Args:
            fact: 关键事实文本
            session: 所属会话名（空字符串表示全局）
            source: 来源轮次简要说明

        Returns:
            新记录 ID；如果同 session 下已有完全相同的事实则返回已有 ID
        """
        fact = fact.strip()
        if not fact:
            return None
        session = (session or "").strip()
        source = (source or "").strip()

        import uuid
        now = datetime.now().isoformat()

        with self._conn() as conn:
            # 同 session 下去重：相同 fact 文本不再新增
            row = conn.execute(
                "SELECT id FROM key_facts WHERE session = ? AND fact = ?",
                (session, fact),
            ).fetchone()
            if row:
                return row["id"]

            fact_id = str(uuid.uuid4())
            conn.execute(
                """
                INSERT INTO key_facts (id, session, fact, created_at, updated_at, source)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (fact_id, session, fact, now, now, source),
            )
        return fact_id

    def list_key_facts(
        self,
        session: Optional[str] = None,
        limit: int = 100,
    ) -> List[KeyFactRecord]:
        """列出关键事实。

        Args:
            session: 指定会话名（None 表示不限会话）
            limit: 最大返回条数

        Returns:
            KeyFactRecord 列表
        """
        with self._conn() as conn:
            if session is None:
                rows = conn.execute(
                    "SELECT * FROM key_facts ORDER BY updated_at DESC LIMIT ?",
                    (limit,),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM key_facts WHERE session = ? ORDER BY updated_at DESC LIMIT ?",
                    (session.strip(), limit),
                ).fetchall()
        return [
            KeyFactRecord(
                id=r["id"],
                session=r["session"],
                fact=r["fact"],
                created_at=r["created_at"],
                updated_at=r["updated_at"],
                source=r["source"],
            )
            for r in rows
        ]

    def search_key_facts(
        self,
        keyword: str,
        session: Optional[str] = None,
        limit: int = 10,
    ) -> List[KeyFactRecord]:
        """按关键词搜索关键事实（LIKE 匹配）。

        Args:
            keyword: 搜索关键词
            session: 指定会话名（None 表示不限会话）
            limit: 最大返回条数

        Returns:
            KeyFactRecord 列表
        """
        keyword = keyword.strip()
        if not keyword:
            return []
        pattern = f"%{keyword}%"
        with self._conn() as conn:
            if session is None:
                rows = conn.execute(
                    "SELECT * FROM key_facts WHERE fact LIKE ? ORDER BY updated_at DESC LIMIT ?",
                    (pattern, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT * FROM key_facts
                    WHERE session = ? AND fact LIKE ?
                    ORDER BY updated_at DESC LIMIT ?
                    """,
                    (session.strip(), pattern, limit),
                ).fetchall()
        return [
            KeyFactRecord(
                id=r["id"],
                session=r["session"],
                fact=r["fact"],
                created_at=r["created_at"],
                updated_at=r["updated_at"],
                source=r["source"],
            )
            for r in rows
        ]

    def remove_key_fact(self, fact_id: str) -> bool:
        """删除指定关键事实。

        Args:
            fact_id: 事实记录 ID

        Returns:
            True 成功删除 / False 不存在
        """
        with self._conn() as conn:
            cur = conn.execute("DELETE FROM key_facts WHERE id = ?", (fact_id,))
            return cur.rowcount > 0

    def clear_key_facts(self, session: Optional[str] = None) -> int:
        """清空关键事实。

        Args:
            session: 指定会话名（None 表示清空全部）

        Returns:
            删除的记录数
        """
        with self._conn() as conn:
            if session is None:
                cur = conn.execute("DELETE FROM key_facts")
            else:
                cur = conn.execute("DELETE FROM key_facts WHERE session = ?", (session.strip(),))
            return cur.rowcount

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

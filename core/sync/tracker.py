"""文件追踪 + 增量同步。

追踪 file_path → doc_id 映射，检测文件变更，实现增量同步。
"""
from __future__ import annotations

import hashlib
import logging
import sqlite3
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

logger = logging.getLogger(__name__)


@dataclass
class FileInfo:
    """文件追踪记录。"""
    file_path: str
    doc_id: str
    file_hash: str
    file_mtime: float
    file_size: int
    last_synced: str


@dataclass
class SyncResult:
    """同步结果汇总。"""
    added: List[str] = field(default_factory=list)
    updated: List[str] = field(default_factory=list)
    deleted: List[str] = field(default_factory=list)
    skipped: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)

    @property
    def total(self) -> int:
        """总处理数。"""
        return len(self.added) + len(self.updated) + len(self.deleted) + len(self.skipped) + len(self.errors)

    @property
    def has_changes(self) -> bool:
        """是否有变更。"""
        return bool(self.added or self.updated or self.deleted)


class FileTracker:
    """文件追踪器：维护 file_path → doc_id 映射。"""

    def __init__(self, storage_path: Path) -> None:
        self.storage_path = Path(storage_path)
        self.db_path = self.storage_path / "file_tracker.db"
        self._init_db()

    def _init_db(self) -> None:
        """初始化追踪数据库。"""
        self.storage_path.mkdir(parents=True, exist_ok=True)
        with self._conn() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS file_index (
                    file_path     TEXT PRIMARY KEY,
                    doc_id        TEXT NOT NULL,
                    file_hash     TEXT NOT NULL,
                    file_mtime    REAL NOT NULL,
                    file_size     INTEGER NOT NULL,
                    last_synced   TEXT NOT NULL
                )
                """
            )

    def _conn(self) -> sqlite3.Connection:
        """获取数据库连接。"""
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        return conn

    def _compute_hash(self, file_path: Path) -> str:
        """计算文件内容 SHA256。"""
        h = hashlib.sha256()
        with open(file_path, "rb") as f:
            while True:
                chunk = f.read(8192)
                if not chunk:
                    break
                h.update(chunk)
        return h.hexdigest()

    def track_file(self, file_path: str, doc_id: str) -> FileInfo:
        """记录或更新文件追踪信息。"""
        p = Path(file_path)
        now = time.strftime("%Y-%m-%dT%H:%M:%S")
        info = FileInfo(
            file_path=str(p),
            doc_id=doc_id,
            file_hash=self._compute_hash(p),
            file_mtime=p.stat().st_mtime,
            file_size=p.stat().st_size,
            last_synced=now,
        )
        with self._conn() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO file_index
                    (file_path, doc_id, file_hash, file_mtime, file_size, last_synced)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (info.file_path, info.doc_id, info.file_hash,
                 info.file_mtime, info.file_size, info.last_synced),
            )
        return info

    def check_file_status(self, file_path: str) -> str:
        """检查文件状态：new / modified / unchanged / deleted。

        Args:
            file_path: 文件绝对路径

        Returns:
            状态字符串
        """
        p = Path(file_path)
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM file_index WHERE file_path = ?",
                (str(p),),
            ).fetchone()

        if row is None:
            return "new" if p.exists() else "deleted"

        if not p.exists():
            return "deleted"

        # 检查 mtime
        current_mtime = p.stat().st_mtime
        if current_mtime != row["file_mtime"]:
            # mtime 变了，检查内容 hash
            current_hash = self._compute_hash(p)
            if current_hash != row["file_hash"]:
                return "modified"
            else:
                # 内容没变，更新 mtime
                self.track_file(file_path, row["doc_id"])
                return "unchanged"

        return "unchanged"

    def scan_directory(self, dir_path: str) -> List[str]:
        """扫描目录，返回所有支持的文件路径。"""
        from core.ingestion.parser import is_supported
        d = Path(dir_path)
        if not d.exists() or not d.is_dir():
            return []
        result = []
        for f in d.rglob("*"):
            if f.is_file() and is_supported(f):
                result.append(str(f))
        return result

    def get_tracked_files(self) -> List[FileInfo]:
        """获取所有追踪的文件。"""
        with self._conn() as conn:
            rows = conn.execute("SELECT * FROM file_index").fetchall()
        return [
            FileInfo(
                file_path=r["file_path"],
                doc_id=r["doc_id"],
                file_hash=r["file_hash"],
                file_mtime=r["file_mtime"],
                file_size=r["file_size"],
                last_synced=r["last_synced"],
            )
            for r in rows
        ]

    def remove_tracked(self, file_path: str) -> None:
        """移除追踪记录。"""
        with self._conn() as conn:
            conn.execute("DELETE FROM file_index WHERE file_path = ?", (file_path,))

    def get_file_history(self, file_path: str) -> Optional[FileInfo]:
        """查询单个文件的追踪记录（mtime/hash/doc_id 等最新状态）。

        Args:
            file_path: 文件绝对路径

        Returns:
            FileInfo 或 None（未追踪）
        """
        p = Path(file_path)
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM file_index WHERE file_path = ?",
                (str(p),),
            ).fetchone()
        if row is None:
            return None
        return FileInfo(
            file_path=row["file_path"],
            doc_id=row["doc_id"],
            file_hash=row["file_hash"],
            file_mtime=row["file_mtime"],
            file_size=row["file_size"],
            last_synced=row["last_synced"],
        )

    def reset(self) -> int:
        """清空所有追踪记录（下次同步会全量重建）。

        Returns:
            被清除的记录数
        """
        with self._conn() as conn:
            count_row = conn.execute("SELECT COUNT(*) FROM file_index").fetchone()
            count = count_row[0] if count_row else 0
            conn.execute("DELETE FROM file_index")
        return count

    def sync_directory(
        self,
        dir_path: str,
        storage,  # Storage 实例
        on_progress=None,  # 可选回调 callback(action: str, file_path: str)
    ) -> SyncResult:
        """增量同步整个目录。

        检测新增/修改/删除的文件，自动入库/更新/清理。
        """
        from core.ingestion.parser import parse, is_supported
        from core.ingestion.chunker import chunk_document
        from config import settings

        result = SyncResult()
        d = Path(dir_path)

        # 1. 扫描当前目录所有支持的文件
        current_files = set(self.scan_directory(dir_path))

        # 2. 查找已追踪的文件中属于该目录的
        # Python 3.9 兼容：is_relative_to 在 3.9 中可能不可用，用 startswith 替代
        tracked = self.get_tracked_files()
        tracked_in_dir = set()
        try:
            d_resolved = str(d.resolve())
            for f in tracked:
                f_resolved = str(Path(f.file_path).resolve())
                if f_resolved.startswith(d_resolved):
                    tracked_in_dir.add(f.file_path)
        except Exception:
            pass

        # 3. 检测已删除的文件
        for fp in tracked_in_dir:
            if fp not in current_files:
                # 文件被删除
                with self._conn() as conn:
                    row = conn.execute(
                        "SELECT doc_id FROM file_index WHERE file_path = ?", (fp,)
                    ).fetchone()
                if row:
                    try:
                        storage.delete_document(row["doc_id"])
                        self.remove_tracked(fp)
                        result.deleted.append(fp)
                        if on_progress:
                            on_progress("deleted", fp)
                    except Exception as e:
                        result.errors.append(f"删除失败 {fp}: {e}")

        # 4. 检测新增和修改的文件
        for fp in current_files:
            status = self.check_file_status(fp)
            if status == "new":
                try:
                    parsed = parse(Path(fp))
                    if not parsed.text.strip():
                        result.skipped.append(fp)
                        continue
                    chunks = chunk_document(
                        parsed,
                        chunk_size=settings.chunk_size,
                        chunk_overlap=settings.chunk_overlap,
                    )
                    record = storage.save_document(parsed, chunks, copy_file=True)
                    self.track_file(fp, record.id)
                    result.added.append(fp)
                    if on_progress:
                        on_progress("added", fp)
                except Exception as e:
                    result.errors.append(f"入库失败 {fp}: {e}")

            elif status == "modified":
                try:
                    # 删旧 → 重新入库
                    with self._conn() as conn:
                        row = conn.execute(
                            "SELECT doc_id FROM file_index WHERE file_path = ?", (fp,)
                        ).fetchone()
                    if row:
                        storage.delete_document(row["doc_id"])

                    parsed = parse(Path(fp))
                    if not parsed.text.strip():
                        result.skipped.append(fp)
                        continue
                    chunks = chunk_document(
                        parsed,
                        chunk_size=settings.chunk_size,
                        chunk_overlap=settings.chunk_overlap,
                    )
                    record = storage.save_document(parsed, chunks, copy_file=True)
                    self.track_file(fp, record.id)
                    result.updated.append(fp)
                    if on_progress:
                        on_progress("updated", fp)
                except Exception as e:
                    result.errors.append(f"更新失败 {fp}: {e}")

            else:
                result.skipped.append(fp)

        return result

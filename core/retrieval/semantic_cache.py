"""语义缓存：基于 query embedding 相似度匹配的问答缓存。

与精确缓存不同，语义缓存能命中"意思相近但表述不同"的查询：
- "什么是生态安葬？" vs "生态安葬是什么意思？" → 命中
- "杭州海葬政策" vs "杭州海葬有什么补贴？" → 不命中（相似度 < 阈值）

缓存层级：
- L1 精确缓存：query 文本完全相同 → 直接返回（<1ms）
- L2 语义缓存：embedding cosine 相似度 ≥ 阈值 → 直接返回（<5ms）

设计要点：
- 复用 VectorIndex 的 embedding 计算（避免重复模型加载）
- TTL 过期自动淘汰（默认 30 分钟）
- LRU 淘汰策略：容量超限时移除 last_access 最早的条目
- SQLite 持久化：跨进程共享，重启不丢失
- 线程安全（多线程 REPL/Web 都可安全访问）
"""
from __future__ import annotations

import hashlib
import json
import logging
import pickle
import sqlite3
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Tuple

import numpy as np

from config import settings

logger = logging.getLogger(__name__)


@dataclass
class CacheEntry:
    """单条缓存项。"""
    query: str                        # 原始查询文本
    query_embedding: List[float]      # query 的 embedding 向量
    answer: str                       # 完整答案（含 [n] 引用标记）
    citations: List[dict] = field(default_factory=list)  # 引用元数据
    sources: List[dict] = field(default_factory=list)    # 检索来源元数据
    timestamp: float = 0.0            # 写入时间戳
    last_access: float = 0.0          # 最后访问时间戳（用于 LRU）
    hit_count: int = 0                # 命中次数


class SemanticCache:
    """语义缓存（LRU + SQLite 持久化 + 向量化 L2 匹配）。

    Args:
        threshold: cosine 相似度阈值，≥ 此值视为命中（默认 0.92，越高越严格）
        ttl: 缓存存活秒数（默认 1800 = 30 分钟）
        max_size: 最大缓存条目数（默认 500，LRU 淘汰）
        db_path: SQLite 持久化路径，None 时不持久化（仅内存）

    性能优化（P1）：
        L2 语义匹配用 numpy 矩阵运算一次算所有相似度，比 Python 循环快 10-50x。
        维护一个 [n, dim] 的 embedding 矩阵和 [n] 的 norm 向量，
        get/put/remove 时增量同步，避免重复计算。
    """

    def __init__(
        self,
        threshold: float = 0.92,
        ttl: int = 1800,
        max_size: int = 500,
        db_path: Optional[Path] = None,
    ) -> None:
        self.threshold = threshold
        self.ttl = ttl
        self.max_size = max_size
        self._entries: List[CacheEntry] = []
        self._exact: dict = {}  # query_hash → index in _entries（L1 精确缓存）
        self._lock = threading.RLock()

        # 向量化索引：维护 embedding 矩阵和 norm 向量，让 L2 匹配从 O(n) 循环
        # 变成单次矩阵乘法。entries 变动时增量更新。
        self._emb_matrix: Optional[np.ndarray] = None  # shape: [n, dim]
        self._emb_norms: Optional[np.ndarray] = None   # shape: [n]
        self._emb_dim: Optional[int] = None

        # SQLite 持久化
        self._db_path = db_path or (settings.storage_path / "semantic_cache.db")
        self._db_conn: Optional[sqlite3.Connection] = None
        self._init_db()
        self._load_from_db()

    # ============================================================
    # SQLite 持久化
    # ============================================================

    def _init_db(self) -> None:
        """初始化 SQLite 缓存表。

        若 db 文件损坏（disk I/O error / file is not a database 等），
        自动删除 db + wal/shm 后重建，避免永久退化为内存模式导致跨进程缓存失效。
        """
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        for attempt in (1, 2):
            try:
                conn = sqlite3.connect(
                    str(self._db_path), check_same_thread=False
                )
                conn.row_factory = sqlite3.Row
                conn.execute("PRAGMA journal_mode=WAL")
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS semantic_cache (
                        query_hash      TEXT PRIMARY KEY,
                        query           TEXT NOT NULL,
                        query_embedding BLOB NOT NULL,
                        answer          TEXT NOT NULL,
                        citations       TEXT DEFAULT '[]',
                        sources         TEXT DEFAULT '[]',
                        timestamp       REAL NOT NULL,
                        last_access     REAL NOT NULL,
                        hit_count       INTEGER DEFAULT 0
                    )
                """)
                conn.execute(
                    "CREATE INDEX IF NOT EXISTS idx_sc_last_access "
                    "ON semantic_cache(last_access)"
                )
                conn.commit()
                self._db_conn = conn
                return
            except sqlite3.DatabaseError as e:
                # 关闭失败的连接
                try:
                    conn.close()
                except Exception:
                    pass
                if attempt == 1:
                    logger.warning(
                        f"语义缓存 SQLite 损坏 ({e})，删除重建: {self._db_path}"
                    )
                    # 删除 db + wal + shm，让下次尝试重建
                    for suffix in ("", "-wal", "-shm"):
                        p = Path(str(self._db_path) + suffix)
                        if p.exists():
                            try:
                                p.unlink()
                            except Exception:
                                pass
                    continue
                logger.warning(f"语义缓存 SQLite 初始化失败，仅用内存: {e}")
                self._db_conn = None
                return
            except Exception as e:
                logger.warning(f"语义缓存 SQLite 初始化失败，仅用内存: {e}")
                try:
                    conn.close()
                except Exception:
                    pass
                self._db_conn = None
                return

    def _load_from_db(self) -> None:
        """从 SQLite 加载未过期的缓存条目到内存。"""
        if self._db_conn is None:
            return
        try:
            now = time.time()
            rows = self._db_conn.execute(
                "SELECT query_hash, query, query_embedding, answer, "
                "citations, sources, timestamp, last_access, hit_count "
                "FROM semantic_cache WHERE ? - timestamp <= ? "
                "ORDER BY last_access DESC LIMIT ?",
                (now, self.ttl, self.max_size),
            ).fetchall()
            with self._lock:
                self._entries.clear()
                self._exact.clear()
                self._reset_embedding_index()
                for row in rows:
                    entry = CacheEntry(
                        query=row["query"],
                        query_embedding=pickle.loads(row["query_embedding"]),
                        answer=row["answer"],
                        citations=json.loads(row["citations"]),
                        sources=json.loads(row["sources"]),
                        timestamp=row["timestamp"],
                        last_access=row["last_access"],
                        hit_count=row["hit_count"],
                    )
                    self._entries.append(entry)
                    self._exact[row["query_hash"]] = len(self._entries) - 1
                    self._append_embedding(entry.query_embedding)
            if self._entries:
                logger.info(f"语义缓存从 SQLite 恢复 {len(self._entries)} 条")
        except Exception as e:
            logger.warning(f"语义缓存从 SQLite 加载失败: {e}")

    def _persist_entry(self, entry: CacheEntry) -> None:
        """将单条缓存写入 SQLite（调用方需持有锁）。"""
        if self._db_conn is None:
            return
        try:
            qhash = self._hash(entry.query)
            self._db_conn.execute(
                "INSERT OR REPLACE INTO semantic_cache "
                "(query_hash, query, query_embedding, answer, "
                " citations, sources, timestamp, last_access, hit_count) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    qhash,
                    entry.query,
                    pickle.dumps(entry.query_embedding),
                    entry.answer,
                    json.dumps(entry.citations, ensure_ascii=False),
                    json.dumps(entry.sources, ensure_ascii=False),
                    entry.timestamp,
                    entry.last_access,
                    entry.hit_count,
                ),
            )
            self._db_conn.commit()
        except Exception as e:
            logger.warning(f"语义缓存写入 SQLite 失败: {e}")

    def _delete_entry_from_db(self, query: str) -> None:
        """从 SQLite 删除单条缓存（调用方需持有锁）。"""
        if self._db_conn is None:
            return
        try:
            qhash = self._hash(query)
            self._db_conn.execute(
                "DELETE FROM semantic_cache WHERE query_hash = ?", (qhash,)
            )
            self._db_conn.commit()
        except Exception as e:
            logger.warning(f"语义缓存从 SQLite 删除失败: {e}")

    def _flush_db(self) -> None:
        """清空 SQLite 缓存表（调用方需持有锁）。"""
        if self._db_conn is None:
            return
        try:
            self._db_conn.execute("DELETE FROM semantic_cache")
            self._db_conn.commit()
        except Exception as e:
            logger.warning(f"语义缓存清空 SQLite 失败: {e}")

    # ============================================================
    # 核心方法
    # ============================================================

    def _hash(self, query: str) -> str:
        """query 归一化后 hash（去首尾空格 + 小写）。"""
        return hashlib.sha256(query.strip().lower().encode("utf-8")).hexdigest()

    def _cosine_similarity(self, a: List[float], b: List[float]) -> float:
        """计算两个向量的 cosine 相似度。"""
        a_arr = np.array(a, dtype=np.float32)
        b_arr = np.array(b, dtype=np.float32)
        denom = np.linalg.norm(a_arr) * np.linalg.norm(b_arr)
        if denom == 0:
            return 0.0
        return float(np.dot(a_arr, b_arr) / denom)

    # ============================================================
    # 向量化索引维护（P1 性能优化）
    # ============================================================

    def _reset_embedding_index(self) -> None:
        """重置 embedding 矩阵索引（调用方需持有锁）。"""
        self._emb_matrix = None
        self._emb_norms = None
        self._emb_dim = None

    def _append_embedding(self, embedding: List[float]) -> None:
        """向 embedding 矩阵追加一行（调用方需持有锁）。

        第一次 append 时初始化矩阵；后续用 vstack 追加。
        vstack 在大矩阵上比 list.append + np.array 慢，但缓存条目通常 < 500，
        且 put 频率远低于 get，所以追加成本可接受。
        """
        if not embedding:
            return
        vec = np.asarray(embedding, dtype=np.float32)
        dim = vec.shape[0]
        if self._emb_matrix is None:
            self._emb_matrix = vec.reshape(1, -1)
            self._emb_norms = np.array([np.linalg.norm(vec)], dtype=np.float32)
            self._emb_dim = dim
        elif dim != self._emb_dim:
            # 维度不一致（理论不应发生），降级为重置
            logger.warning(
                f"语义缓存 embedding 维度不一致: 期望 {self._emb_dim}, 实际 {dim}"
            )
            self._rebuild_embedding_index()
        else:
            self._emb_matrix = np.vstack([self._emb_matrix, vec.reshape(1, -1)])
            self._emb_norms = np.append(
                self._emb_norms, np.linalg.norm(vec)
            )

    def _remove_embedding_at(self, idx: int) -> None:
        """从 embedding 矩阵删除指定行（调用方需持有锁）。"""
        if self._emb_matrix is None or idx < 0 or idx >= self._emb_matrix.shape[0]:
            return
        self._emb_matrix = np.delete(self._emb_matrix, idx, axis=0)
        self._emb_norms = np.delete(self._emb_norms, idx)
        if self._emb_matrix.shape[0] == 0:
            self._reset_embedding_index()

    def _rebuild_embedding_index(self) -> None:
        """从 _entries 重建 embedding 矩阵（调用方需持有锁）。"""
        self._reset_embedding_index()
        for entry in self._entries:
            self._append_embedding(entry.query_embedding)

    def _find_best_match(self, query_embedding: List[float]) -> Tuple[int, float]:
        """用矩阵运算一次性计算所有相似度，返回 (best_idx, best_sim)。

        未命中（无缓存或全部过期）返回 (-1, 0.0)。
        调用方需持有锁。

        性能：O(n*dim) 一次矩阵乘法，比 O(n) Python 循环快 10-50x。
        """
        if self._emb_matrix is None or self._emb_matrix.shape[0] == 0:
            return -1, 0.0

        query_vec = np.asarray(query_embedding, dtype=np.float32)
        if query_vec.shape[0] != self._emb_dim:
            return -1, 0.0

        # 一次性算所有相似度：dot(q, e_i) / (|q| * |e_i|)
        query_norm = np.linalg.norm(query_vec)
        if query_norm == 0:
            return -1, 0.0

        # 用 np.maximum 避免 0 除
        denom = self._emb_norms * query_norm
        denom = np.maximum(denom, 1e-10)
        sims = (self._emb_matrix @ query_vec) / denom

        best_idx = int(np.argmax(sims))
        best_sim = float(sims[best_idx])
        return best_idx, best_sim

    def get(
        self,
        query: str,
        query_embedding: Optional[List[float]] = None,
    ) -> Optional[CacheEntry]:
        """查询缓存。

        Args:
            query: 用户查询文本
            query_embedding: query 的 embedding 向量（可选，提供时启用 L2 语义缓存）

        Returns:
            命中则返回 CacheEntry，未命中返回 None
        """
        now = time.time()
        qhash = self._hash(query)

        with self._lock:
            # L1 精确缓存：query hash 完全匹配
            idx = self._exact.get(qhash)
            if idx is not None:
                entry = self._entries[idx]
                if now - entry.timestamp <= self.ttl:
                    entry.hit_count += 1
                    entry.last_access = now
                    self._persist_entry(entry)
                    logger.debug(f"语义缓存 L1 命中: {query[:30]}...")
                    return entry
                else:
                    # 过期，移除
                    self._remove_at(idx)

            # L2 语义缓存：embedding 相似度匹配（向量化一次算所有相似度）
            if query_embedding is not None:
                best_idx, best_sim = self._find_best_match(query_embedding)
                if best_idx >= 0 and best_sim >= self.threshold:
                    entry = self._entries[best_idx]
                    # 命中后还要检查 TTL（_find_best_match 不检查时间）
                    if now - entry.timestamp <= self.ttl:
                        entry.hit_count += 1
                        entry.last_access = now
                        self._persist_entry(entry)
                        logger.info(
                            f"语义缓存 L2 命中 (sim={best_sim:.3f}): "
                            f"query='{query[:20]}' → cached='{entry.query[:20]}'"
                        )
                        return entry

        return None

    def put(
        self,
        query: str,
        query_embedding: List[float],
        answer: str,
        citations: Optional[List[dict]] = None,
        sources: Optional[List[dict]] = None,
    ) -> None:
        """写入缓存。

        Args:
            query: 用户查询文本
            query_embedding: query 的 embedding 向量
            answer: 完整答案
            citations: 引用元数据列表
            sources: 检索来源元数据列表
        """
        qhash = self._hash(query)
        now = time.time()
        entry = CacheEntry(
            query=query,
            query_embedding=query_embedding,
            answer=answer,
            citations=citations or [],
            sources=sources or [],
            timestamp=now,
            last_access=now,
        )

        with self._lock:
            # 已存在相同 query → 替换
            if qhash in self._exact:
                old_idx = self._exact[qhash]
                self._remove_at(old_idx)

            # 容量超限 → LRU 淘汰（移除 last_access 最早的）
            while len(self._entries) >= self.max_size:
                self._evict_lru()

            self._entries.append(entry)
            self._exact[qhash] = len(self._entries) - 1
            self._append_embedding(entry.query_embedding)
            self._persist_entry(entry)
            logger.debug(f"语义缓存写入: {query[:30]}... (total={len(self._entries)})")

    def _remove_at(self, idx: int) -> None:
        """移除指定索引的条目（调用方需持有锁）。"""
        if idx < 0 or idx >= len(self._entries):
            return
        entry = self._entries.pop(idx)
        self._delete_entry_from_db(entry.query)
        # 同步删除 embedding 行
        self._remove_embedding_at(idx)
        # 重建 _exact 索引（pop 后后面的索引前移）
        self._rebuild_exact_index()

    def _evict_lru(self) -> None:
        """LRU 淘汰：移除 last_access 最早的条目（调用方需持有锁）。"""
        if not self._entries:
            return
        # 找到 last_access 最小的条目
        lru_idx = 0
        lru_time = self._entries[0].last_access
        for i, entry in enumerate(self._entries[1:], 1):
            if entry.last_access < lru_time:
                lru_time = entry.last_access
                lru_idx = i
        self._remove_at(lru_idx)

    def _rebuild_exact_index(self) -> None:
        """重建 _exact 索引（调用方需持有锁）。"""
        self._exact = {}
        for i, entry in enumerate(self._entries):
            self._exact[self._hash(entry.query)] = i

    def clear(self) -> None:
        """清空全部缓存。"""
        with self._lock:
            self._entries.clear()
            self._exact.clear()
            self._reset_embedding_index()
            self._flush_db()
            logger.info("语义缓存已清空")

    def stats(self) -> dict:
        """返回缓存统计信息。"""
        with self._lock:
            total_hits = sum(e.hit_count for e in self._entries)
            return {
                "size": len(self._entries),
                "max_size": self.max_size,
                "total_hits": total_hits,
                "threshold": self.threshold,
                "ttl": self.ttl,
                "persisted": self._db_conn is not None,
            }

    def cleanup_expired(self) -> int:
        """清理过期条目，返回清理数量。"""
        now = time.time()
        with self._lock:
            before = len(self._entries)
            expired_indices = [
                i for i, e in enumerate(self._entries)
                if now - e.timestamp > self.ttl
            ]
            # 从后往前删，避免索引偏移
            for i in sorted(expired_indices, reverse=True):
                self._remove_at(i)
            cleaned = len(expired_indices)
            if cleaned > 0:
                logger.info(f"语义缓存清理过期条目: {cleaned} 个")
            return cleaned

    def flush(self) -> None:
        """将所有内存条目刷新到 SQLite（用于安全关闭）。"""
        if self._db_conn is None:
            return
        with self._lock:
            for entry in self._entries:
                self._persist_entry(entry)
            logger.info(f"语义缓存已刷新 {len(self._entries)} 条到 SQLite")

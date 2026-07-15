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
- 线程安全（多线程 REPL/Web 都可安全访问）
- 可选持久化到 SQLite（跨进程共享，默认仅内存）
"""
from __future__ import annotations

import hashlib
import logging
import threading
import time
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

import numpy as np

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
    hit_count: int = 0                # 命中次数


class SemanticCache:
    """语义缓存。

    Args:
        threshold: cosine 相似度阈值，≥ 此值视为命中（默认 0.92，越高越严格）
        ttl: 缓存存活秒数（默认 1800 = 30 分钟）
        max_size: 最大缓存条目数（默认 500，LRU 淘汰）
    """

    def __init__(
        self,
        threshold: float = 0.92,
        ttl: int = 1800,
        max_size: int = 500,
    ) -> None:
        self.threshold = threshold
        self.ttl = ttl
        self.max_size = max_size
        self._entries: List[CacheEntry] = []
        self._exact: dict = {}  # query_hash → index in _entries（L1 精确缓存）
        self._lock = threading.RLock()

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
                    logger.debug(f"语义缓存 L1 命中: {query[:30]}...")
                    return entry
                else:
                    # 过期，移除
                    self._remove_at(idx)

            # L2 语义缓存：embedding 相似度匹配
            if query_embedding is not None:
                best_sim = 0.0
                best_idx = -1
                for i, entry in enumerate(self._entries):
                    # 先检查 TTL
                    if now - entry.timestamp > self.ttl:
                        continue
                    sim = self._cosine_similarity(query_embedding, entry.query_embedding)
                    if sim > best_sim:
                        best_sim = sim
                        best_idx = i

                if best_idx >= 0 and best_sim >= self.threshold:
                    entry = self._entries[best_idx]
                    entry.hit_count += 1
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
        entry = CacheEntry(
            query=query,
            query_embedding=query_embedding,
            answer=answer,
            citations=citations or [],
            sources=sources or [],
            timestamp=time.time(),
        )

        with self._lock:
            # 已存在相同 query → 替换
            if qhash in self._exact:
                old_idx = self._exact[qhash]
                self._remove_at(old_idx)

            # 容量超限 → LRU 淘汰（移除最久未访问的）
            while len(self._entries) >= self.max_size:
                self._evict_oldest()

            self._entries.append(entry)
            self._exact[qhash] = len(self._entries) - 1
            logger.debug(f"语义缓存写入: {query[:30]}... (total={len(self._entries)})")

    def _remove_at(self, idx: int) -> None:
        """移除指定索引的条目（调用方需持有锁）。"""
        if idx < 0 or idx >= len(self._entries):
            return
        entry = self._entries.pop(idx)
        qhash = self._hash(entry.query)
        self._exact.pop(qhash, None)
        # 重建 _exact 索引（pop 后后面的索引前移）
        self._rebuild_exact_index()

    def _evict_oldest(self) -> None:
        """淘汰最久未写入的条目（FIFO，调用方需持有锁）。"""
        if not self._entries:
            return
        entry = self._entries.pop(0)
        qhash = self._hash(entry.query)
        self._exact.pop(qhash, None)
        self._rebuild_exact_index()

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
            }

    def cleanup_expired(self) -> int:
        """清理过期条目，返回清理数量。"""
        now = time.time()
        with self._lock:
            before = len(self._entries)
            self._entries = [e for e in self._entries if now - e.timestamp <= self.ttl]
            self._rebuild_exact_index()
            cleaned = before - len(self._entries)
            if cleaned > 0:
                logger.info(f"语义缓存清理过期条目: {cleaned} 个")
            return cleaned

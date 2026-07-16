"""P4: 语义缓存 LRU 淘汰 + SQLite 持久化测试。"""
import time
from pathlib import Path

import numpy as np
import pytest

from core.retrieval.semantic_cache import SemanticCache, CacheEntry


def _emb(seed: int = 0) -> list:
    """生成确定性 embedding（可复现）。"""
    rng = np.random.RandomState(seed)
    return rng.rand(64).tolist()


# ============================================================
# LRU 淘汰策略
# ============================================================

def test_lru_evicts_least_recently_accessed(tmp_path):
    """LRU 淘汰：移除 last_access 最早的条目，而非最早写入的。"""
    cache = SemanticCache(
        threshold=0.9, ttl=3600, max_size=3,
        db_path=tmp_path / "cache.db",
    )
    # 写入 3 条
    cache.put("问题0", _emb(0), "答案0")
    cache.put("问题1", _emb(1), "答案1")
    cache.put("问题2", _emb(2), "答案2")

    # 访问 问题0 和 问题2（让 问题1 成为最久未访问）
    cache.get("问题0")
    cache.get("问题2")

    # 写入第 4 条，触发 LRU 淘汰
    cache.put("问题3", _emb(3), "答案3")

    # 问题1 应被淘汰（last_access 最早）
    assert cache.get("问题1") is None
    # 问题0、问题2、问题3 应保留
    assert cache.get("问题0") is not None
    assert cache.get("问题2") is not None
    assert cache.get("问题3") is not None


def test_lru_eviction_keeps_recently_accessed(tmp_path):
    """频繁访问的条目不会被淘汰。"""
    cache = SemanticCache(
        threshold=0.9, ttl=3600, max_size=2,
        db_path=tmp_path / "cache.db",
    )
    cache.put("A", _emb(1), "答A")
    cache.put("B", _emb(2), "答B")

    # 访问 A，让它成为最近访问
    cache.get("A")

    # 写入 C，触发淘汰
    cache.put("C", _emb(3), "答C")

    # A 被访问过，应保留；B 未被访问，应被淘汰
    assert cache.get("A") is not None
    assert cache.get("B") is None
    assert cache.get("C") is not None


def test_lru_with_all_accessed(tmp_path):
    """所有条目都被访问过时，淘汰最早访问的。"""
    cache = SemanticCache(
        threshold=0.9, ttl=3600, max_size=3,
        db_path=tmp_path / "cache.db",
    )
    cache.put("A", _emb(1), "答A")
    time.sleep(0.01)
    cache.put("B", _emb(2), "答B")
    time.sleep(0.01)
    cache.put("C", _emb(3), "答C")

    # 按顺序访问 A → B → C（A 的 last_access 最早）
    cache.get("A")
    time.sleep(0.01)
    cache.get("B")
    time.sleep(0.01)
    cache.get("C")

    # 写入 D，触发淘汰
    cache.put("D", _emb(4), "答D")

    # A 的 last_access 最早（在 B、C 之前），应被淘汰
    assert cache.get("A") is None


# ============================================================
# SQLite 持久化
# ============================================================

def test_persistence_survives_restart(tmp_path):
    """重启后缓存不丢失。"""
    db_path = tmp_path / "cache.db"

    # 第一次创建，写入数据
    cache1 = SemanticCache(
        threshold=0.9, ttl=3600, max_size=10,
        db_path=db_path,
    )
    cache1.put("持久化测试", _emb(42), "持久化答案")

    # 第二次创建（模拟重启），从 SQLite 加载
    cache2 = SemanticCache(
        threshold=0.9, ttl=3600, max_size=10,
        db_path=db_path,
    )

    # 应能命中
    entry = cache2.get("持久化测试")
    assert entry is not None
    assert entry.answer == "持久化答案"


def test_persistence_hit_count_preserved(tmp_path):
    """持久化保留 hit_count。"""
    db_path = tmp_path / "cache.db"

    cache1 = SemanticCache(
        threshold=0.9, ttl=3600, max_size=10,
        db_path=db_path,
    )
    cache1.put("计数测试", _emb(1), "答案")
    cache1.get("计数测试")
    cache1.get("计数测试")

    cache2 = SemanticCache(
        threshold=0.9, ttl=3600, max_size=10,
        db_path=db_path,
    )
    entry = cache2.get("计数测试")
    assert entry is not None
    assert entry.hit_count >= 2  # 至少命中过 2 次


def test_clear_persists_to_db(tmp_path):
    """clear() 同时清空内存和 SQLite。"""
    db_path = tmp_path / "cache.db"

    cache1 = SemanticCache(
        threshold=0.9, ttl=3600, max_size=10,
        db_path=db_path,
    )
    cache1.put("清除测试", _emb(1), "答案")
    cache1.clear()

    # 重启后应为空
    cache2 = SemanticCache(
        threshold=0.9, ttl=3600, max_size=10,
        db_path=db_path,
    )
    assert cache2.stats()["size"] == 0
    assert cache2.get("清除测试") is None


def test_stats_includes_persisted_flag(tmp_path):
    """stats 返回 persisted 字段。"""
    cache = SemanticCache(
        threshold=0.9, ttl=3600, max_size=10,
        db_path=tmp_path / "cache.db",
    )
    stats = cache.stats()
    assert "persisted" in stats
    assert stats["persisted"] is True


def test_last_access_updated_on_get(tmp_path):
    """get() 命中后更新 last_access。"""
    cache = SemanticCache(
        threshold=0.9, ttl=3600, max_size=10,
        db_path=tmp_path / "cache.db",
    )
    cache.put("测试", _emb(1), "答案")

    # 获取 entry 查看 last_access
    with cache._lock:
        entry = cache._entries[0]
        original_last_access = entry.last_access

    time.sleep(0.05)
    cache.get("测试")

    with cache._lock:
        entry = cache._entries[0]
        assert entry.last_access > original_last_access


def test_flush_persists_all_entries(tmp_path):
    """flush() 将所有内存条目写入 SQLite。"""
    db_path = tmp_path / "cache.db"

    cache = SemanticCache(
        threshold=0.9, ttl=3600, max_size=10,
        db_path=db_path,
    )
    cache.put("flush1", _emb(1), "答1")
    cache.put("flush2", _emb(2), "答2")
    cache.flush()

    # 重启后应能恢复
    cache2 = SemanticCache(
        threshold=0.9, ttl=3600, max_size=10,
        db_path=db_path,
    )
    assert cache2.get("flush1") is not None
    assert cache2.get("flush2") is not None

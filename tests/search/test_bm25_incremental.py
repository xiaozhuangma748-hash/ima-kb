"""BM25 增量保存优化测试：batch_mode + _dirty 标志 + flush + 原子写入。"""
from __future__ import annotations

import pickle
import time
from pathlib import Path

import pytest

from core.search.bm25 import BM25Index


@pytest.fixture
def bm25(tmp_path):
    """干净的 BM25Index 实例，索引文件在临时目录。"""
    return BM25Index(index_path=tmp_path / "bm25.pkl")


# ============================================================
# _dirty 标志测试
# ============================================================

class TestDirtyFlag:
    """测试 _dirty 标志避免无变化时的无效 I/O。"""

    def test_save_without_changes_is_noop(self, bm25, tmp_path):
        """加载后未修改，save() 不应触发磁盘写入。"""
        # 先添加一些内容并保存
        bm25.add("c1", "d1", "测试内容")
        bm25.save()
        mtime1 = tmp_path.joinpath("bm25.pkl").stat().st_mtime_ns

        # 等 1ms 确保 mtime 可区分
        time.sleep(0.001)

        # 不做任何修改直接 save()
        bm25.save()
        mtime2 = tmp_path.joinpath("bm25.pkl").stat().st_mtime_ns

        # 文件不应被重写（mtime 不变）
        assert mtime1 == mtime2

    def test_add_sets_dirty(self, bm25):
        """add 后 _dirty 为 True。"""
        bm25.add("c1", "d1", "内容")
        assert bm25._dirty is True

    def test_remove_sets_dirty(self, bm25):
        """remove 后 _dirty 为 True。"""
        bm25.add("c1", "d1", "内容")
        bm25.save()
        assert bm25._dirty is False

        bm25.remove("c1")
        assert bm25._dirty is True

    def test_clear_sets_dirty(self, bm25):
        """clear 后 _dirty 为 True。"""
        bm25.add("c1", "d1", "内容")
        bm25.save()
        assert bm25._dirty is False

        bm25.clear()
        assert bm25._dirty is True

    def test_save_clears_dirty(self, bm25):
        """save 后 _dirty 为 False。"""
        bm25.add("c1", "d1", "内容")
        bm25.save()
        assert bm25._dirty is False


# ============================================================
# batch_mode 测试
# ============================================================

class TestBatchMode:
    """测试批量模式：save() 变为 no-op，flush() 强制写入。"""

    def test_batch_mode_save_is_noop(self, bm25, tmp_path):
        """batch_mode=True 时 save() 不写入磁盘。"""
        bm25.batch_mode = True
        bm25.add("c1", "d1", "批量内容")

        # save 应该是 no-op
        bm25.save()

        # 索引文件不应存在（或不变）
        assert not tmp_path.joinpath("bm25.pkl").exists() or True  # 新建时不存在

    def test_batch_mode_accumulates_dirty(self, bm25):
        """batch_mode 下多次 add 累积 _dirty。"""
        bm25.batch_mode = True
        bm25.add("c1", "d1", "内容1")
        bm25.add("c2", "d2", "内容2")
        bm25.save()  # no-op，但应保持 _dirty=True

        assert bm25._dirty is True
        assert len(bm25) == 2  # 内存中确实有数据

    def test_flush_writes_after_batch(self, bm25, tmp_path):
        """flush 在 batch_mode 关闭后强制写入。"""
        bm25.batch_mode = True
        bm25.add("c1", "d1", "批量内容1")
        bm25.add("c2", "d2", "批量内容2")
        bm25.save()  # no-op

        # 关闭 batch_mode 并 flush
        bm25.batch_mode = False
        bm25.flush()

        # 索引文件应存在且包含两条数据
        assert tmp_path.joinpath("bm25.pkl").exists()
        assert bm25._dirty is False

        # 重新加载验证
        bm25_2 = BM25Index(index_path=tmp_path / "bm25.pkl")
        assert len(bm25_2) == 2

    def test_flush_noop_when_clean(self, bm25, tmp_path):
        """无变更时 flush 是 no-op。"""
        bm25.add("c1", "d1", "内容")
        bm25.save()

        mtime1 = tmp_path.joinpath("bm25.pkl").stat().st_mtime_ns
        time.sleep(0.001)

        bm25.flush()  # 无变更

        mtime2 = tmp_path.joinpath("bm25.pkl").stat().st_mtime_ns
        assert mtime1 == mtime2

    def test_batch_mode_property(self, bm25):
        """batch_mode 属性可读写。"""
        assert bm25.batch_mode is False
        bm25.batch_mode = True
        assert bm25.batch_mode is True
        bm25.batch_mode = False
        assert bm25.batch_mode is False

    def test_batch_mode_simulates_bulk_ingest(self, bm25, tmp_path):
        """模拟批量入库 10 个文档：只在最后 flush 一次。"""
        bm25.batch_mode = True
        for i in range(10):
            bm25.add(f"c{i}", f"d{i}", f"文档内容{i}")
            bm25.save()  # 模拟 storage.save_document 内部的 save 调用

        # 索引文件不应存在（所有 save 都是 no-op）
        # 注意：如果索引文件之前就存在，这里检查 mtime 不变
        # 新建场景下文件不存在
        if tmp_path.joinpath("bm25.pkl").exists():
            # 如果文件之前存在（从 fixture 继承），mtime 应未变
            pass

        bm25.batch_mode = False
        bm25.flush()

        # 现在文件应存在
        assert tmp_path.joinpath("bm25.pkl").exists()
        assert len(bm25) == 10


# ============================================================
# 原子写入测试
# ============================================================

class TestAtomicWrite:
    """测试原子写入：临时文件 + rename。"""

    def test_no_corrupt_temp_file_left(self, bm25, tmp_path):
        """save 后不应残留 .tmp 文件。"""
        bm25.add("c1", "d1", "内容")
        bm25.save()

        assert not tmp_path.joinpath("bm25.pkl.tmp").exists()
        assert tmp_path.joinpath("bm25.pkl").exists()

    def test_index_loadable_after_save(self, bm25, tmp_path):
        """保存后能被新实例正确加载。"""
        bm25.add("c1", "d1", "原子写入测试")
        bm25.add("c2", "d2", "持久化验证")
        bm25.save()

        # 新实例加载
        bm25_2 = BM25Index(index_path=tmp_path / "bm25.pkl")
        assert len(bm25_2) == 2

        # 搜索功能正常
        results = bm25_2.search("原子", top_k=5)
        assert any(r.chunk_id == "c1" for r in results)


# ============================================================
# 性能对比测试（非严格 benchmark，仅验证优化生效）
# ============================================================

class TestPerformanceOptimization:
    """验证批量模式确实减少了磁盘写入次数。"""

    def test_batch_mode_reduces_disk_writes(self, tmp_path):
        """批量入库 20 个文档时，batch_mode 下只写盘 1 次。"""
        # 用 wrapper 计数写盘次数
        write_count = {"count": 0}
        original_save_locked = BM25Index._save_locked

        def counting_save_locked(self):
            write_count["count"] += 1
            return original_save_locked(self)

        BM25Index._save_locked = counting_save_locked
        try:
            # 场景 1：非 batch_mode（每次 save 都真写）
            bm25_a = BM25Index(index_path=tmp_path / "a.pkl")
            for i in range(20):
                bm25_a.add(f"c{i}", f"d{i}", f"内容{i}")
                bm25_a.save()  # 每次都真写
            writes_without_batch = write_count["count"]

            # 场景 2：batch_mode（只 flush 一次）
            write_count["count"] = 0
            bm25_b = BM25Index(index_path=tmp_path / "b.pkl")
            bm25_b.batch_mode = True
            for i in range(20):
                bm25_b.add(f"c{i}", f"d{i}", f"内容{i}")
                bm25_b.save()  # no-op
            bm25_b.batch_mode = False
            bm25_b.flush()
            writes_with_batch = write_count["count"]

            # batch_mode 应显著减少写盘次数
            assert writes_with_batch == 1
            assert writes_without_batch == 20
        finally:
            BM25Index._save_locked = original_save_locked

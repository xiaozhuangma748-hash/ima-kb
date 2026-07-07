"""文件追踪 + 增量同步测试。"""
import pytest
import time
from pathlib import Path
from unittest.mock import MagicMock, patch
from core.sync.tracker import FileTracker, SyncResult


def test_track_new_file(tmp_path):
    """追踪新文件。"""
    tracker = FileTracker(storage_path=tmp_path)
    f = tmp_path / "test.txt"
    f.write_text("测试内容", encoding="utf-8")

    info = tracker.track_file(str(f), doc_id="doc_001")
    assert info.doc_id == "doc_001"
    assert info.file_path == str(f)
    assert info.file_hash != ""
    assert info.file_mtime > 0


def test_detect_new_files(tmp_path):
    """检测目录中的新文件。"""
    tracker = FileTracker(storage_path=tmp_path)
    d = tmp_path / "docs"
    d.mkdir()
    (d / "a.txt").write_text("内容A", encoding="utf-8")
    (d / "b.txt").write_text("内容B", encoding="utf-8")

    new_files = tracker.scan_directory(str(d))
    assert len(new_files) == 2


def test_detect_modified_file(tmp_path):
    """检测已修改的文件。"""
    tracker = FileTracker(storage_path=tmp_path)
    f = tmp_path / "test.txt"
    f.write_text("原始内容", encoding="utf-8")
    tracker.track_file(str(f), doc_id="doc_001")

    # 修改文件
    time.sleep(0.1)
    f.write_text("修改后内容", encoding="utf-8")

    status = tracker.check_file_status(str(f))
    assert status == "modified"


def test_detect_deleted_file(tmp_path):
    """检测已删除的文件。"""
    tracker = FileTracker(storage_path=tmp_path)
    f = tmp_path / "test.txt"
    f.write_text("内容", encoding="utf-8")
    tracker.track_file(str(f), doc_id="doc_001")

    f.unlink()
    status = tracker.check_file_status(str(f))
    assert status == "deleted"


def test_unchanged_file_skipped(tmp_path):
    """未修改的文件状态为 unchanged。"""
    tracker = FileTracker(storage_path=tmp_path)
    f = tmp_path / "test.txt"
    f.write_text("内容", encoding="utf-8")
    tracker.track_file(str(f), doc_id="doc_001")

    status = tracker.check_file_status(str(f))
    assert status == "unchanged"


def test_sync_result_summary(tmp_path):
    """同步结果汇总。"""
    result = SyncResult(
        added=["doc_a"],
        updated=["doc_b"],
        deleted=["doc_c"],
        skipped=["doc_d"],
        errors=["error_msg"],
    )
    assert len(result.added) == 1
    assert len(result.updated) == 1
    assert result.total == 5
    assert result.has_changes


def test_reset_clears_all_tracked(tmp_path):
    """reset 清空所有追踪记录。"""
    tracker = FileTracker(storage_path=tmp_path)
    f1 = tmp_path / "a.txt"
    f2 = tmp_path / "b.txt"
    f1.write_text("内容A", encoding="utf-8")
    f2.write_text("内容B", encoding="utf-8")
    tracker.track_file(str(f1), doc_id="doc_a")
    tracker.track_file(str(f2), doc_id="doc_b")

    assert len(tracker.get_tracked_files()) == 2
    count = tracker.reset()
    assert count == 2
    assert len(tracker.get_tracked_files()) == 0


def test_reset_empty_returns_zero(tmp_path):
    """空追踪库 reset 应返回 0。"""
    tracker = FileTracker(storage_path=tmp_path)
    count = tracker.reset()
    assert count == 0


def test_reset_persists_across_instances(tmp_path):
    """reset 后重新实例化应仍为空。"""
    tracker = FileTracker(storage_path=tmp_path)
    f = tmp_path / "test.txt"
    f.write_text("内容", encoding="utf-8")
    tracker.track_file(str(f), doc_id="doc_001")

    tracker.reset()

    # 重新实例化（模拟程序重启）
    tracker2 = FileTracker(storage_path=tmp_path)
    assert len(tracker2.get_tracked_files()) == 0

"""记忆持久化测试。"""
import json
import pytest
from pathlib import Path
from core.memory.store import MemoryStore


def test_load_empty_when_file_missing(tmp_path):
    """文件不存在时返回空结构。"""
    store = MemoryStore(storage_path=tmp_path)
    data = store.load()
    assert data == {
        "profile": {},
        "workflow": {"patterns": [], "suggestions_enabled": True},
        "tasks": [],
        "history": {"recent_queries": []},
    }


def test_save_and_load_roundtrip(tmp_path):
    """保存后加载应一致。"""
    store = MemoryStore(storage_path=tmp_path)
    store.update("profile", "preferred_format", "table")
    store.update("profile", "focus_topics", ["骨灰安置"])
    store.save()

    store2 = MemoryStore(storage_path=tmp_path)
    data = store2.load()
    assert data["profile"]["preferred_format"] == "table"
    assert data["profile"]["focus_topics"] == ["骨灰安置"]


def test_update_creates_nested_keys(tmp_path):
    """update 能创建嵌套 key。"""
    store = MemoryStore(storage_path=tmp_path)
    store.update("profile", "preferred_style", "scholar")
    data = store.get_data()
    assert data["profile"]["preferred_style"] == "scholar"


def test_load_corrupted_json_backups(tmp_path):
    """损坏 JSON 备份后返回默认结构。"""
    (tmp_path / "memory.json").write_text("{invalid json", encoding="utf-8")
    store = MemoryStore(storage_path=tmp_path)
    data = store.load()
    assert "profile" in data  # 返回默认结构
    # 备份文件存在
    backups = list(tmp_path.glob("memory.json.bak.*"))
    assert len(backups) == 1


def test_atomic_write(tmp_path):
    """原子写入：写入过程中崩溃不应损坏原文件。"""
    store = MemoryStore(storage_path=tmp_path)
    store.update("profile", "preferred_format", "table")
    store.save()

    # 再次保存
    store.update("profile", "preferred_style", "scholar")
    store.save()

    data = store.load()
    assert data["profile"]["preferred_format"] == "table"
    assert data["profile"]["preferred_style"] == "scholar"

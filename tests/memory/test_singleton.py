"""MemoryStore 单例工厂测试。"""
from __future__ import annotations

from pathlib import Path

from core.memory.store import (
    MemoryStore,
    get_default_memory_store,
    reset_default_memory_store,
)


def test_get_default_returns_singleton(tmp_path, monkeypatch):
    """多次调用 get_default_memory_store 应返回同一实例。"""
    monkeypatch.setattr("core.memory.store.settings.storage_path", tmp_path)
    reset_default_memory_store()

    s1 = get_default_memory_store()
    s2 = get_default_memory_store()
    assert s1 is s2, "单例失效：两次调用返回不同实例"


def test_get_default_lazy_init(tmp_path, monkeypatch):
    """首次调用前不应创建实例。"""
    monkeypatch.setattr("core.memory.store.settings.storage_path", tmp_path)
    reset_default_memory_store()

    # 首次调用后才创建
    assert get_default_memory_store() is not None
    s1 = get_default_memory_store()
    s2 = get_default_memory_store()
    assert s1 is s2


def test_explicit_path_creates_new_instance(tmp_path, monkeypatch):
    """显式传 storage_path 应创建独立实例（用于测试隔离）。"""
    monkeypatch.setattr("core.memory.store.settings.storage_path", tmp_path)
    reset_default_memory_store()

    singleton = get_default_memory_store()
    isolated = MemoryStore(storage_path=tmp_path / "isolated")

    assert isolated is not singleton, "显式传路径仍返回单例，破坏测试隔离"
    assert isolated.file_path != singleton.file_path


def test_reset_clears_singleton(tmp_path, monkeypatch):
    """reset_default_memory_store 后再调用应创建新实例。"""
    monkeypatch.setattr("core.memory.store.settings.storage_path", tmp_path)

    reset_default_memory_store()
    s1 = get_default_memory_store()
    reset_default_memory_store()
    s2 = get_default_memory_store()

    assert s1 is not s2, "reset 后未创建新实例"


def test_singleton_shares_state(tmp_path, monkeypatch):
    """单例应共享内存状态（跨模块修改可见）。"""
    monkeypatch.setattr("core.memory.store.settings.storage_path", tmp_path)
    reset_default_memory_store()

    s1 = get_default_memory_store()
    s1.update("test_section", "key", "value")

    s2 = get_default_memory_store()
    assert s2.get_data().get("test_section", {}).get("key") == "value", "单例状态未共享"


def test_singleton_persists_to_disk(tmp_path, monkeypatch):
    """单例修改后 save 应持久化到磁盘，下次获取单例能读到。"""
    monkeypatch.setattr("core.memory.store.settings.storage_path", tmp_path)
    reset_default_memory_store()

    s1 = get_default_memory_store()
    s1.update("profile", "preferred_style", "scholar")
    s1.save()

    # 模拟进程重启
    reset_default_memory_store()
    s2 = get_default_memory_store()
    assert s2.get_data().get("profile", {}).get("preferred_style") == "scholar"

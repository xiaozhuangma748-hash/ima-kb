"""记忆持久化：JSON 文件 + 原子写入 + 损坏备份。"""
from __future__ import annotations

import copy
import json
import logging
import os
import threading
import time
from pathlib import Path
from typing import Any, Dict, Optional

from config import settings

logger = logging.getLogger(__name__)


# 默认记忆结构
DEFAULT_MEMORY = {
    "profile": {},
    "workflow": {"patterns": [], "suggestions_enabled": True},
    "tasks": [],
    "history": {"recent_queries": []},
}


class MemoryStore:
    """记忆数据 JSON 存储。"""

    def __init__(self, storage_path: Optional[Path] = None) -> None:
        if storage_path is None:
            storage_path = settings.storage_path
        self.storage_path = Path(storage_path)
        self.storage_path.mkdir(parents=True, exist_ok=True)
        self.file_path = self.storage_path / "memory.json"
        self._data: Dict = copy.deepcopy(DEFAULT_MEMORY)
        self._load()

    def _load(self) -> None:
        """加载记忆数据。文件不存在或损坏时用默认值。"""
        if not self.file_path.exists():
            self._data = copy.deepcopy(DEFAULT_MEMORY)
            return
        try:
            self._data = json.loads(self.file_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, ValueError) as e:
            # 备份损坏的文件
            bak = self.file_path.parent / f"{self.file_path.name}.bak.{int(time.time())}"
            try:
                self.file_path.rename(bak)
                logger.warning(f"记忆文件损坏，已备份到 {bak}")
            except Exception:
                pass
            self._data = copy.deepcopy(DEFAULT_MEMORY)

    def load(self) -> Dict:
        """加载并返回记忆数据。"""
        self._load()
        return self.get_data()

    def save(self) -> None:
        """原子写入：临时文件 + rename。"""
        tmp_path = self.file_path.with_suffix(".json.tmp")
        tmp_path.write_text(
            json.dumps(self._data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        os.replace(str(tmp_path), str(self.file_path))

    def update(self, section: str, key: str, value: Any) -> None:
        """更新某 section 下的 key。"""
        if section not in self._data:
            self._data[section] = {}
        if not isinstance(self._data[section], dict):
            self._data[section] = {}
        self._data[section][key] = value

    def get_data(self) -> Dict:
        """返回当前记忆数据。"""
        return self._data

    def clear(self) -> None:
        """清空所有记忆。"""
        self._data = copy.deepcopy(DEFAULT_MEMORY)
        self.save()


# ============================================================
# 单例工厂：默认 MemoryStore 共享同一实例
# ============================================================
# 背景：生产代码中多处 MemoryStore() 无参调用会创建独立实例，
# 每个实例都重新 load 文件且内存数据不共享，导致跨模块修改不可见。
# 通过 get_default_memory_store() 获取单例，保证全局一致。
# 测试代码继续用 MemoryStore(storage_path=tmp_path) 显式传路径以隔离。
_default_instance: Optional["MemoryStore"] = None
_default_lock = threading.Lock()


def get_default_memory_store() -> "MemoryStore":
    """获取默认 MemoryStore 单例（线程安全）。

    首次调用时惰性创建，后续调用返回同一实例。
    生产代码应优先使用此函数而非 MemoryStore()，
    测试代码隔离场景仍可用 MemoryStore(storage_path=...) 创建独立实例。

    Returns:
        全局共享的 MemoryStore 实例
    """
    global _default_instance
    if _default_instance is None:
        with _default_lock:
            # 双重检查锁定，避免多个线程同时进入临界区
            if _default_instance is None:
                _default_instance = MemoryStore()
    return _default_instance


def reset_default_memory_store() -> None:
    """重置单例（主要用于测试场景）。

    一般生产代码不需要调用此函数。
    """
    global _default_instance
    with _default_lock:
        _default_instance = None

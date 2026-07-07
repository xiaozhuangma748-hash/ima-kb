"""记忆持久化：JSON 文件 + 原子写入 + 损坏备份。"""
from __future__ import annotations

import copy
import json
import logging
import os
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

"""搜索配置存储模块。

管理搜索的默认配置（如默认标签、默认限制数量），
使用 JSON 文件持久化存储，支持原子写入。
"""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Optional


class SearchConfig:
    """搜索配置管理类。

    配置文件路径: storage/search_config.json
    默认值: tag=None, limit=10
    """

    def __init__(self, storage_path: Optional[Path] = None) -> None:
        """初始化搜索配置。

        Args:
            storage_path: 存储目录路径，默认为项目根目录下的 storage/
        """
        if storage_path is None:
            from config import settings
            storage_path = settings.storage_path

        self._config_file = storage_path / "search_config.json"
        self._storage_path = storage_path

        # 默认值
        self._default_tag: Optional[str] = None
        self._default_limit: int = 10

        # 加载配置
        self._load()

    def _load(self) -> None:
        """从 JSON 文件加载配置。"""
        if not self._config_file.exists():
            return

        try:
            with open(self._config_file, "r", encoding="utf-8") as f:
                data = json.load(f)

            self._default_tag = data.get("tag")
            self._default_limit = data.get("limit", 10)
        except (json.JSONDecodeError, IOError):
            # 配置文件损坏或读取失败，使用默认值
            pass

    def _save(self) -> None:
        """原子写入保存配置到 JSON 文件。"""
        self._storage_path.mkdir(parents=True, exist_ok=True)

        data = {
            "tag": self._default_tag,
            "limit": self._default_limit,
        }

        # 原子写入：先写临时文件，再重命名
        fd, temp_path = tempfile.mkstemp(
            dir=str(self._storage_path),
            suffix=".tmp",
            prefix=".search_config_",
        )

        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)

            # 重命名临时文件为目标文件（原子操作）
            Path(temp_path).replace(self._config_file)
        except Exception:
            # 写入失败，清理临时文件
            try:
                Path(temp_path).unlink(missing_ok=True)
            except Exception:
                pass
            raise

    def get_default_tag(self) -> Optional[str]:
        """获取默认标签。

        Returns:
            默认标签，None 表示无默认标签
        """
        return self._default_tag

    def get_default_limit(self) -> int:
        """获取默认限制数量。

        Returns:
            默认限制数量，默认 10
        """
        return self._default_limit

    def set_defaults(self, tag: Optional[str] = None, limit: Optional[int] = None) -> None:
        """设置默认值。

        Args:
            tag: 默认标签，None 表示不修改
            limit: 默认限制数量，None 表示不修改
        """
        if tag is not None:
            self._default_tag = tag

        if limit is not None:
            self._default_limit = limit

        self._save()

    def reset(self) -> None:
        """重置为默认值。"""
        self._default_tag = None
        self._default_limit = 10
        self._save()

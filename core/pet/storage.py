"""宠物状态 JSON 持久化。"""
from __future__ import annotations

import json
import time
from dataclasses import asdict
from pathlib import Path
from typing import Optional

from core.pet.pet import Pet


class PetStorage:
    """宠物状态存储（JSON 文件）。"""

    def __init__(self, storage_path: Optional[Path] = None) -> None:
        if storage_path is None:
            from config import settings
            storage_path = settings.storage_path
        self.storage_path = Path(storage_path)
        self.storage_path.mkdir(parents=True, exist_ok=True)
        self.file_path = self.storage_path / "pet.json"

    def load(self) -> Optional[Pet]:
        """加载宠物状态。文件不存在返回 None，损坏返回 None 并备份。"""
        if not self.file_path.exists():
            return None
        try:
            data = json.loads(self.file_path.read_text(encoding="utf-8"))
            return Pet(**data)
        except (json.JSONDecodeError, TypeError) as e:
            # 备份损坏的文件（用 parent / name.bak.ts 避免后缀替换问题）
            bak = self.file_path.parent / f"{self.file_path.name}.bak.{int(time.time())}"
            self.file_path.rename(bak)
            return None

    def save(self, pet: Pet) -> None:
        """保存宠物状态。"""
        data = asdict(pet)
        self.file_path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def create(self, name: str) -> Pet:
        """创建新宠物并保存。"""
        pet = Pet(name=name)
        pet.created_at = _now_iso()
        pet.last_decay = _now_iso()
        pet.last_interact = _now_iso()
        self.save(pet)
        return pet


def _now_iso() -> str:
    """当前时间的 ISO 字符串。"""
    from datetime import datetime
    return datetime.now().isoformat()

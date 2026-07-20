"""桌面宠物位置记忆与勿扰模式配置（持久化到 storage/desktop_pet.json）。

零侵入约束：
- 本模块属于 ``core/desktop/`` 新增模块，不修改项目任何现有文件。
- 仅通过 ``config.settings.storage_path`` 只读访问 storage 目录路径，
  不修改 ``config.py`` / ``config/`` 任何内容。
- 配置文件 ``storage/desktop_pet.json`` 运行时生成，删除后回到默认配置。

设计：
1. ``DesktopPetSettings`` 持久化窗口位置 / 尺寸 / 迷你模式 / 勿扰模式 / 音效开关。
2. ``DndFilter`` 在勿扰模式下静默非手动触发的状态变更与音效。
3. 线程安全：``save()`` 通过 ``threading.Lock`` 串行化文件写入。
"""
from __future__ import annotations

import json
import logging
import threading
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


class DesktopPetSettings:
    """桌面宠物配置持久化。

    字段：
        x, y: 窗口位置（int，默认 100, 100）
        size: 尺寸 S/M/L（默认 M）
        mini_mode: 迷你模式（bool，默认 False）
        dnd: 勿扰模式（bool，默认 False）
        sound: 音效开关（bool，默认 True）
    """

    DEFAULT_X = 100
    DEFAULT_Y = 100
    DEFAULT_SIZE = "M"
    DEFAULT_MINI = False
    DEFAULT_DND = False
    DEFAULT_SOUND = True

    def __init__(
        self,
        x: int = DEFAULT_X,
        y: int = DEFAULT_Y,
        size: str = DEFAULT_SIZE,
        mini_mode: bool = DEFAULT_MINI,
        dnd: bool = DEFAULT_DND,
        sound: bool = DEFAULT_SOUND,
    ) -> None:
        self.x = x
        self.y = y
        self.size = size
        self.mini_mode = mini_mode
        self.dnd = dnd
        self.sound = sound
        self._lock = threading.Lock()

    @classmethod
    def get_storage_path(cls) -> Path:
        """获取配置文件路径。

        通过 ``config.settings.storage_path`` 只读访问 storage 目录，
        若 config 不可用则回退到相对路径 ``storage/``。
        """
        try:
            from config import settings
            base = Path(settings.storage_path)
        except Exception:
            base = Path("storage")
        return base / "desktop_pet.json"

    @classmethod
    def load(cls) -> 'DesktopPetSettings':
        """从 storage/desktop_pet.json 加载配置，文件不存在时返回默认。"""
        path = cls.get_storage_path()
        if not path.exists():
            return cls()
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return cls(
                x=int(data.get("x", cls.DEFAULT_X)),
                y=int(data.get("y", cls.DEFAULT_Y)),
                size=str(data.get("size", cls.DEFAULT_SIZE)),
                mini_mode=bool(data.get("mini_mode", cls.DEFAULT_MINI)),
                dnd=bool(data.get("dnd", cls.DEFAULT_DND)),
                sound=bool(data.get("sound", cls.DEFAULT_SOUND)),
            )
        except Exception as e:
            logger.warning(f"加载配置失败，使用默认: {e}")
            return cls()

    def save(self) -> bool:
        """保存配置到 storage/desktop_pet.json。

        Returns:
            True 保存成功；False 保存失败（已记录日志）。
        """
        try:
            path = self.get_storage_path()
            path.parent.mkdir(parents=True, exist_ok=True)
            with self._lock:
                data = {
                    "x": self.x,
                    "y": self.y,
                    "size": self.size,
                    "mini_mode": self.mini_mode,
                    "dnd": self.dnd,
                    "sound": self.sound,
                }
                path.write_text(
                    json.dumps(data, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
            return True
        except Exception as e:
            logger.error(f"保存配置失败: {e}")
            return False

    def update_position(self, x: int, y: int) -> None:
        """更新位置并持久化。"""
        self.x = x
        self.y = y
        self.save()

    def update_size(self, size: str) -> None:
        """更新尺寸（S/M/L）并持久化。非法值忽略。"""
        if size not in ("S", "M", "L"):
            return
        self.size = size
        self.save()

    def toggle_dnd(self) -> bool:
        """切换勿扰模式，返回新状态。"""
        self.dnd = not self.dnd
        self.save()
        return self.dnd

    def toggle_sound(self) -> bool:
        """切换音效，返回新状态。"""
        self.sound = not self.sound
        self.save()
        return self.sound

    def toggle_mini_mode(self) -> bool:
        """切换迷你模式，返回新状态。"""
        self.mini_mode = not self.mini_mode
        self.save()
        return self.mini_mode

    def to_dict(self) -> dict:
        """转为字典（供 JS / Mobile 同步使用）。"""
        return {
            "x": self.x,
            "y": self.y,
            "size": self.size,
            "mini_mode": self.mini_mode,
            "dnd": self.dnd,
            "sound": self.sound,
        }

    @classmethod
    def from_dict(cls, data: dict) -> 'DesktopPetSettings':
        """从字典构造（供测试使用）。"""
        return cls(
            x=int(data.get("x", cls.DEFAULT_X)),
            y=int(data.get("y", cls.DEFAULT_Y)),
            size=str(data.get("size", cls.DEFAULT_SIZE)),
            mini_mode=bool(data.get("mini_mode", cls.DEFAULT_MINI)),
            dnd=bool(data.get("dnd", cls.DEFAULT_DND)),
            sound=bool(data.get("sound", cls.DEFAULT_SOUND)),
        )


class DndFilter:
    """勿扰模式过滤器：在 dnd 模式下静默非手动触发的状态变更。

    设计要点：
    1. ``should_silence`` 判断状态变更是否应被静默（不通知 JS / 不发声）。
    2. ``should_play_sound`` 判断是否应播放音效（综合 sound 与 dnd）。
    3. 手动触发的状态变更（如双击问答、拖拽入库）永远不静默，保证用户交互正常。
    """

    # 手动触发的状态（勿扰模式下仍允许）
    MANUAL_STATES = {
        # 用户主动操作触发的状态（保留扩展位，当前用 is_manual 标志位判断）
    }

    def __init__(self, settings: DesktopPetSettings) -> None:
        self.settings = settings

    def should_silence(self, state, is_manual: bool = False) -> bool:
        """判断该状态变更是否应被静默。

        Args:
            state: PetState 枚举值
            is_manual: 是否为用户手动触发（如双击问答、拖拽入库）

        Returns:
            True 表示应静默（不通知 JS / 不发声），False 表示正常处理
        """
        if not self.settings.dnd:
            return False
        if is_manual:
            return False  # 手动触发永远不静默
        # 勿扰模式下静默所有自动触发的状态变更
        return True

    def should_play_sound(self, is_manual: bool = False) -> bool:
        """是否应播放音效。

        Args:
            is_manual: 是否为用户手动触发

        Returns:
            True 应播放；False 应静音
        """
        if not self.settings.sound:
            return False
        if self.settings.dnd and not is_manual:
            return False
        return True

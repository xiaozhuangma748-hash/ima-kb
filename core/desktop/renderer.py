"""桌面宠物渲染资源加载器（Task 3）。

零侵入约束：
- 本模块属于 ``core/desktop/`` 新增模块，不修改项目任何现有文件。

设计说明：
- 项目已从 ASCII 艺术切换为 GIF 动画（``bridge.get_ascii`` 返回空字符串，
  GIF 切换由 JS 端 ``setCatGif(state)`` 完成）。
- ``AsciiArtLoader`` 保留为向后兼容的最小实现：按宠物分支与等级构造，
  提供 GIF 资源路径解析能力，供 ``bridge`` / ``app`` 注入使用。
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from core.desktop.states import PetState

__all__ = ["AsciiArtLoader"]

# 合法分支（与 core.pet / core.persona 保持一致）
_VALID_BRANCHES = {"scholar", "warrior", "artisan", "neutral"}


class AsciiArtLoader:
    """宠物渲染资源加载器（GIF 模式下的最小兼容实现）。

    Args:
        branch: 宠物分支（scholar/warrior/artisan/neutral），非法值回退 neutral。
        level: 宠物等级（预留，当前 GIF 不区分等级）。
    """

    def __init__(self, branch: str = "neutral", level: int = 1) -> None:
        self.branch = branch if branch in _VALID_BRANCHES else "neutral"
        self.level = max(1, int(level))

    # ---- 资源路径 ----
    @staticmethod
    def _static_dir() -> Path:
        return Path(__file__).parent / "static"

    def gif_path(self, state: PetState) -> Path:
        """返回指定状态的 GIF 绝对路径。"""
        return self._static_dir() / "cats" / f"cat_{state.value}.gif"

    def gif_rel(self, state: PetState) -> str:
        """返回指定状态的 GIF 相对路径（供 HTML/JS 使用）。"""
        return f"cats/cat_{state.value}.gif"

    def exists(self, state: PetState) -> bool:
        """检查指定状态的 GIF 资源是否存在。"""
        return self.gif_path(state).exists()

    # ---- 向后兼容：ASCII 接口（GIF 模式下返回空） ----
    def load(self, state: PetState) -> str:
        """加载指定状态的渲染内容。GIF 模式下返回空字符串。

        历史版本返回 ASCII 艺术文本；切换 GIF 后由 JS 端负责渲染，
        Python 端无需提供文本内容。
        """
        return ""

    def get_ascii(self, state: PetState) -> str:
        """``load`` 的别名，向后兼容。"""
        return self.load(state)

    def available_states(self) -> list:
        """返回 GIF 资源实际存在的状态列表。"""
        return [s for s in PetState if self.exists(s)]

    def __repr__(self) -> str:
        return f"AsciiArtLoader(branch={self.branch!r}, level={self.level})"

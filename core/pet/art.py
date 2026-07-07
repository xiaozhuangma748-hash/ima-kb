"""ASCII 艺术加载器。"""
from __future__ import annotations

from pathlib import Path
from typing import Optional


ARTS_DIR = Path(__file__).parent / "arts"


class ArtLibrary:
    """ASCII 艺术加载器。"""

    def get(
        self,
        branch: Optional[str],
        level: int,
        small: bool = False,
    ) -> str:
        """加载指定形态的 ASCII 艺术。

        Args:
            branch: None / "scholar" / "warrior" / "artisan"
            level: 1-10
            small: True 返回缩略版

        Returns:
            ASCII 艺术字符串
        """
        branch_key = branch or "none"
        suffix = "_small" if small else ""
        path = ARTS_DIR / f"{branch_key}_{level}{suffix}.txt"

        if not path.exists():
            # 尝试加载大尺寸再截断
            if small:
                full_path = ARTS_DIR / f"{branch_key}_{level}.txt"
                if full_path.exists():
                    lines = full_path.read_text(encoding="utf-8").split("\n")[:6]
                    return "\n".join(lines)

            # 都没有，返回占位符
            return self._fallback(branch, level, small)

        return path.read_text(encoding="utf-8")

    def _fallback(
        self,
        branch: Optional[str],
        level: int,
        small: bool = False,
    ) -> str:
        """占位符。small=True 时返回更短的版本以满足缩略要求。"""
        branch_label = branch or "未分系"
        if small:
            return f"""
   ???
 [{branch_label} Lv{level}]
"""
        return f"""
   ???
  ( ? )
   |||
 [{branch_label} Lv{level}]
"""

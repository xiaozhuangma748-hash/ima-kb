"""主题系统：Claude Code / MiMo / 极简 三套配色。

用法：
    from core.ui.theme import get_theme, set_theme, list_themes
    set_theme("mimo")           # 切换主题
    t = get_theme()             # 获取当前主题
    t.colors["primary"]         # 主色
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Optional


# ============================================================
# 主题定义
# ============================================================

@dataclass
class Theme:
    """一个主题的配色定义。"""
    name: str           # 主题标识（claude / mimo / minimal）
    label: str          # 显示名
    desc: str           # 描述
    colors: Dict[str, str] = field(default_factory=dict)
    # colors 含字段：
    #   primary / secondary / accent / success / warning / danger
    #   border_logo / border_welcome / border_tips / border_ai
    #   text_title / text_body / text_dim
    #   prompt / spinner / chart_bar


# 三套主题
THEMES: Dict[str, Theme] = {
    "claude": Theme(
        name="claude",
        label="Claude Code",
        desc="橙黄主调 + 青色辅助（默认，Claude Code 风格）",
        colors={
            "primary":        "yellow",       # 主色（Logo / 提示符）
            "secondary":      "cyan",         # 辅色（Welcome / 状态）
            "accent":         "magenta",      # 强调（标签 / 标记）
            "success":        "green",
            "warning":        "yellow",
            "danger":         "red",
            "border_logo":    "yellow",
            "border_welcome": "cyan",
            "border_tips":    "yellow",
            "border_ai":      "yellow",
            "text_title":     "bold yellow",
            "text_body":      "white",
            "text_dim":       "dim",
            "prompt":         "bold fg:ansiyellow",
            "spinner":        "yellow",
            "chart_bar":      "green",
            "ai_marker":      "bold yellow",  # ⏺ 标记
        },
    ),
    "mimo": Theme(
        name="mimo",
        label="MiMo Blue",
        desc="青蓝主调 + 紫色辅助（MiMo CODE 风格，冷静专业）",
        colors={
            "primary":        "cyan",
            "secondary":      "blue",
            "accent":         "magenta",
            "success":        "green",
            "warning":        "yellow",
            "danger":         "red",
            "border_logo":    "cyan",
            "border_welcome": "blue",
            "border_tips":    "magenta",
            "border_ai":      "cyan",
            "text_title":     "bold cyan",
            "text_body":      "white",
            "text_dim":       "dim",
            "prompt":         "bold fg:ansicyan",
            "spinner":        "cyan",
            "chart_bar":      "cyan",
            "ai_marker":      "bold cyan",
        },
    ),
    "minimal": Theme(
        name="minimal",
        label="极简白",
        desc="无色主调，纯文字感（专注内容，无干扰）",
        colors={
            "primary":        "white",
            "secondary":      "dim",
            "accent":         "bold",
            "success":        "green",
            "warning":        "yellow",
            "danger":         "red",
            "border_logo":    "white",
            "border_welcome": "white",
            "border_tips":    "white",
            "border_ai":      "white",
            "text_title":     "bold",
            "text_body":      "white",
            "text_dim":       "dim",
            "prompt":         "bold fg:ansiwhite",
            "spinner":        "white",
            "chart_bar":      "white",
            "ai_marker":      "bold white",
        },
    ),
}


# ============================================================
# 主题管理
# ============================================================

_CONFIG_PATH = Path("storage/theme.json")


def list_themes() -> Dict[str, Theme]:
    """列出所有可用主题。"""
    return THEMES


def get_theme(name: Optional[str] = None) -> Theme:
    """获取主题。不传名返回当前主题。"""
    if name is None:
        name = _load_current()
    return THEMES.get(name, THEMES["claude"])


def set_theme(name: str) -> Theme:
    """切换主题。返回切换后的主题。"""
    if name not in THEMES:
        raise ValueError(f"未知主题: {name}（可选: {list(THEMES.keys())}）")
    _save_current(name)
    return THEMES[name]


def _load_current() -> str:
    """读取当前主题名（持久化在 storage/theme.json）。"""
    try:
        if _CONFIG_PATH.exists():
            data = json.loads(_CONFIG_PATH.read_text(encoding="utf-8"))
            return data.get("theme", "claude")
    except Exception:
        pass
    return "claude"


def _save_current(name: str) -> None:
    """保存当前主题名。"""
    try:
        _CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        _CONFIG_PATH.write_text(
            json.dumps({"theme": name}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except Exception:
        pass

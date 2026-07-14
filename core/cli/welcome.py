"""启动页渲染与活动记录。

从 repl.py 第 131-342 行迁移：
- ``_load_activities()`` 读取活动记录
- ``_record_activity()`` 记录一条活动（最多保留 20 条）
- ``_render_welcome_panel()`` 渲染启动页
- ``_render_pet_compact()`` 渲染宠物紧凑横版
- ``_render_pet_empty_compact()`` 未领养宠物占位
- ``_render_bar()`` 渲染进度条
"""
from __future__ import annotations

import shutil
import sys
from typing import Optional

from rich.cells import cell_len, set_cell_size
from rich.console import Console, Group
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from config import settings, PROJECT_ROOT
from core.ui.theme import get_theme
from core.cli.constants import (
    console,
    PIXEL_PET_ASCII,
    _ACTIVITY_PATH,
    _LABEL_MAP,
)


def _load_activities() -> list[dict]:
    """读取活动记录。"""
    try:
        if _ACTIVITY_PATH.exists():
            import json
            return json.loads(_ACTIVITY_PATH.read_text("utf-8"))
    except Exception:
        pass
    return []


def _record_activity(act_type: str, desc: str, session: Optional[str] = None) -> None:
    """记录一条活动（最多保留 50 条，自动清理 7 天前的记录，同类型+描述去重）。

    Args:
        act_type: 活动类型（search/qa/ingest 等）
        desc: 活动描述
        session: 所属会话名（用于启动页按会话过滤）
    """
    from datetime import datetime, timedelta
    import json
    entries = _load_activities()
    # 清理 7 天前的旧记录
    cutoff = (datetime.now() - timedelta(days=7)).strftime("%m-%d")
    entries = [e for e in entries if e.get("time", "") >= cutoff]

    # 去重：同会话 + 同类型 + 同描述只保留最新一条
    new_entry = {
        "type": act_type,
        "desc": desc,
        "time": datetime.now().strftime("%m-%d %H:%M"),
        "session": session or "",
    }
    entries = [
        e for e in entries
        if not (
            e.get("session", "") == (session or "")
            and e.get("type") == act_type
            and e.get("desc") == desc
        )
    ]
    entries.insert(0, new_entry)

    if len(entries) > 50:
        entries = entries[:50]
    try:
        _ACTIVITY_PATH.parent.mkdir(parents=True, exist_ok=True)
        _ACTIVITY_PATH.write_text(json.dumps(entries, ensure_ascii=False, indent=2), "utf-8")
    except Exception:
        pass


def _w(text: str) -> int:
    """获取文本的实际显示列宽（中文占 2 列）。"""
    return cell_len(text)


def _pad_to_width(text: Text, width: int) -> Text:
    """将 Text 填充/截断到指定列宽。"""
    cur = cell_len(text.plain)
    if cur < width:
        text.append(" " * (width - cur))
    elif cur > width:
        truncated = set_cell_size(text.plain, width - 1) + "…"
        text = Text(truncated, style=text.style)
    return text


def _make_row(parts: list[tuple], width: int) -> Text:
    """构建一行 Text，精确到 width 列宽（中文按 2 列算）。"""
    result = Text()
    for s, style in parts:
        result.append(s, style=style)
    return _pad_to_width(result, width)


def _render_welcome_panel(stats: dict, llm_available: bool, pet: Optional["Pet"] = None,
                          session_name: Optional[str] = None) -> None:
    """渲染启动页（Claude Code 风格）。"""
    t = get_theme()
    term_cols = shutil.get_terminal_size((80, 24)).columns
    W = term_cols - 4  # 内宽 = 终端宽 - 2(border) - 2(左右各1空格)

    pet_color = t.colors["primary"]
    pet_ascii_lines_raw = PIXEL_PET_ASCII.strip("\n").split("\n")
    # 去掉每行多余的前导空格，让内容左对齐，确保视觉中心准确
    min_indent = min(len(l) - len(l.lstrip()) for l in pet_ascii_lines_raw if l.strip())
    pet_ascii_lines = [l[min_indent:] if l.strip() else l for l in pet_ascii_lines_raw]
    pet_ascii_w = max(_w(l) for l in pet_ascii_lines)
    project_path = str(PROJECT_ROOT.resolve()).replace(str(PROJECT_ROOT.home()), "~")
    status_text = "✓ 在线" if llm_available else "✗ 未配置"
    status_color = "green" if llm_available else "red"

    # ---- 右区宽度：约 40%，最小 30 列 ----
    right_w = max(30, int(W * 0.40))
    left_w = W - right_w - 3  # -3 = 竖线 + 左右各1空格

    # ============================================================
    # 右区内容：Tips（5条最核心） + 分隔线 + Recent activity（3条）
    # ============================================================
    right_rows: list[Text] = []

    # Tips 标题
    right_rows.append(Text("Tips for getting started", style=f"bold {t.colors['primary']}"))
    right_rows.append(Text(""))

    tip_items = [
        ("直接输入问题", "AI 问答"),
        ("/search <词>", "搜索知识库"),
        ("/ingest <路径>", "入库文件"),
        ("/agent", "AI Agent 模式"),
        ("/theme", "切换主题"),
    ]

    for cmd, desc in tip_items:
        line = Text()
        line.append(f"  {cmd}", style="white")
        line.append("  ")
        line.append(desc, style="dim")
        right_rows.append(_pad_to_width(line, right_w))

    # 分隔线（空行 + 分隔线 + 空行）
    right_rows.append(Text(""))
    right_rows.append(Text("─" * right_w, style="dim"))

    # Recent activity 标题
    right_rows.append(Text("Recent activity", style=f"bold {t.colors['primary']}"))
    right_rows.append(Text(""))

    all_entries = _load_activities()
    # 按当前会话过滤（session 为空表示旧记录，也显示）
    if session_name:
        recent_entries = [
            e for e in all_entries
            if e.get("session", "") == session_name or e.get("session", "") == ""
        ]
    else:
        recent_entries = all_entries
    if recent_entries:
        from datetime import datetime
        today = datetime.now().strftime("%m-%d")
        for e in recent_entries[:3]:
            e_time = e.get("time", "")
            time_str = e_time.split(" ", 1)[-1] if e_time.startswith(today) and " " in e_time else e_time
            e_type = e.get("type", "操作")
            e_desc = e.get("desc", "")
            label = _LABEL_MAP.get(e_type, "Action")

            prefix = f"  {label}  "
            desc_w = right_w - _w(prefix) - _w(time_str) - 1
            if desc_w < 5:
                desc_w = 5
            if _w(e_desc) > desc_w:
                desc_disp = set_cell_size(e_desc, desc_w - 1) + "…"
            else:
                desc_disp = e_desc

            used = _w(prefix) + _w(desc_disp)
            pad = right_w - used - _w(time_str)
            if pad < 1:
                pad = 1

            row = Text()
            row.append(prefix, style="white")
            row.append(desc_disp, style="dim")
            row.append(" " * pad)
            row.append(time_str, style="dim")
            right_rows.append(_pad_to_width(row, right_w))
    else:
        right_rows.append(Text("  No recent activity", style="dim"))

    # 底部统计信息
    right_rows.append(Text(""))
    doc_count = stats.get("documents", 0)
    today_count = len([e for e in recent_entries if e.get("time", "").startswith(datetime.now().strftime("%m-%d"))]) if recent_entries else 0
    stat_text = f"  {doc_count} 篇文档 · 今日 {today_count} 次操作"
    stat_row = Text(stat_text, style="dim")
    right_rows.append(_pad_to_width(stat_row, right_w))

    right_h = len(right_rows)

    # ============================================================
    # 左区内容：欢迎语 + 宠物 + 模型信息
    # 高度 = 右区高度（用空行填充居中）
    # ============================================================
    # 先构建左区实际内容
    left_content: list[Text] = []

    # 欢迎语
    welcome_text = "Welcome back!"
    welcome_pad = (left_w - _w(welcome_text)) // 2
    if welcome_pad < 0:
        welcome_pad = 0
    welcome_row = Text()
    welcome_row.append(" " * welcome_pad)
    welcome_row.append(welcome_text, style="bold white")
    left_content.append(_pad_to_width(welcome_row, left_w))

    left_content.append(Text(" " * left_w))

    # 宠物 ASCII（居中）
    for line in pet_ascii_lines:
        pet_pad = (left_w - pet_ascii_w) // 2
        if pet_pad < 0:
            pet_pad = 0
        pet_line = Text()
        pet_line.append(" " * pet_pad)
        pet_line.append(line, style=f"bold {pet_color}")
        left_content.append(_pad_to_width(pet_line, left_w))

    left_content.append(Text(" " * left_w))

    # 会话名称（如果有）
    if session_name:
        session_text = f"上次会话: {session_name}"
        session_pad = (left_w - _w(session_text)) // 2
        if session_pad < 0:
            session_pad = 0
        session_row = Text()
        session_row.append(" " * session_pad)
        session_row.append(session_text, style="dim")
        left_content.append(_pad_to_width(session_row, left_w))

    # 模型信息 + 状态
    model_text = f"{settings.llm_model} · {status_text}"
    model_pad = (left_w - _w(model_text)) // 2
    if model_pad < 0:
        model_pad = 0
    model_row = Text()
    model_row.append(" " * model_pad)
    model_row.append(f"{settings.llm_model} · ", style="dim")
    model_row.append(status_text, style=status_color)
    left_content.append(_pad_to_width(model_row, left_w))

    # 项目路径
    path_pad = (left_w - _w(project_path)) // 2
    if path_pad < 0:
        path_pad = 0
    path_row = Text()
    path_row.append(" " * path_pad)
    path_row.append(project_path, style="dim")
    left_content.append(_pad_to_width(path_row, left_w))

    content_h = len(left_content)

    # 用空行填充到与右区等高（上下均匀分配，视觉居中）
    left_rows: list[Text] = []
    total_pad = max(0, right_h - content_h)
    top_pad = total_pad // 2
    bottom_pad = total_pad - top_pad

    for _ in range(top_pad):
        left_rows.append(Text(" " * left_w))
    left_rows.extend(left_content)
    for _ in range(bottom_pad):
        left_rows.append(Text(" " * left_w))

    # ============================================================
    # 左右逐行合并 + 竖线
    # ============================================================
    rows: list[Text] = []
    main_rows_count = max(len(left_rows), len(right_rows))

    for i in range(main_rows_count):
        left = left_rows[i] if i < len(left_rows) else Text(" " * left_w)
        right = right_rows[i] if i < len(right_rows) else Text(" " * right_w)
        left = _pad_to_width(left, left_w)
        right = _pad_to_width(right, right_w)
        row = Text()
        row.append_text(left)
        row.append(" │ ", style="dim")
        row.append_text(right)
        rows.append(_pad_to_width(row, W))

    # ============================================================
    # 输出（用超大宽度 console 禁止自动换行）
    # ============================================================
    big_console = Console(
        file=sys.stdout,
        width=max(term_cols * 2, 500),
        color_system=console.color_system,
        no_color=console.no_color,
        legacy_windows=console.legacy_windows,
        soft_wrap=True,
    )

    def _p(t):
        big_console.print(t, end="\n")

    console.print()

    # 顶边框 + 标题（左上角）：╭── IMA v4.0 ────────────────╮
    left_border = "╭── "
    title_text = f"IMA v4.0"
    right_sep = " ──"
    right_fill_len = term_cols - _w(left_border) - _w(title_text) - _w(right_sep) - 1  # -1 for ╮
    if right_fill_len < 1:
        right_fill_len = 1
    title_line = Text()
    title_line.append(left_border, style=t.colors["border_welcome"])
    title_line.append(title_text, style=f"bold {t.colors['primary']}")
    title_line.append(right_sep, style=t.colors["border_welcome"])
    title_line.append("─" * right_fill_len, style=t.colors["border_welcome"])
    title_line.append("╮", style=t.colors["border_welcome"])
    _p(title_line)

    # 内容行
    border_style = t.colors["border_welcome"]
    for row in rows:
        line = Text()
        line.append("│ ", style=border_style)
        line.append_text(row)
        line.append(" │", style=border_style)
        _p(line)

    # 底边框
    bottom_line = Text()
    bottom_line.append("╰", style=border_style)
    bottom_line.append("─" * (term_cols - 2), style=border_style)
    bottom_line.append("╯", style=border_style)
    _p(bottom_line)

    console.print()


def _pad_to_width(text: Text, width: int) -> Text:
    """将 Text 填充/截断到指定列宽（中文按 2 列计算）。"""
    cur = cell_len(text.plain)
    if cur < width:
        text.append(" " * (width - cur))
    elif cur > width:
        truncated = set_cell_size(text.plain, width - 1) + "…"
        text = Text(truncated, style=text.style)
    return text


def _render_pet_compact(pet: "Pet") -> tuple:
    """渲染宠物紧凑横版（2 行）。返回 (line1, line2)。

    右栏数值根据终端宽度自动换行，用 2 空格分隔（不用竖线）。
    """
    branch_label = {"scholar": "学者", "warrior": "战士", "artisan": "工匠"}.get(pet.branch, "未分系")
    color = {"scholar": "cyan", "warrior": "red", "artisan": "yellow"}.get(pet.branch, "white")
    # 单行 Emoji 头像（按系别）
    avatar = {"scholar": "[O]", "warrior": "[W]", "artisan": "[A]"}.get(pet.branch, "[?]")
    line1 = Text.from_markup(
        f"  [{color}]{avatar}[/{color}] [bold magenta]{pet.name}[/bold magenta] "
        f"[dim]Lv{pet.level} {branch_label}[/dim]"
    )

    # 终端宽度自适应：右栏宽度 = 终端宽度 - 左栏(缩进 2) - 4(间距)
    term_cols = shutil.get_terminal_size((80, 24)).columns
    right_width = max(20, term_cols - 2 - 4)

    # 数值对 (可见文本, markup 文本)，用 2 空格分隔
    suffix = f"→{pet.exp_remaining()}" if pet.level < 10 else "(满级)"
    stat_parts = [
        (f"饱食:{pet.hunger}",                   f"饱食:{pet.hunger}"),
        (f"能量:{pet.energy}",                   f"能量:{pet.energy}"),
        (f"心情:{pet.mood}",                     f"心情:{pet.mood}"),
        (f"清洁:{pet.cleanliness}",              f"清洁:{pet.cleanliness}"),
        (f"经验:{pet.exp}/{pet.exp_needed()}",   f"经验:{pet.exp}/{pet.exp_needed()}"),
        (suffix,                                 f"[dim]{suffix}[/dim]"),
    ]

    # 自动换行：超出右栏宽度时分行
    sep = "  "
    wrapped: list[str] = []
    cur_vis = ""
    cur_mk = ""
    for vis, mk in stat_parts:
        cand_vis = f"{cur_vis}{sep}{vis}" if cur_vis else vis
        if cell_len(cand_vis) <= right_width:
            cur_vis = cand_vis
            cur_mk = f"{cur_mk}{sep}{mk}" if cur_mk else mk
        else:
            if cur_mk:
                wrapped.append(cur_mk)
            cur_vis = vis
            cur_mk = mk
    if cur_mk:
        wrapped.append(cur_mk)

    indent = "  "
    line2 = Text.from_markup("\n".join(f"{indent}{w}" for w in wrapped))
    return line1, line2


def _render_pet_empty_compact() -> tuple:
    """未领养宠物的占位（2 行）。"""
    return (
        Text.from_markup("  [?][bold magenta]虚拟宠物[/bold magenta] [dim]/pet adopt 领养[/dim]"),
        Text(""),  # 空行占位
    )


def _render_bar(value: int, width: int = 16) -> str:
    """渲染一个进度条（0-100）。

    返回 rich markup 字符串，颜色随数值变化：
    - >=70 绿色
    - >=40 黄色
    - <40  红色
    """
    value = max(0, min(100, value))
    filled = round(value / 100 * width)
    empty = width - filled
    if value >= 70:
        color = "green"
    elif value >= 40:
        color = "yellow"
    else:
        color = "red"
    return f"[{color}]{'█' * filled}[/][dim]{'░' * empty}[/dim]"

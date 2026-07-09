"""交互式 REPL CLI：终端常驻对话模式。

进入后：
- 直接输入文本 → AI 问答（支持多轮对话，保留上下文）
- /search <词>  → BM25 搜索
- /ingest <路径> → 入库
- /list         → 列出文档
- /show <id>    → 文档详情
- /delete <id>  → 删除文档
- /stats        → 知识库统计
- /rebuild      → 重建索引
- /clear        → 清空对话历史
- /help         → 帮助
- /exit / quit  → 退出
"""
from __future__ import annotations

import sys
import threading
from pathlib import Path
from typing import List, Optional

from rich.console import Console, Group
from rich.panel import Panel
from rich.prompt import Prompt
from rich.table import Table
from rich.markdown import Markdown
from rich.columns import Columns
from rich.text import Text
from rich.align import Align
from rich.spinner import Spinner
from rich.live import Live
from prompt_toolkit import prompt as pt_prompt
from prompt_toolkit.completion import Completer, Completion, NestedCompleter
from prompt_toolkit.styles import Style as PtStyle

from config import settings
from core.storage import Storage
from core.ingestion.parser import parse, is_supported, SUPPORTED_EXTENSIONS, ParseError
from core.ingestion.chunker import chunk_document
from core.llm.client import get_llm, LLMError
from core.qa.chain import RAGChain
from core.search.bm25 import SearchResult
from core.ui.theme import get_theme, set_theme, list_themes
from core.pet.pet import Pet
from core.pet.storage import PetStorage
from core.pet.art import ArtLibrary
from core.pet.interact import PetInteractor, InteractError
from core.pet.tasks import DailyTaskManager
from core.pet.shop import Shop, ShopError
from core.pet.administrator import PetAdministrator, AnswerResult
from core.memory.store import MemoryStore
from core.memory.profile import ProfileManager
from core.memory.tasks import TaskManager
from core.memory.workflow import WorkflowTracker
from core.retrieval.hybrid import HybridRetriever
from core.retrieval.vector import VectorIndex
from core.retrieval.rerank import Reranker


console = Console()

# ============================================================
# Claude Code 风格界面元素
# ============================================================

# ASCII 艺术字 Logo（IMA）
ASCII_LOGO_LARGE = """
██╗  ██╗ █████╗ ██████╗ ██╗███╗   ██╗
██║  ██║██╔══██╗██╔══██╗██║████╗  ██║
███████║███████║██║  ██║██║██╔██╗ ██║
██╔══██║██╔══██║██║  ██║██║██║╚██╗██║
██║  ██║██║  ██║██████╔╝██║██║ ╚████║
╚═╝  ╚═╝╚═╝  ╚═╝╚═════╝ ╚═╝╚═╝  ╚═══╝
"""


def _render_welcome_panel(stats: dict, llm_available: bool, pet: Optional["Pet"] = None) -> None:
    """渲染欢迎面板：固定双栏布局 + 主题配色，底部边框对齐。"""
    t = get_theme()  # 当前主题

    # ---- 顶部 Logo 面板 ----
    logo_str = ASCII_LOGO_LARGE
    subtitle = Text("✨ 个人知识库 · 智能问答终端 v4.0", style=t.colors["secondary"])
    logo_text = Text(logo_str, style=t.colors["text_title"])
    logo_panel = Panel(
        Align.center(Group(logo_text, Text(""), subtitle)),
        border_style=t.colors["border_logo"],
        padding=(0, 2),
    )
    console.print(logo_panel)

    # ---- 左栏：知识库状态 ----
    status_line = "[green]✓ 在线[/green]" if llm_available else "[red]✗ 未配置[/red]"
    pet_line1, pet_line2 = _render_pet_compact(pet) if pet else _render_pet_empty_compact()
    left_content = Group(
        pet_line1,
        pet_line2,
        Text("─" * 30, style="dim"),
        Text("📊 知识库状态", style=f"bold {t.colors['secondary']}"),
        Text(""),
        Text.from_markup(f"  文档总数   [{t.colors['secondary']}]{stats['documents']}[/{t.colors['secondary']}]"),
        Text.from_markup(f"  分块总数   [{t.colors['secondary']}]{stats['chunks']}[/{t.colors['secondary']}]"),
        Text.from_markup(f"  总 Tokens  [{t.colors['secondary']}]{stats['total_tokens']:,}[/{t.colors['secondary']}]"),
        Text.from_markup(f"  原文件大小 [{t.colors['secondary']}]{stats['total_size_mb']} MB[/{t.colors['secondary']}]"),
        Text(""),
        Text.from_markup(f"  LLM 状态   {status_line}"),
        Text.from_markup(f"  模型       [dim]{settings.llm_model}[/dim]"),
        Text(""),
        Text.from_markup(f"  当前主题   [{t.colors['primary']}]{t.label}[/{t.colors['primary']}] [dim](/theme 切换)[/dim]"),
    )

    # ---- 右栏：使用提示 ----
    tips_lines = [
        Text("  直接输入问题    AI 问答（多轮对话）", style="white"),
        Text("  输入 /          弹出命令列表", style="white"),
        Text("  /search <词>    BM25 搜索", style="white"),
        Text("  /ingest <路径>  入库文件", style="white"),
        Text("  /analyze <路径> 数据分析", style="white"),
        Text("  /read <id>      智能阅读", style="white"),
        Text("  /compare A B    智能对比", style="white"),
        Text("  /graph stats    知识图谱", style="white"),
        Text("  /theme          切换主题", style="white"),
        Text("  /exit           退出", style="white"),
    ]
    right_content = Group(
        Text("🎯 快速开始", style=f"bold {t.colors['primary']}"),
        Text(""),
        *tips_lines,
    )

    # ---- 先测量左侧面板在半宽下的高度，让两边底部对齐 ----
    target_width = max(30, (console.width - 1) // 2)
    measure_console = Console(
        force_terminal=True,
        width=target_width,
        height=console.height,
        color_system=console.color_system,
    )
    tmp_left_panel = Panel(
        left_content,
        border_style=t.colors["border_welcome"],
        title=f"[bold {t.colors['secondary']}]Welcome[/bold {t.colors['secondary']}]",
        title_align="left",
        padding=(1, 2),
    )
    with measure_console.capture() as capture:
        measure_console.print(tmp_left_panel)
    panel_height = len(capture.get().splitlines())

    # ---- 使用相同高度构建两个面板 ----
    left_panel = Panel(
        left_content,
        border_style=t.colors["border_welcome"],
        title=f"[bold {t.colors['secondary']}]Welcome[/bold {t.colors['secondary']}]",
        title_align="left",
        padding=(1, 2),
        height=panel_height,
    )
    right_panel = Panel(
        right_content,
        border_style=t.colors["border_tips"],
        title=f"[bold {t.colors['primary']}]Tips for getting started[/bold {t.colors['primary']}]",
        title_align="left",
        padding=(1, 2),
        height=panel_height,
    )

    # ---- 固定左右分栏 ----
    grid = Table.grid(expand=True, padding=(0, 1))
    grid.add_column(ratio=1)
    grid.add_column(ratio=1)
    grid.add_row(left_panel, right_panel)
    console.print(grid)
    console.print()


def _render_pet_compact(pet: "Pet") -> tuple:
    """渲染宠物紧凑横版（2 行）。返回 (line1, line2)。"""
    branch_label = {"scholar": "学者", "warrior": "战士", "artisan": "工匠"}.get(pet.branch, "未分系")
    color = {"scholar": "cyan", "warrior": "red", "artisan": "yellow"}.get(pet.branch, "white")
    # 单行 Emoji 头像（按系别）
    avatar = {"scholar": "🦉", "warrior": "🐺", "artisan": "🦡"}.get(pet.branch, "🐣")
    line1 = Text.from_markup(
        f"  [{color}]{avatar}[/{color}] [bold magenta]{pet.name}[/bold magenta] "
        f"[dim]Lv{pet.level} {branch_label}[/dim]"
    )
    line2 = Text.from_markup(
        f"  ❤️{pet.hunger} ⚡{pet.energy} 😊{pet.mood} 🛁{pet.cleanliness} "
        f"✨{pet.exp}/{pet.exp_needed()}"
        + (f" [dim]→{pet.exp_remaining()}[/dim]" if pet.level < 10 else " [dim](满级)[/dim]")
    )
    return line1, line2


def _render_pet_empty_compact() -> tuple:
    """未领养宠物的占位（2 行）。"""
    return (
        Text.from_markup("  🐣 [bold magenta]虚拟宠物[/bold magenta] [dim]/pet adopt 领养[/dim]"),
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


# 帮助文本
HELP_TEXT = """
[bold green]🚀 快速上手（3 个命令够用）[/bold green]
- [cyan]直接输入文本[/cyan]        AI 问答（自动检索知识库，多轮对话）
- [cyan]/smart <描述>[/cyan]       智能路由（AI 自动选功能，最省心）
- [cyan]/help[/cyan]               查看所有命令

[bold]核心命令（高频）[/bold]
- [cyan]/search <关键词>[/cyan] [dim](/s)[/dim]    BM25 搜索（--tag 标签 --limit N）
- [cyan]/list[/cyan] [dim](/l)[/dim]               列出所有文档
- [cyan]/show <id>[/cyan] [dim](/sh)[/dim]         查看文档详情（id 可简写前 8 位）
- [cyan]/stats[/cyan] [dim](/st)[/dim]             知识库统计
- [cyan]/ingest <路径>[/cyan] [dim](/i)[/dim]      入库文件或目录
- [cyan]/note <文字>[/cyan]            文本直入库（不用先存文件）
- [cyan]/clip[/cyan]                   剪贴板入库（截图/文字/URL 自动识别）
- [cyan]/url <网址>[/cyan]             网页入库（自动提取正文）
- [cyan]/tag [名称][/cyan] [dim](/t)[/dim]         不带参数看所有标签，带参数按标签筛选
- [cyan]/clear[/cyan]                 清空对话历史（开新话题前用）
- [cyan]/help[/cyan] [dim](/h)[/dim]               显示此帮助
- [cyan]/exit[/cyan] [dim](/q)[/dim]               退出

[bold]智能功能（中频）[/bold]
- [cyan]/smart <描述>[/cyan]         [bold]智能路由[/bold]（说人话，AI 自动选功能）
  例: [dim]/smart 总结 862e0973[/dim] / [dim]/smart 对比 862e 和 02fd[/dim] / [dim]/smart 分析数据.xlsx[/dim]
- [cyan]/analyze <路径>[/cyan]       数据表分析（Excel/CSV/TSV/JSON）
- [cyan]/read <id>[/cyan] [dim](/r)[/dim]          智能阅读（逐段 AI 解读，n/p/数字/q 控制）
- [cyan]/compare A B[/cyan]          智能对比（A/B 可以是文档 ID 或文件路径）
- [cyan]/report <id>[/cyan]          生成文档分析报告（Markdown）
- [cyan]/agent <任务>[/cyan] [dim](/a)[/dim]       Agent 模式（LLM 自主调工具完成复杂任务）

[bold]管理命令（低频）[/bold]
- [cyan]/delete <id>[/cyan]          删除文档
- [cyan]/reparse <id|路径>[/cyan]   重新解析文档（OCR 失败/内容更新后重试）
- [cyan]/rebuild [--vector][/cyan]  重建 BM25 索引（--vector 同时重建向量索引并热更新）
- [cyan]/retag [-f] [-d ID][/cyan]   重新生成/补全文档标签（-f 强制全部）
- [cyan]/watch <目录>[/cyan]         监控文件夹自动入库（Ctrl+C 退出）
- [cyan]/web [-p 端口][/cyan]        启动 Web 后台（FastAPI + 单页 HTML）
- [cyan]/session <子命令>[/cyan]     会话管理（save/load/list/export）
  例: [dim]/session save[/dim] / [dim]/session list[/dim] / [dim]/session load xxx[/dim]
- [cyan]/graph <子命令>[/cyan]       知识图谱（build/stats/neighbors/export/clear）
- [cyan]/theme [名称][/cyan]         切换主题（claude/mimo/minimal）
- [cyan]/sync <目录>[/cyan]          增量同步目录（自动检测新增/修改/删除）
- [cyan]/health[/cyan]               知识库数据质量报告
- [cyan]/dedup[/cyan]                扫描近似重复 chunk
- [cyan]/draw <id>[/cyan] [dim](--style 风格)[/dim]  基于文档生成配图
- [cyan]/daily[/cyan] [dim](--topics 主题1,主题2)[/dim]   生成每日知识卡片
- [cyan]/pic <描述>[/cyan]                 直接文生图
[bold]管道用法（链式调用）[/bold]
- [cyan]/search 骨灰 | ask 这些政策有什么差异[/cyan]   搜索结果喂给 AI 分析
- [cyan]/list | ask 按类型分类统计[/cyan]              文档列表喂给 AI
- [cyan]/show 862e0973 | ask 总结要点[/cyan]          文档详情喂给 AI
- [cyan]/stats | ask 数据分析建议[/cyan]              知识库统计喂给 AI
- [cyan]骨灰安置政策 | ask 翻译成英文[/cyan]            纯文本作为上下文
- 多段管道：[cyan]/list | ask 分类 | ask 画表[/cyan]

[bold]使用技巧[/bold]
- 不确定用什么命令 → [cyan]/smart 描述[/cyan]，让 AI 帮你选
- 切换话题前输入 [cyan]/clear[/cyan] 清空历史
- AI 回答带 [1][2] 编号，对应 /stats 后的引用来源
- 命令可以简写：[cyan]/s 骨灰[/cyan] = [cyan]/search 骨灰[/cyan]
- 复杂任务用 [cyan]/agent[/cyan]，简单总结用 [cyan]/smart[/cyan]
- 输入 [cyan]/memory[/cyan] 回车显示内联帮助，直接输入 [cyan]/memory clear[/cyan] 或 [cyan]/m c[/cyan] 执行
"""


# ============================================================
# 命令自动补全（输入 / 自动弹出所有命令供选择）
# ============================================================

# 命令列表：(命令, 描述)
COMMAND_LIST = [
    # 核心命令 + 别名
    ("/smart",   "智能路由（说人话，AI 自动选功能）"),
    ("/search",  "BM25 搜索（--tag 标签 --limit N）"),
    ("/s",       "= /search（别名）"),
    ("/list",    "列出所有文档"),
    ("/l",       "= /list（别名）"),
    ("/show",    "查看文档详情"),
    ("/sh",      "= /show（别名）"),
    ("/stats",   "知识库统计"),
    ("/st",      "= /stats（别名）"),
    ("/ingest",  "入库文件或目录"),
    ("/i",       "= /ingest（别名）"),
    ("/note",    "文本直入库（/note 一段文字）"),
    ("/clip",    "剪贴板入库（截图/文字/URL 自动识别）"),
    ("/url",     "网页入库（/url https://...）"),
    ("/tag",     "查看所有标签 / 按标签筛选"),
    ("/t",       "= /tag（别名）"),
    ("/clear",   "清空对话历史"),
    # 智能功能
    ("/analyze", "数据表智能分析（Excel/CSV/TSV/JSON）"),
    ("/read",    "智能阅读模式（逐段解读 + 提问）"),
    ("/r",       "= /read（别名）"),
    ("/compare", "智能对比两个文档/文件"),
    ("/report",  "生成文档分析报告（Markdown）"),
    ("/agent",   "Agent 模式（LLM 自主调工具完成复杂任务）"),
    ("/a",       "= /agent（别名）"),
    # 管理命令
    ("/delete",  "删除文档"),
    ("/reparse", "重新解析文档（OCR 失败/内容更新后重试）"),
    ("/rebuild", "重建 BM25 索引（--vector 同时重建向量索引）"),
    ("/retag",   "重新生成/补全文档标签（-f 强制 -d ID）"),
    ("/watch",   "监控文件夹自动入库（持续/Ctrl+C 退出）"),
    ("/web",     "启动 Web 界面（-p 端口）"),
    ("/session", "会话管理（save/load/list/export）"),
    ("/graph",   "知识图谱（build/stats/neighbors/export/clear）"),
    ("/theme",   "切换主题（claude/mimo/minimal）"),
    # 同步与维护
    ("/sync",    "增量同步目录（自动检测新增/修改/删除）"),
    ("/health",  "知识库数据质量报告"),
    ("/dedup",   "扫描近似重复 chunk"),
    ("/draw",    "基于文档生成配图（--style 风格）"),
    ("/daily",   "生成每日知识卡片（--topics 主题）"),
    ("/pic",     "直接文生图（/pic <描述>）"),
    # 帮助/退出
    ("/help",    "显示帮助"),
    ("/h",       "= /help（别名）"),
    ("/pet",     "虚拟宠物（adopt/feed/play/train/wash/sleep/shop/tasks/style）"),
    ("/memory",  "记忆管理（show/clear/add/tasks）"),
    ("/exit",    "退出"),
    ("/q",       "= /quit（别名）"),
    ("/quit",    "退出"),
]

# NestedCompleter：输入命令+空格后自动弹出子命令补全
# 格式：命令 → 子命令 → 选项（多级嵌套）
_SUB_MENU_NESTED = {
    '/memory': {
        'clear': None,
        'format': {'table': None, 'list': None, 'prose': None, 'auto': None, 'none': None},
        'style': {'scholar': None, 'warrior': None, 'artisan': None, 'auto': None},
        'topic': {'add': None, 'remove': None, 'clear': None},
        'region': {'add': None, 'remove': None, 'clear': None},
        'task': {'add': None, 'done': None, 'cancel': None, 'reopen': None, 'start': None, 'delete': None},
        'tasks': None,
        'workflow': {'clear': None, 'suggest': None},
    },
    '/pet': {
        'feed': None, 'play': None, 'train': None, 'wash': None, 'sleep': None,
        'tasks': None, 'shop': None, 'bag': None, 'reset': None,
    },
    '/graph': {
        'stats': None, 'build': None, 'neighbors': None, 'export': None, 'clear': None,
    },
    '/sync': {'reset': None},
    '/session': {'save': None, 'load': None, 'list': None, 'export': None, 'delete': None},
    '/tag': {'rename': None, 'merge': None},
    '/dedup': {'delete': None},
    '/health': {'list': None},
}

# 子命令中文描述（path → 描述，path 是命令+各层级子命令组成的 tuple）
_SUB_MENU_DESC = {
    ('/memory', 'clear'): '清空所有记忆',
    ('/memory', 'format'): '设置输出格式',
    ('/memory', 'format', 'table'): '表格',
    ('/memory', 'format', 'list'): '列表',
    ('/memory', 'format', 'prose'): '散文',
    ('/memory', 'format', 'auto'): '自动',
    ('/memory', 'format', 'none'): '无',
    ('/memory', 'style'): '切换人格风格',
    ('/memory', 'style', 'scholar'): '学者风格',
    ('/memory', 'style', 'warrior'): '战士风格',
    ('/memory', 'style', 'artisan'): '工匠风格',
    ('/memory', 'style', 'auto'): '自动',
    ('/memory', 'topic'): '管理主题偏好',
    ('/memory', 'topic', 'add'): '添加',
    ('/memory', 'topic', 'remove'): '移除',
    ('/memory', 'topic', 'clear'): '清空',
    ('/memory', 'region'): '管理地区偏好',
    ('/memory', 'region', 'add'): '添加',
    ('/memory', 'region', 'remove'): '移除',
    ('/memory', 'region', 'clear'): '清空',
    ('/memory', 'task'): '管理任务',
    ('/memory', 'task', 'add'): '添加',
    ('/memory', 'task', 'done'): '完成',
    ('/memory', 'task', 'cancel'): '取消',
    ('/memory', 'task', 'reopen'): '重新打开',
    ('/memory', 'task', 'start'): '开始',
    ('/memory', 'task', 'delete'): '删除',
    ('/memory', 'tasks'): '查看任务列表',
    ('/memory', 'workflow'): '清空/推荐工作流',
    ('/memory', 'workflow', 'clear'): '清空',
    ('/memory', 'workflow', 'suggest'): '推荐工作流',
    ('/pet', 'feed'): '喂食',
    ('/pet', 'play'): '玩耍',
    ('/pet', 'train'): '训练',
    ('/pet', 'wash'): '洗澡',
    ('/pet', 'sleep'): '睡觉',
    ('/pet', 'tasks'): '查看任务',
    ('/pet', 'shop'): '商店',
    ('/pet', 'bag'): '背包',
    ('/pet', 'reset'): '重置宠物',
    ('/graph', 'stats'): '统计信息',
    ('/graph', 'build'): '构建图谱',
    ('/graph', 'neighbors'): '查询邻居',
    ('/graph', 'export'): '导出 HTML',
    ('/graph', 'clear'): '清空图谱',
    ('/sync', 'reset'): '清空追踪记录',
    ('/session', 'save'): '保存会话',
    ('/session', 'load'): '加载会话',
    ('/session', 'list'): '会话列表',
    ('/session', 'export'): '导出会话',
    ('/session', 'delete'): '删除会话',
    ('/tag', 'rename'): '重命名标签',
    ('/tag', 'merge'): '合并标签',
    ('/dedup', 'delete'): '删除近似重复',
    ('/health', 'list'): '列出质量问题',
}

# 别名 → 完整命令
_CMD_ALIASES = {
    '/s': '/search', '/l': '/list', '/sh': '/show', '/st': '/stats',
    '/i': '/ingest', '/r': '/read', '/a': '/agent', '/t': '/tag',
    '/m': '/memory', '/g': '/graph', '/p': '/pet', '/h': '/help',
    '/q': '/quit',
}


class CommandCompleter(Completer):
    """命令补全器：支持中文描述 + 子命令嵌套。"""

    def __init__(self, commands, sub_menus, sub_desc):
        self._cmd_meta = dict(commands)       # 命令 → 中文描述
        self._sub_menus = sub_menus           # 完整命令 → 子命令字典
        self._sub_desc = sub_desc           # tuple path → 子命令描述

    def _resolve(self, cmd: str) -> str:
        """解析别名到完整命令名。"""
        return _CMD_ALIASES.get(cmd, cmd)

    def get_completions(self, document, complete_event):
        text = document.text_before_cursor.lstrip()
        parts = text.split() if text else []
        trailing = text.endswith(" ")              # 是否已按空格 → 进入下一级

        if not parts:
            # 空输入 → 显示所有命令
            for cmd, meta in sorted(self._cmd_meta.items()):
                yield Completion(cmd, start_position=0, display_meta=meta)
            return

        first = parts[0]

        # 仅一个词 且 未按空格 → 正在输入命令名
        if len(parts) == 1 and not trailing:
            for cmd, meta in sorted(self._cmd_meta.items()):
                if cmd.startswith(first):
                    yield Completion(cmd, start_position=-len(first), display_meta=meta)
            return

        # ——— 走到这里说明需要子命令 / 多级嵌套 ———

        resolved = self._resolve(first)
        menu = self._sub_menus.get(resolved)
        if menu is None:
            return

        # 把 parts[1:] 作为导航路径，trailing 表示最后一级也已完成
        nav = list(parts[1:])
        if trailing:
            nav.append("")                          # 空字符串 → 展示当前级全部选项

        # 逐级深入子菜单；path 用于描述查找
        path = [resolved]

        for i, seg in enumerate(nav):
            if isinstance(menu, dict) and seg in menu:
                # 该级已命中 → 进入下一级
                menu = menu[seg]
                path.append(seg)
            elif isinstance(menu, dict):
                # 未命中(或空串) → 在当前级做前缀匹配并显示描述
                for sub_cmd in sorted(menu.keys()):
                    if sub_cmd.startswith(seg):
                        desc_path = tuple(path + [sub_cmd])
                        desc = self._sub_desc.get(desc_path)
                        yield Completion(
                            sub_cmd, start_position=-len(seg),
                            display_meta=desc if desc else None,
                        )
                return
            else:
                return


def _build_nested_completer() -> CommandCompleter:
    """构建命令补全器，顶层命令带中文描述，子命令按嵌套字典补全。"""
    commands = list(COMMAND_LIST)
    # 别名命令也纳入补全
    commands.append(('/m', '/memory（别名）'))
    commands.append(('/g', '/graph（别名）'))
    commands.append(('/p', '/pet（别名）'))
    commands.append(('/h', '/help（别名）'))
    commands.append(('/q', '/quit（别名）'))
    return CommandCompleter(commands, _SUB_MENU_NESTED, _SUB_MENU_DESC)

# 输入提示符样式（橙色粗体 > Claude Code 风格）
_INPUT_STYLE = PtStyle.from_dict({
    "prompt": "bold fg:ansiyellow",
    "completion-menu.completion": "bg:ansiblack fg:ansiwhite",
    "completion-menu.completion.current": "bg:ansiyellow fg:ansiblack bold",
    "completion-menu.meta.completion": "bg:ansiblue fg:ansiwhite",
    "completion-menu.meta.completion.current": "bg:ansicyan fg:ansiblack bold",
    "completion-menu.progress-button": "bg:ansiblue",
    "completion-menu.progress-bar": "bg:ansiblue",
})


def _read_input() -> str:
    """读取用户输入，输入 / 时自动弹出命令补全菜单。

    - 橙色 > 提示符（Claude Code 风格）
    - 输入 / 后立即显示所有命令列表 + 描述
    - 用方向键 ↑↓ 选择，Tab/Enter 确认
    - Ctrl+D / Ctrl+C 退出
    """
    try:
        text = pt_prompt(
            [("class:prompt", "\n> ")],
            completer=_build_nested_completer(),
            complete_while_typing=True,
            style=_INPUT_STYLE,
        )
        return text.strip()
    except (EOFError, KeyboardInterrupt):
        raise


class REPL:
    """交互式 REPL。"""

    def __init__(self) -> None:
        self.storage = Storage()
        self.rag: Optional[RAGChain] = None
        # 对话历史（多轮）
        self.history: List[dict] = []
        # LLM 是否可用
        self.llm_available: bool = settings.has_llm()
        # 运行中
        self.running: bool = True
        # Web 后台服务（后台线程运行的 uvicorn Server）
        self._web_server = None
        self._web_thread: Optional[threading.Thread] = None
        # 当前数据分析结果（用于 /analyze 后追问）
        self.current_analysis = None
        # 智能阅读状态（用于 /read 模式）
        self.reader = None
        # 虚拟宠物
        self.pet: Optional[Pet] = None
        self.pet_storage = PetStorage()
        self.pet_interactor = PetInteractor()
        self.task_manager = DailyTaskManager()
        self.shop = Shop()
        self.art_lib = ArtLibrary()
        # 加载宠物 + 应用衰减
        self.pet = self.pet_storage.load()
        if self.pet is not None:
            self.pet.apply_decay()
            self.pet_storage.save(self.pet)

        # 初始化宠物管理员（编排检索 + 记忆 + 人格 + LLM）
        # 失败时静默降级为普通问答，不影响 REPL 主流程
        self.administrator: Optional[PetAdministrator] = None
        self.memory_store: Optional[MemoryStore] = None
        self.workflow_tracker: Optional[WorkflowTracker] = None
        if self.pet:
            try:
                self.memory_store = MemoryStore()
                self.workflow_tracker = WorkflowTracker(self.memory_store)
                vector_index = VectorIndex()
                hybrid = HybridRetriever(
                    bm25_index=self.storage.bm25, vector_index=vector_index,
                )
                llm = get_llm() if settings.has_llm() else None
                reranker = Reranker(llm) if llm else None
                if llm and reranker:
                    self.administrator = PetAdministrator(
                        pet=self.pet,
                        storage=self.storage,
                        memory_store=self.memory_store,
                        hybrid_retriever=hybrid,
                        reranker=reranker,
                        llm=llm,
                    )
            except Exception as e:
                console.print(f"[dim]宠物管理员初始化失败，降级为普通问答: {e}[/dim]")

    # ---- 启动 ----

    def run(self) -> None:
        """启动 REPL 主循环。"""
        # 清屏 + 渲染欢迎面板
        console.clear()
        stats = self.storage.stats()
        _render_welcome_panel(stats, self.llm_available, pet=self.pet)

        while self.running:
            try:
                user_input = _read_input()
            except (EOFError, KeyboardInterrupt):
                console.print("\n[dim]再见 👋[/dim]")
                break

            if not user_input:
                continue

            # 管道：输入含 " | " 时按管道处理（如 /search 骨灰 | ask 差异）
            if " | " in user_input:
                self._handle_pipe(user_input)
            # 命令
            elif user_input.startswith("/"):
                self._handle_command(user_input)
            elif self.reader is not None:
                # 阅读模式特殊处理
                self._handle_read_input(user_input)
            else:
                # 普通对话
                self._handle_chat(user_input)

    def _handle_read_input(self, user_input: str) -> None:
        """阅读模式下的输入处理。"""
        u = user_input.lower().strip()
        if u in ("n", "next", "下一段", "下一"):
            chunk = self.reader.next()
            if chunk is None:
                console.print("[yellow]已到最后一段[/yellow]")
            else:
                self._render_read_chunk()
        elif u in ("p", "prev", "上一段", "上一"):
            chunk = self.reader.prev()
            if chunk is None:
                console.print("[yellow]已到第一段[/yellow]")
            else:
                self._render_read_chunk()
        elif u in ("i", "interpret", "解读"):
            with console.status("[bold yellow]AI 解读中...[/bold yellow]", spinner="dots"):
                interp = self.reader.interpret()
            console.print(Panel(
                Text(interp),
                title="[bold cyan]💡 AI 解读[/bold cyan]",
                border_style="cyan",
                padding=(1, 2),
            ))
        elif u in ("q", "quit", "exit", "退出"):
            self.reader.close()
            self.reader = None
            console.print("[green]✓ 已退出阅读模式[/green]\n")
        elif u.isdigit():
            idx = int(u) - 1  # 用户输入 1-based
            chunk = self.reader.goto(idx)
            if chunk is None:
                console.print(f"[red]段号超出范围（1-{self.reader.state.total_chunks}）[/red]")
            else:
                self._render_read_chunk()
        else:
            # 针对当前段提问
            with console.status("[bold yellow]AI 思考中...[/bold yellow]", spinner="dots"):
                answer = self.reader.ask(user_input)
            console.print(Panel(
                Text(answer),
                title="[bold cyan]📖 阅读助手[/bold cyan]",
                border_style="cyan",
                padding=(1, 2),
            ))

    # ---- 命令处理 ----

    def _handle_pipe(self, user_input: str) -> None:
        """REPL 内管道：支持 "命令1 | 命令2" 链式调用。

        示例:
            /search 骨灰 | ask 这些政策有什么差异
            /list | ask 按类型分类统计
            /show 862e0973 | ask 总结要点
            骨灰安置政策 | ask 翻译成英文

        规则:
            - 上游命令的输出作为下游 ask 的上下文
            - 下游只能是 ask（普通问答）
            - 上游可以是 /search /list /show /stats /tags，或纯文本
        """
        # 按 " | " 分割
        segments = [s.strip() for s in user_input.split(" | ") if s.strip()]
        if len(segments) < 2:
            console.print("[yellow]管道用法: 命令1 | 命令2  （至少两段）[/yellow]")
            console.print("[dim]示例: /search 骨灰 | ask 总结差异[/dim]")
            return

        # 逐段执行，上游输出传给下游
        context = ""
        for i, seg in enumerate(segments):
            is_last = (i == len(segments) - 1)

            if seg.startswith("/"):
                # /xxx 命令
                parts = seg.split(maxsplit=1)
                cmd = parts[0].lower()
                arg = parts[1].strip() if len(parts) > 1 else ""

                # 上游命令：捕获输出为文本（不打印 rich 格式）
                if cmd == "/search":
                    context = self._pipe_search(arg)
                elif cmd == "/list":
                    context = self._pipe_list()
                elif cmd == "/show":
                    context = self._pipe_show(arg)
                elif cmd == "/stats":
                    context = self._pipe_stats()
                elif cmd == "/tags":
                    context = self._pipe_tags()
                else:
                    console.print(f"[red]管道不支持命令: {cmd}[/red]")
                    console.print("[dim]支持的命令: /search /list /show /stats /tags | ask[/dim]")
                    return

                if not is_last:
                    console.print(f"[dim]✓ 上游输出 ({len(context)} 字符)，传给下游...[/dim]\n")

            elif seg.lower().startswith("ask "):
                # ask 下游：带 context 调 LLM
                question = seg[4:].strip()
                if not question:
                    console.print("[red]ask 后面要跟问题[/red]")
                    return
                if not context:
                    context = "(无上游内容)"
                self._pipe_ask(question, context)

            else:
                # 纯文本当作 context
                context = seg
                if not is_last:
                    console.print(f"[dim]✓ 文本 ({len(context)} 字符)作为上下文[/dim]\n")

    def _pipe_search(self, query: str) -> str:
        """管道版搜索：返回纯文本结果。"""
        if not query:
            return "[错误] 搜索关键词为空"
        results = self.storage.bm25_search(query, top_k=10)
        if not results:
            return f"未找到与 '{query}' 相关的内容"
        lines = [f"搜索 '{query}' 找到 {len(results)} 条结果：\n"]
        for i, r in enumerate(results, 1):
            lines.append(
                f"[{i}] {r.doc_title} (相关度 {r.score:.2f})\n"
                f"    文档ID: {r.doc_id[:8]}\n"
                f"    内容: {r.content[:300]}\n"
            )
        return "\n".join(lines)

    def _pipe_list(self) -> str:
        """管道版列表：返回纯文本。"""
        docs = self.storage.list_documents(limit=100)
        if not docs:
            return "知识库为空"
        lines = [f"共 {len(docs)} 个文档：\n"]
        for d in docs:
            tags = "、".join(d.tags) if d.tags else "无"
            lines.append(
                f"- [{d.id[:8]}] {d.title}  "
                f"类型:{d.file_type} 标签:{tags} "
                f"分块:{d.chunk_count} tokens:{d.total_tokens}"
            )
        return "\n".join(lines)

    def _pipe_show(self, doc_id: str) -> str:
        """管道版文档详情：返回纯文本。"""
        doc_id = doc_id.strip()
        if len(doc_id) < 32:
            docs = self.storage.list_documents(limit=10000)
            matched = [d for d in docs if d.id.startswith(doc_id)]
            if not matched:
                return f"未找到文档: {doc_id}"
            doc_id = matched[0].id
        doc = self.storage.get_document(doc_id)
        if doc is None:
            return f"未找到文档: {doc_id}"
        chunks = self.storage.get_chunks(doc_id)
        preview = "\n\n".join(c.content[:500] for c in chunks[:5])
        return (
            f"文档: {doc.title}\n"
            f"ID: {doc.id}\n类型: {doc.file_type}\n"
            f"标签: {', '.join(doc.tags) if doc.tags else '无'}\n"
            f"分块: {doc.chunk_count} / Tokens: {doc.total_tokens}\n\n"
            f"前 5 段内容：\n{preview}"
        )

    def _pipe_stats(self) -> str:
        """管道版统计：返回纯文本。"""
        s = self.storage.stats()
        docs = self.storage.list_documents(limit=10000)
        type_count: dict = {}
        for d in docs:
            type_count[d.file_type] = type_count.get(d.file_type, 0) + 1
        type_str = ", ".join(f"{t}:{n}" for t, n in sorted(type_count.items()))
        return (
            f"知识库统计：\n"
            f"- 文档总数: {s['documents']}\n"
            f"- 分块总数: {s['chunks']}\n"
            f"- 总 Tokens: {s['total_tokens']}\n"
            f"- 原文件大小: {s['total_size_mb']} MB\n"
            f"- 类型分布: {type_str}"
        )

    def _pipe_tags(self) -> str:
        """管道版标签：返回纯文本。"""
        docs = self.storage.list_documents(limit=10000)
        tag_count: dict = {}
        for d in docs:
            for t in (d.tags or []):
                tag_count[t] = tag_count.get(t, 0) + 1
        if not tag_count:
            return "无标签"
        lines = [f"共 {len(tag_count)} 个标签：\n"]
        for t, n in sorted(tag_count.items(), key=lambda x: -x[1]):
            lines.append(f"- {t}: {n} 个文档")
        return "\n".join(lines)

    def _pipe_ask(self, question: str, context: str) -> None:
        """管道下游 ask：带 context 调 LLM，流式输出。"""
        if not self.llm_available:
            console.print("[red]LLM 未配置，无法问答[/red]")
            return
        try:
            llm = get_llm()
        except LLMError as e:
            console.print(f"[red]LLM 初始化失败:[/red] {e}")
            return

        prompt = f"""基于以下上下文回答问题。

[上下文]
{context}

[问题]
{question}

要求：基于上下文回答，不要编造。如果上下文不足以回答，明确说明。"""

        messages = [
            {"role": "system", "content": "你是知识库分析助手，基于提供的上下文回答问题。"},
            {"role": "user", "content": prompt},
        ]

        console.print("[bold yellow]⏺[/bold yellow] [dim]基于管道上下文回答...[/dim]")
        full: list[str] = []
        first_token = True
        try:
            for token in llm.chat_stream(messages, temperature=0.3):
                if first_token:
                    sys.stdout.write("\033[1A\r\033[K")
                    sys.stdout.flush()
                    console.print("[bold yellow]⏺[/bold yellow] [bold cyan]AI[/bold cyan]", end="")
                    first_token = False
                sys.stdout.write(token)
                sys.stdout.flush()
                full.append(token)
            if first_token:
                sys.stdout.write("\033[1A\r\033[K")
                sys.stdout.flush()
                console.print("[bold yellow]⏺[/bold yellow] [dim]（无响应）[/dim]")
            console.print()
        except LLMError as e:
            err_msg = str(e).replace("[", "\\[")
            console.print(f"[red]问答失败:[/red] {err_msg}")

    # 命令别名：短名 → 完整命令
    CMD_ALIASES = {
        "/s": "/search",
        "/l": "/list",
        "/sh": "/show",
        "/st": "/stats",
        "/t": "/tag",        # /t 不带参数显示所有标签，带参数筛选
        "/a": "/agent",
        "/r": "/read",
        "/i": "/ingest",
        "/h": "/help",
        "/q": "/quit",
        "/se": "/session",   # /se 作为 /session 别名（/s 已被 /search 占用）
        # 会话管理快捷别名（/session 的子命令快捷方式）
        "/save": "/session_save",
        "/load": "/session_load",
        "/sessions": "/session_list",
        "/export": "/session_export",
        # 新增高频命令别名（覆盖后增功能）
        "/m": "/memory",     # 记忆管理
        "/g": "/graph",      # 知识图谱
        "/p": "/pet",        # 宠物系统
        "/sy": "/sync",      # 增量同步
        "/he": "/health",    # 健康检查
        "/dd": "/dedup",     # 去重
        "/rt": "/retag",     # 重新打标签
        "/rb": "/rebuild",   # 重建索引
        "/rp": "/reparse",   # 重新解析
        "/n": "/note",       # 文本直入库
        "/c": "/clip",       # 剪贴板入库
        "/u": "/url",        # 网页入库
        "/w": "/watch",      # 文件夹监控
        "/wb": "/web",       # 启动 Web
        "/an": "/analyze",   # 数据分析
        "/cm": "/compare",   # 对比
        "/sm": "/smart",     # 智能路由
        "/d": "/delete",     # 删除文档
        "/ss": "/stats",     # 统计的另一个别名
    }

    # 子命令菜单：主命令 → [(子命令参数, 描述), ...]
    # 第 1 项固定为空字符串（执行默认行为），其余为可用子命令
    # 占位符语法：
    #   <名称>           普通参数，提示 "请输入 名称:"
    #   <名称|a|b|c>     有固定选项，提示 "请输入 名称 (a/b/c):" 并验证输入
    SUBCOMMAND_MENU = {
        "/memory": [
            ("", "查看记忆概览"),
            ("clear", "清空所有记忆"),
            ("format <格式|table|list|prose|auto|none>", "设置格式偏好"),
            ("style <风格|auto|scholar|warrior|artisan>", "设置风格偏好"),
            ("topic add <主题>", "添加关注主题"),
            ("topic remove <主题>", "移除关注主题"),
            ("topic clear", "清空所有主题"),
            ("region add <地区>", "添加关注地区"),
            ("region clear", "清空所有地区"),
            ("task add <描述>", "添加任务"),
            ("tasks", "列出所有任务"),
        ],
        "/pet": [
            ("", "查看宠物状态"),
            ("feed", "喂食宠物"),
            ("play", "陪宠物玩耍"),
            ("train", "训练宠物"),
            ("wash", "给宠物洗澡"),
            ("sleep", "让宠物睡觉"),
            ("tasks", "查看每日任务"),
            ("shop", "查看商店"),
            ("bag", "查看背包"),
            ("reset", "重置宠物"),
        ],
        "/graph": [
            ("stats", "图谱统计"),
            ("build", "构建图谱 (--force 强制重建)"),
            ("neighbors <名称>", "查询节点邻居"),
            ("export", "导出 HTML 可视化"),
            ("clear", "清空图谱"),
        ],
        "/sync": [
            ("<目录路径>", "增量同步目录"),
            ("reset", "清空文件追踪记录"),
        ],
        "/session": [
            ("save [名称]", "保存当前会话"),
            ("load <名称>", "恢复已保存的会话"),
            ("list", "列出所有已保存会话"),
            ("export <名称>", "导出为 Markdown"),
            ("delete <名称>", "删除已保存的会话"),
        ],
        "/tag": [
            ("", "显示所有标签"),
            ("rename <旧> <新>", "重命名标签"),
            ("merge <源> <目标>", "合并标签"),
            ("<名称>", "按标签筛选文档"),
        ],
        "/dedup": [
            ("", "扫描近似重复内容"),
            ("delete <chunk_id>", "删除指定 chunk"),
        ],
        "/health": [
            ("", "生成健康报告"),
            ("list", "列出问题文档详情"),
        ],
    }

    def _show_subcommand_menu(self, cmd: str) -> Optional[str]:
        """显示子命令交互菜单，返回用户选择的子命令参数。

        使用 prompt_toolkit 的 radiolist_dialog 弹出选择菜单：
        - 方向键 ↑↓ 选择
        - Enter 确认
        - Esc/q 取消

        Returns:
            - None: 用户取消
            - "": 执行默认行为（无参数）
            - 非空字符串: 对应子命令参数
        """
        items = self.SUBCOMMAND_MENU.get(cmd)
        if not items:
            return ""

        # 构造 radiolist_dialog 的 values：[(value, description), ...]
        # value 是子命令模板（如 "format <格式|table|list|...>"），description 是显示文本
        values = []
        for sub, desc in items:
            if sub:
                sub_name = sub.split()[0]
                display = f"{sub_name}  —  {desc}"
            else:
                display = f"(默认)  —  {desc}"
            values.append((sub, display))

        try:
            from prompt_toolkit.shortcuts import radiolist_dialog
            selected = radiolist_dialog(
                title=f"{cmd} 子命令菜单",
                text="方向键选择，Enter 确认，Esc/q 取消",
                values=values,
            ).run()
        except Exception:
            return None

        if selected is None:
            return None

        if selected and "<" in selected and ">" in selected:
            return self._prompt_subcmd_params(cmd, selected)
        return selected

    def _prompt_subcmd_params(self, cmd: str, sub: str) -> Optional[str]:
        """为带占位符的子命令提示输入参数。

        占位符语法：
          <名称>           普通参数，自由输入
          <名称|a|b|c>     有固定选项，显示并验证

        Args:
            cmd: 主命令（如 /memory）
            sub: 子命令模板（如 "format <格式|table|list|...>"）

        Returns:
            填充后的完整子命令参数，或 None（用户取消）
        """
        import re
        placeholders = re.findall(r"<([^>]+)>", sub)
        if not placeholders:
            return sub

        prompt_parts = []
        for ph in placeholders:
            if "|" in ph:
                # 有固定选项：<名称|选项1|选项2|...>
                parts = ph.split("|")
                param_name = parts[0]
                choices_list = parts[1:]
                choices_display = "/".join(choices_list)
                valid = False
                while not valid:
                    try:
                        val = Prompt.ask(
                            f"请输入 {param_name} ({choices_display})",
                            default="",
                        ).strip()
                    except (EOFError, KeyboardInterrupt):
                        return None
                    if not val:
                        console.print("[dim]已取消[/dim]")
                        return None
                    if val in choices_list:
                        valid = True
                    else:
                        console.print(
                            f"[red]无效的 {param_name}: {val}[/red]  "
                            f"[dim]可选: {choices_display}[/dim]"
                        )
                prompt_parts.append(val)
            else:
                # 普通参数：自由输入
                try:
                    val = Prompt.ask(f"请输入 {ph}").strip()
                except (EOFError, KeyboardInterrupt):
                    return None
                if not val:
                    console.print("[dim]已取消[/dim]")
                    return None
                prompt_parts.append(val)

        # 替换占位符
        result = sub
        for ph, val in zip(placeholders, prompt_parts):
            result = re.sub(
                r"<" + re.escape(ph) + r">",
                val,
                result,
                count=1,
            )
        return result

    def _handle_command(self, user_input: str) -> None:
        """处理 / 开头的命令。"""
        parts = user_input.split(maxsplit=1)
        cmd = parts[0].lower()
        arg = parts[1].strip() if len(parts) > 1 else ""

        # 别名展开
        cmd = self.CMD_ALIASES.get(cmd, cmd)

        # 子命令菜单：主命令在菜单表中时，以下情况触发菜单
        # 1. 参数为纯数字（如 "/memory 3"）：作为菜单编号处理
        # 2. 空参数/有参数：直接交给命令处理器（显示帮助或执行）
        # _menu_skip 标志用于递归调用时跳过菜单（避免死循环）
        trigger_menu = False
        menu_numeric_arg = None
        if cmd in self.SUBCOMMAND_MENU and not getattr(self, '_menu_skip', False):
            if arg.isdigit():
                # 纯数字参数 → 菜单编号选择
                trigger_menu = True
                menu_numeric_arg = arg

        if trigger_menu:
            # 如果是纯数字参数，直接用数字选择（跳过菜单显示）
            if menu_numeric_arg is not None:
                items = self.SUBCOMMAND_MENU[cmd]
                idx = int(menu_numeric_arg) - 1
                if 0 <= idx < len(items):
                    sub, _ = items[idx]
                    selected = sub
                    # 如果选中的子命令有占位符，仍需提示输入参数
                    if "<" in sub and ">" in sub:
                        selected = self._prompt_subcmd_params(cmd, sub)
                        if selected is None:
                            return
                else:
                    console.print(f"[red]无效的编号: {menu_numeric_arg}[/red]  "
                                  f"[dim]可选 1-{len(items)}[/dim]")
                    return
            else:
                selected = self._show_subcommand_menu(cmd)
            if selected is None:
                return  # 用户取消
            # 设置跳过标志，递归调用时不再弹菜单
            self._menu_skip = True
            try:
                if selected:
                    self._handle_command(f"{cmd} {selected}")
                else:
                    # 空字符串表示执行默认行为（无参数）
                    self._handle_command(cmd)
            finally:
                self._menu_skip = False
            return

        if cmd in ("/exit", "/quit", "exit", "quit"):
            self.running = False
            console.print("[dim]再见 👋[/dim]")
        elif cmd == "/help":
            console.print(Panel(
                HELP_TEXT,
                border_style="yellow",
                title="[bold yellow]帮助[/bold yellow]",
                title_align="left",
                padding=(1, 2),
            ))
        elif cmd == "/search":
            self._cmd_search(arg)
        elif cmd == "/ingest":
            self._cmd_ingest(arg)
        elif cmd == "/note":
            self._cmd_note(arg)
        elif cmd == "/clip":
            self._cmd_clip()
        elif cmd == "/url":
            self._cmd_url(arg)
        elif cmd == "/analyze":
            self._cmd_analyze(arg)
        elif cmd == "/list":
            self._cmd_list()
        elif cmd == "/show":
            self._cmd_show(arg)
        elif cmd == "/tag":
            # /tag 不带参数 → 显示所有标签
            # /tag rename <old> <new> → 重命名标签
            # /tag merge <src> <dst> → 合并标签
            # /tag <名称> → 按标签筛选
            if arg:
                parts = arg.split(maxsplit=1)
                if parts[0].lower() == "rename" and len(parts) > 1:
                    self._cmd_tag_rename(parts[1])
                elif parts[0].lower() == "merge" and len(parts) > 1:
                    self._cmd_tag_merge(parts[1])
                else:
                    self._cmd_tag(arg)
            else:
                self._cmd_tags()
        elif cmd == "/delete":
            self._cmd_delete(arg)
        elif cmd == "/reparse":
            self._cmd_reparse(arg)
        elif cmd == "/edit":
            self._cmd_edit(arg)
        elif cmd == "/stats":
            self._cmd_stats()
        elif cmd == "/rebuild":
            self._cmd_rebuild(arg)
        elif cmd == "/retag":
            self._cmd_retag(arg)
        elif cmd == "/watch":
            self._cmd_watch(arg)
        elif cmd == "/web":
            self._cmd_web(arg)
        elif cmd == "/clear":
            self._cmd_clear()
        elif cmd == "/session":
            self._cmd_session(arg)
        elif cmd == "/session_save":
            self._cmd_save(arg)
        elif cmd == "/session_load":
            self._cmd_load(arg)
        elif cmd == "/session_list":
            self._cmd_sessions()
        elif cmd == "/session_export":
            self._cmd_export(arg)
        elif cmd == "/report":
            self._cmd_report(arg)
        elif cmd == "/read":
            self._cmd_read(arg)
        elif cmd == "/compare":
            self._cmd_compare(arg)
        elif cmd == "/agent":
            self._cmd_agent(arg)
        elif cmd == "/smart":
            self._cmd_smart(arg)
        elif cmd == "/graph":
            self._cmd_graph(arg)
        elif cmd == "/pet":
            self._cmd_pet(arg)
        elif cmd == "/memory":
            self._cmd_memory(arg)
        elif cmd == "/theme":
            self._cmd_theme(arg)
        elif cmd == "/sync":
            self._cmd_sync(arg)
        elif cmd == "/health":
            self._cmd_health(arg)
        elif cmd == "/dedup":
            self._cmd_dedup(arg)
        elif cmd == "/draw":
            self._cmd_draw(arg)
        elif cmd == "/daily":
            self._cmd_daily(arg)
        elif cmd == "/pic":
            self._cmd_pic(arg)
        else:
            console.print(f"[red]未知命令:[/red] {cmd}  [dim]输入 /help 查看所有命令[/dim]")
            return

        # 工作流模式记录 + 下一步推荐（仅在管理员模式启用时）
        self._record_workflow(cmd)

    # ---- 各命令实现 ----

    def _cmd_search(self, query: str) -> None:
        """BM25 搜索：/search <关键词> [--tag 标签] [--limit N]"""
        if not query:
            console.print("[yellow]用法: /search <关键词> [--tag 标签] [--limit N][/yellow]")
            console.print("[dim]示例: /search 骨灰 --tag 政策 --limit 5[/dim]")
            return

        # 解析可选参数 --tag / --limit
        import shlex
        try:
            tokens = shlex.split(query)
        except ValueError:
            tokens = query.split()

        tag_filter: Optional[str] = None
        limit = 10
        keyword_parts: list[str] = []
        i = 0
        while i < len(tokens):
            tok = tokens[i]
            if tok in ("--tag", "-t") and i + 1 < len(tokens):
                tag_filter = tokens[i + 1]
                i += 2
            elif tok in ("--limit", "-n") and i + 1 < len(tokens):
                try:
                    limit = int(tokens[i + 1])
                except ValueError:
                    console.print(f"[yellow]无效的 --limit 值: {tokens[i + 1]}[/yellow]")
                    return
                i += 2
            else:
                keyword_parts.append(tok)
                i += 1

        keyword = " ".join(keyword_parts)
        if not keyword:
            console.print("[yellow]请提供搜索关键词[/yellow]")
            return

        # 如有 tag 筛选，扩大候选数后过滤
        fetch_k = limit * 5 if tag_filter else limit
        results = self.storage.bm25_search(keyword, top_k=fetch_k)

        if tag_filter:
            tagged_docs = self.storage.list_documents_by_tag(tag_filter)
            allowed_ids = {d.id for d in tagged_docs}
            results = [r for r in results if r.doc_id in allowed_ids]
            if not results:
                console.print(
                    f"[yellow]未找到与 '{keyword}' 相关且带标签 '{tag_filter}' 的内容[/yellow]"
                )
                console.print(f"[dim]带此标签的文档共 {len(tagged_docs)} 个[/dim]")
                return
            results = results[:limit]
        else:
            if not results:
                console.print(f"[yellow]未找到与 '{keyword}' 相关的内容[/yellow]")
                return
            results = results[:limit]

        tag_hint = f" [dim]· 标签筛选: {tag_filter}[/dim]" if tag_filter else ""
        console.print(f"\n[bold]找到 {len(results)} 条相关结果[/bold] [dim](BM25)[/dim]{tag_hint}\n")
        for i, r in enumerate(results, 1):
            preview = r.content[:200].replace("\n", " ")
            console.print(
                f"[cyan]{i}.[/cyan] [green]({r.score:.2f})[/green] "
                f"[dim][{r.doc_title}][/dim]"
            )
            console.print(f"   {preview}{'...' if len(r.content) > 200 else ''}\n")

    def _cmd_ingest(self, path_str: str) -> None:
        """入库文件或目录。"""
        if not path_str:
            console.print("[yellow]用法: /ingest <文件或目录路径>[/yellow]")
            return
        # 支持 ~ 展开
        path = Path(path_str).expanduser().resolve()
        if not path.exists():
            console.print(f"[red]路径不存在:[/red] {path}")
            return

        files: list[Path] = []
        if path.is_file():
            files = [path]
        elif path.is_dir():
            for ext in SUPPORTED_EXTENSIONS:
                files.extend(path.rglob(f"*{ext}"))
            files = sorted(set(files))

        if not files:
            console.print("[yellow]未找到支持的文件[/yellow]")
            return

        console.print(f"\n[bold]入库 {len(files)} 个文件...[/bold]\n")
        success = 0
        for f in files:
            if self._ingest_one(f):
                success += 1
                # 宠物经验埋点：ingest 行为
                self._pet_gain_exp(30, "ingest")
        console.print(f"\n[bold]完成[/bold] · 成功 {success} / 共 {len(files)}\n")

    def _cmd_note(self, arg: str) -> None:
        """文本直入库：/note 一段文字。"""
        if not arg.strip():
            console.print("[yellow]用法: /note <文本内容>[/yellow]")
            console.print("[dim]示例: /note 骨灰安置费用标准：基本服务费800元[/dim]")
            return
        from core.ingestion.quick import save_text
        try:
            file_path = save_text(arg.strip())
            console.print(f"[dim]已保存临时文件: {file_path.name}[/dim]")
            if self._ingest_one(file_path):
                self._pet_gain_exp(10, "ingest")
                console.print("[green]✓ 文本已入库[/green]")
        except Exception as e:
            console.print(f"[red]入库失败: {e}[/red]")

    def _cmd_clip(self) -> None:
        """剪贴板入库：自动识别截图/文字/URL。"""
        from core.ingestion.quick import save_clipboard
        with console.status("[bold yellow]读取剪贴板...[/bold yellow]", spinner="dots"):
            file_path, content_type = save_clipboard()

        if file_path is None:
            console.print(f"[yellow]剪贴板内容无效: {content_type}[/yellow]")
            console.print("[dim]支持：截图（Cmd+Shift+4）、复制文字、复制 URL[/dim]")
            return

        type_label = {"image": "📷 截图", "text": "📝 文本", "url": "🔗 网页"}.get(content_type, "内容")
        console.print(f"[dim]检测到: {type_label}[/dim]")
        if self._ingest_one(file_path):
            self._pet_gain_exp(10, "ingest")
            console.print(f"[green]✓ {type_label}已入库[/green]")

    def _cmd_url(self, arg: str) -> None:
        """网页入库：/url https://...。"""
        if not arg.strip():
            console.print("[yellow]用法: /url <网页地址>[/yellow]")
            console.print("[dim]示例: /url https://www.example.com/policy[/dim]")
            return
        url = arg.strip()
        if not (url.startswith("http://") or url.startswith("https://")):
            url = "https://" + url

        from core.ingestion.quick import save_url
        with console.status(f"[bold yellow]抓取网页...[/bold yellow] {url}", spinner="dots"):
            try:
                file_path = save_url(url)
            except Exception as e:
                console.print(f"[red]抓取失败: {e}[/red]")
                return

        console.print(f"[dim]已提取网页正文: {file_path.name}[/dim]")
        if self._ingest_one(file_path):
            self._pet_gain_exp(15, "ingest")
            console.print("[green]✓ 网页已入库[/green]")

    def _ingest_one(self, file_path: Path) -> bool:
        """入库单个文件。"""
        if not is_supported(file_path):
            return False
        try:
            parsed = parse(file_path)
            if not parsed.text.strip():
                if parsed.meta.get("ocr_unavailable"):
                    console.print(
                        f"  [yellow]跳过图片[/yellow]（OCR 未安装）: {file_path.name}  "
                        f"[dim]用 brew install tesseract tesseract-lang 启用[/dim]"
                    )
                else:
                    console.print(f"  [yellow]跳过空内容[/yellow]: {file_path.name}")
                return False
            chunks = chunk_document(
                parsed,
                chunk_size=settings.chunk_size,
                chunk_overlap=settings.chunk_overlap,
            )
            # 去重检查
            import hashlib
            content_hash = hashlib.sha256(parsed.text.encode("utf-8")).hexdigest()
            doc_id = content_hash[:32]
            if self.storage.get_document(doc_id) is not None:
                console.print(f"  [cyan]已存在（跳过）[/cyan]: {file_path.name}")
                return False

            # 自动打标签
            tags: list[str] = []
            if self.llm_available:
                try:
                    from core.classify.tagger import Tagger
                    tagger = Tagger()
                    tags = tagger.generate_tags_for_document(parsed)
                except Exception as e:
                    console.print(f"  [dim]标签生成失败: {type(e).__name__}[/dim]")

            record = self.storage.save_document(parsed, chunks, copy_file=True, tags=tags)
            tag_str = f"  [dim]标签: {', '.join(tags)}[/dim]" if tags else ""
            console.print(
                f"  [green]✓[/green] {file_path.name}  "
                f"[dim]分块 {record.chunk_count} / {record.total_tokens} tokens[/dim]{tag_str}"
            )
            return True
        except ParseError as e:
            console.print(f"  [red]解析失败[/red]: {file_path.name} - {e}")
            return False
        except Exception as e:
            console.print(f"  [red]入库失败[/red]: {file_path.name} - {type(e).__name__}: {e}")
            return False

    # ---- 数据表分析 ----

    def _cmd_analyze(self, arg: str) -> None:
        """数据表智能分析：/analyze <文件路径> [--sheet 名称 | --sheets]"""
        if not arg:
            console.print("[yellow]用法:[/yellow]")
            console.print("  [cyan]/analyze <文件路径>[/cyan]              一键分析")
            console.print("  [cyan]/analyze <文件路径> --sheet 名称[/cyan]  指定 Excel sheet")
            console.print("  [cyan]/analyze <文件路径> --sheets[/cyan]     列出所有 sheet")
            console.print("[dim]支持格式: xlsx / xls / csv / tsv / json[/dim]")
            return

        if not self.llm_available:
            console.print("[red]LLM 未配置，数据分析需要 AGNES_API_KEY[/red]")
            return

        # 解析参数
        tokens = arg.split()
        file_path_str = tokens[0] if tokens else ""
        list_sheets_only = "--sheets" in arg
        sheet_name = None
        if "--sheet" in tokens:
            idx = tokens.index("--sheet")
            if idx + 1 < len(tokens):
                sheet_name = tokens[idx + 1]

        if not file_path_str:
            console.print("[red]请提供文件路径[/red]")
            return

        path = Path(file_path_str).expanduser().resolve()
        if not path.exists():
            console.print(f"[red]文件不存在:[/red] {path}")
            return

        # 仅列出 sheet
        if list_sheets_only:
            try:
                from core.analyze.analyzer import DataAnalyzer
                az = DataAnalyzer()
                sheets = az.list_sheets(path)
                if not sheets:
                    console.print("[yellow]该文件不是 Excel，无 sheet[/yellow]")
                else:
                    console.print(f"[bold]Excel「{path.name}」的 sheets:[/bold]")
                    for i, s in enumerate(sheets, 1):
                        console.print(f"  [cyan]{i}.[/cyan] {s}")
            except Exception as e:
                console.print(f"[red]读取 sheet 失败:[/red] {e}")
            return

        # 执行分析
        from rich.spinner import Spinner
        from rich.live import Live

        try:
            from core.analyze.analyzer import DataAnalyzer
            console.print(f"\n[bold]📊 分析中[/bold] [dim]{path.name}[/dim]...")
            with Live(Spinner("dots", text="[cyan]读取数据 + 统计 + AI 解读...[/cyan]"), console=console, transient=True):
                az = DataAnalyzer()
                result = az.analyze(path, sheet_name=sheet_name)
            # 渲染结果
            az.render(result)
            # 保存到当前分析状态（供追问用）
            self.current_analysis = (az, result)
            console.print(
                "[dim]提示：现在可以直接追问，如「按月份汇总」「哪个最多」「缺失值情况」[/dim]\n"
            )
            # 宠物经验埋点：analyze 行为
            self._pet_gain_exp(15, "analyze")
        except FileNotFoundError as e:
            console.print(f"[red]{e}[/red]")
        except ValueError as e:
            console.print(f"[red]格式不支持:[/red] {e}")
        except Exception as e:
            err_msg = str(e).replace("[", "\\[")
            console.print(f"[red]分析失败:[/red] {type(e).__name__}: {err_msg}")

    def _cmd_list(self) -> None:
        """列出文档。"""
        docs = self.storage.list_documents(limit=100)
        if not docs:
            console.print("[yellow]知识库为空[/yellow]")
            return
        table = Table(title=f"知识库文档（共 {len(docs)} 条）")
        table.add_column("ID", style="cyan", width=10)
        table.add_column("标题", style="white")
        table.add_column("类型", style="yellow")
        table.add_column("标签", style="magenta")
        table.add_column("分块", justify="right")
        table.add_column("Tokens", justify="right")
        table.add_column("入库时间", style="dim")
        for d in docs:
            table.add_row(
                d.id[:8], d.title, d.file_type,
                "、".join(d.tags) if d.tags else "[dim]-[/dim]",
                str(d.chunk_count), str(d.total_tokens),
                d.created_at[:19],
            )
        console.print(table)

    def _cmd_show(self, id_str: str) -> None:
        """查看文档详情。"""
        if not id_str:
            console.print("[yellow]用法: /show <id 前 8 位>[/yellow]")
            return
        # 简写匹配
        doc_id = self._resolve_doc_id(id_str)
        if not doc_id:
            console.print(f"[red]未找到文档:[/red] {id_str}")
            return
        doc = self.storage.get_document(doc_id)
        if not doc:
            console.print(f"[red]未找到文档[/red]")
            return
        console.print(f"\n[bold cyan]{doc.title}[/bold cyan]")
        console.print(f"  ID:       {doc.id}")
        console.print(f"  文件名:   {doc.file_name}")
        console.print(f"  类型:     {doc.file_type}")
        console.print(f"  大小:     {doc.file_size} bytes")
        console.print(f"  语言:     {doc.language}")
        console.print(f"  分块:     {doc.chunk_count}")
        console.print(f"  Tokens:   {doc.total_tokens}")
        console.print(f"  入库时间: {doc.created_at}")
        console.print(f"  原路径:   {doc.file_path}")
        if doc.meta:
            # 显示关键 meta 字段（saved_path/ocr_used/ocr_failed_pages 等）
            meta_parts = [f"{k}={v}" for k, v in doc.meta.items() if v]
            console.print(f"  元信息:   [dim]{', '.join(meta_parts[:5])}[/dim]")
        if doc.tags:
            console.print(f"  标签:     [magenta]{'、'.join(doc.tags)}[/magenta]")
        else:
            console.print(f"  标签:     [dim]（无）[/dim]")
        console.print()
        chunks = self.storage.get_chunks(doc_id)
        for c in chunks[:3]:
            console.print(f"[dim]--- Chunk #{c.index} ---[/dim]")
            console.print(c.content[:400] + ("..." if len(c.content) > 400 else ""))
            console.print()
        if len(chunks) > 3:
            console.print(f"[dim]... 还有 {len(chunks) - 3} 块[/dim]\n")

    def _cmd_tags(self) -> None:
        """列出所有标签。"""
        tags = self.storage.list_all_tags()
        if not tags:
            console.print("[yellow]还没有标签[/yellow]")
            console.print("[dim]提示: 在终端运行 ima retag 给文档批量打标签[/dim]")
            return
        console.print(f"\n[bold]所有标签[/bold] [dim]（共 {len(tags)} 个）[/dim]\n")
        for tag, cnt in tags.items():
            console.print(f"  [magenta]{tag}[/magenta] [dim]×{cnt}[/dim]")
        console.print()

    def _cmd_tag(self, name: str) -> None:
        """按标签筛选文档。"""
        if not name:
            console.print("[yellow]用法: /tag <标签名>[/yellow]")
            console.print("[dim]提示: 输入 /tags 查看所有可用标签[/dim]")
            return
        docs = self.storage.list_documents_by_tag(name)
        if not docs:
            console.print(f"[yellow]没有带标签 '{name}' 的文档[/yellow]")
            console.print("[dim]提示: 输入 /tags 查看所有可用标签[/dim]")
            return
        console.print(f"\n[bold]带标签 '{name}' 的文档[/bold] [dim]（共 {len(docs)} 个）[/dim]\n")
        table = Table(show_lines=False)
        table.add_column("ID", style="cyan", width=10)
        table.add_column("标题", style="white")
        table.add_column("类型", style="yellow")
        table.add_column("标签", style="magenta")
        for d in docs:
            table.add_row(
                d.id[:8], d.title, d.file_type,
                "、".join(d.tags),
            )
        console.print(table)
        console.print()

    def _cmd_tag_rename(self, arg: str) -> None:
        """重命名标签：/tag rename <旧名> <新名>"""
        parts = arg.split(maxsplit=1)
        if len(parts) < 2:
            console.print("[yellow]用法: /tag rename <旧标签> <新标签>[/yellow]")
            return
        old_tag, new_tag = parts[0].strip(), parts[1].strip()
        if not new_tag:
            console.print("[yellow]新标签名不能为空[/yellow]")
            return
        affected = self.storage.rename_tag(old_tag, new_tag)
        if affected > 0:
            console.print(f"[green]✓ 已重命名标签[/green] [dim]{old_tag} → [/dim][magenta]{new_tag}[/magenta]")
            console.print(f"  [dim]影响 {affected} 个文档[/dim]")
        else:
            console.print(f"[yellow]未找到标签: {old_tag}[/yellow]")

    def _cmd_tag_merge(self, arg: str) -> None:
        """合并标签：/tag merge <源标签> <目标标签>"""
        parts = arg.split(maxsplit=1)
        if len(parts) < 2:
            console.print("[yellow]用法: /tag merge <源标签> <目标标签>[/yellow]")
            console.print("[dim]源标签将被删除，其文档改用目标标签[/dim]")
            return
        source_tag, target_tag = parts[0].strip(), parts[1].strip()
        if not target_tag:
            console.print("[yellow]目标标签名不能为空[/yellow]")
            return
        affected = self.storage.merge_tag(source_tag, target_tag)
        if affected > 0:
            console.print(f"[green]✓ 已合并标签[/green] [dim]{source_tag} → [/dim][magenta]{target_tag}[/magenta]")
            console.print(f"  [dim]影响 {affected} 个文档[/dim]")
        else:
            console.print(f"[yellow]未找到源标签: {source_tag}[/yellow]")

    def _cmd_delete(self, id_str: str) -> None:
        """删除文档。"""
        if not id_str:
            console.print("[yellow]用法: /delete <id 前 8 位>[/yellow]")
            return
        doc_id = self._resolve_doc_id(id_str)
        if not doc_id:
            console.print(f"[red]未找到文档:[/red] {id_str}")
            return
        doc = self.storage.get_document(doc_id)
        if not doc:
            console.print("[red]文档不存在[/red]")
            return
        # 确认
        confirm = Prompt.ask(
            f"确定删除 [cyan]{doc.title}[/cyan]？",
            choices=["y", "n"], default="n"
        )
        if confirm != "y":
            console.print("[dim]已取消[/dim]")
            return
        if self.storage.delete_document(doc_id):
            console.print(f"[green]✓ 已删除[/green]")
        else:
            console.print(f"[red]删除失败[/red]")

    def _cmd_reparse(self, id_str: str) -> None:
        """重新解析文档：/reparse <id 前 8 位 | 文件路径>

        适用场景：
        - OCR 失败的文档（安装 tesseract 后重新解析）
        - 文件内容更新后重新入库
        - 解析器升级后重试

        流程：删除旧文档 → 重置 OCR 缓存 → 重新解析原文件 → 入库
        """
        if not id_str:
            console.print("[yellow]用法: /reparse <id 前 8 位 | 文件路径>[/yellow]")
            console.print("[dim]用于重新解析 OCR 失败或内容更新的文档[/dim]")
            return

        # 判断输入是 doc_id 还是文件路径
        from pathlib import Path as _Path
        maybe_path = _Path(id_str)
        if maybe_path.exists() and maybe_path.is_file():
            # 直接按文件路径处理
            file_path = maybe_path
            # 尝试找到对应的旧 doc_id 以便删除
            doc_id = None
        else:
            # 按 doc_id 前缀匹配
            doc_id = self._resolve_doc_id(id_str)
            if not doc_id:
                console.print(f"[red]未找到文档:[/red] {id_str}")
                return
            doc = self.storage.get_document(doc_id)
            if not doc:
                console.print("[red]文档不存在[/red]")
                return
            file_path = _Path(doc.file_path)
            if not file_path.exists():
                console.print(f"[red]原文件不存在:[/red] {file_path}")
                console.print("[dim]文档记录中的原文件路径已失效[/dim]")
                return

        # 确认
        console.print(f"[dim]将重新解析: {file_path.name}[/dim]")
        confirm = Prompt.ask(
            "确定重新解析？（会先删除旧文档记录）",
            choices=["y", "n"], default="n",
        )
        if confirm != "y":
            console.print("[dim]已取消[/dim]")
            return

        # 1. 删除旧文档（如果存在 doc_id）
        if doc_id:
            self.storage.delete_document(doc_id)
            console.print(f"[dim]已删除旧记录[/dim]")

        # 2. 重置 OCR 缓存（用户可能刚安装了 tesseract）
        from core.ingestion.parser import reset_ocr_cache
        reset_ocr_cache()

        # 3. 重新解析并入库
        console.print(f"[bold]重新解析...[/bold] [dim]{file_path.name}[/dim]")
        if self._ingest_one(file_path):
            self._pet_gain_exp(15, "ingest")
            console.print("[green]✓ 重新解析完成[/green]")
            # 如果原文件被追踪，更新追踪记录
            try:
                from core.sync.tracker import FileTracker
                tracker = FileTracker(storage_path=settings.storage_path)
                tracker.scan_directory(str(file_path.parent))
            except Exception:
                pass  # 追踪更新失败不影响主流程
        else:
            console.print(f"[red]重新解析失败[/red]")

    def _cmd_edit(self, arg: str) -> None:
        """编辑文档属性：/edit <id> <field> <value>

        支持的字段：
            title <新标题>   修改文档标题
            tags  <标签列表>  修改标签（逗号分隔）
        """
        if not arg:
            console.print("[yellow]用法: /edit <id> <field> <value>[/yellow]")
            console.print("  [cyan]/edit <id> title <新标题>[/cyan]    修改标题")
            console.print("  [cyan]/edit <id> tags <标签,标签>[/cyan]   修改标签")
            return
        parts = arg.split(maxsplit=2)
        if len(parts) < 2:
            console.print("[yellow]用法: /edit <id> <field> <value>[/yellow]")
            return
        id_str, field = parts[0], parts[1].lower()
        value = parts[2].strip() if len(parts) > 2 else ""
        doc_id = self._resolve_doc_id(id_str)
        if not doc_id:
            console.print(f"[red]未找到文档:[/red] {id_str}")
            return
        doc = self.storage.get_document(doc_id)
        if not doc:
            console.print(f"[red]文档不存在[/red]")
            return

        if field == "title":
            if not value:
                console.print("[yellow]新标题不能为空[/yellow]")
                return
            ok = self.storage.update_document_title(doc_id, value)
            if ok:
                console.print(f"[green]✓ 标题已更新[/green]")
                console.print(f"  [dim]{doc.title} → [/dim][cyan]{value}[/cyan]")
            else:
                console.print(f"[red]更新失败[/red]")
        elif field == "tags":
            if not value:
                # 空值表示清除所有标签
                tags = []
            else:
                tags = [t.strip() for t in value.replace("、", ",").split(",") if t.strip()]
            ok = self.storage.update_document_tags(doc_id, tags)
            if ok:
                if tags:
                    console.print(f"[green]✓ 标签已更新: [magenta]{'、'.join(tags)}[/magenta][/green]")
                else:
                    console.print(f"[green]✓ 已清除所有标签[/green]")
            else:
                console.print(f"[red]更新失败[/red]")
        else:
            console.print(f"[red]未知字段: '{field}'[/red]  允许: title / tags")

    def _cmd_stats(self) -> None:
        """统计。"""
        s = self.storage.stats()
        bm25_info = self.storage.bm25.info()
        console.print("\n[bold]📊 知识库统计[/bold]\n")
        console.print(f"  文档总数:    [cyan]{s['documents']}[/cyan]")
        console.print(f"  分块总数:    [cyan]{s['chunks']}[/cyan]")
        console.print(f"  总 Tokens:   [cyan]{s['total_tokens']:,}[/cyan]")
        console.print(f"  原文件大小:  [cyan]{s['total_size_mb']} MB[/cyan]")
        console.print(f"  BM25 词汇量: [cyan]{bm25_info['vocabulary']}[/cyan]")
        if s["by_type"]:
            console.print("\n  [bold]按类型分布:[/bold]")
            for ftype, cnt in s["by_type"].items():
                console.print(f"    {ftype:12s} {cnt}")
        # 标签统计
        tags = self.storage.list_all_tags()
        if tags:
            console.print(f"\n  [bold]标签统计[/bold] [dim]（共 {len(tags)} 个）[/dim]")
            for tag, cnt in list(tags.items())[:10]:
                console.print(f"    [magenta]{tag}[/magenta] [dim]×{cnt}[/dim]")
            if len(tags) > 10:
                console.print(f"    [dim]... 还有 {len(tags) - 10} 个标签[/dim]")
        console.print()

    def _cmd_rebuild(self, arg: str = "") -> None:
        """重建索引：/rebuild [--vector]

        --vector / -v: 同时重建向量索引并热更新到当前会话的检索链路
        """
        vector_flag = "--vector" in arg or "-v" in arg
        console.print("[bold]重建 BM25 索引...[/bold]")
        count = self.storage.rebuild_bm25_index()
        info = self.storage.bm25.info()
        console.print(f"[green]✓ BM25 完成[/green] · 索引 {info['chunks']} 块 / 词汇 {info['vocabulary']}")

        if vector_flag:
            try:
                from core.retrieval.vector import VectorIndex
                vector_index = VectorIndex()
                if vector_index.is_available():
                    console.print("[bold]重建向量索引...[/bold]")
                    v_count = self.storage.rebuild_vector_index(vector_index)
                    console.print(f"[green]✓ 向量索引完成[/green] · {v_count} 块")
                    # 热更新：让当前会话的检索链路立即用上新索引
                    self.storage.attach_vector_index(vector_index)
                    if self.administrator is not None:
                        self.administrator.hybrid.vector = vector_index
                    console.print("[dim]已热更新到当前会话（无需重启）[/dim]")
                else:
                    console.print("[yellow]⚠ 向量索引不可用（依赖未安装）[/yellow]")
                    console.print("[dim]用 'bash install.sh --vector' 安装[/dim]")
            except ImportError:
                console.print("[yellow]⚠ 向量依赖未安装[/yellow]")
            except Exception as e:
                console.print(f"[red]向量索引重建失败: {e}[/red]")
                console.print("[dim]BM25 索引已重建，向量索引仍可用旧实例[/dim]")

    def _cmd_retag(self, arg: str) -> None:
        """重新生成/补全文档标签。"""
        from core.classify.tagger import Tagger
        from core.llm.client import LLMError

        if not settings.has_llm():
            console.print("[red]未配置 AGNES_API_KEY，无法调用 LLM 打标签[/red]")
            return

        # 解析参数: /retag [-f] [-d ID] [-n N]
        force = "-f" in arg or "--force" in arg
        doc_id = ""
        limit = 0
        parts = arg.split()
        for i, p in enumerate(parts):
            if p in ("-d", "--doc-id") and i + 1 < len(parts):
                doc_id = parts[i + 1]
            elif p in ("-n", "--limit") and i + 1 < len(parts):
                try:
                    limit = int(parts[i + 1])
                except ValueError:
                    pass

        # 选目标文档
        if doc_id:
            if len(doc_id) < 32:
                all_docs = self.storage.list_documents(limit=10000)
                target_docs = [d for d in all_docs if d.id.startswith(doc_id)]
            else:
                d = self.storage.get_document(doc_id)
                target_docs = [d] if d else []
            if not target_docs:
                console.print(f"[red]未找到文档: {doc_id}[/red]")
                return
        else:
            all_docs = self.storage.list_documents(limit=10000)
            if force:
                target_docs = all_docs
            else:
                target_docs = [d for d in all_docs if not d.tags]
            if limit:
                target_docs = target_docs[:limit]

        if not target_docs:
            console.print("[yellow]没有需要打标签的文档[/yellow]")
            if not force and not doc_id:
                console.print("[dim]提示: /retag -f 重新生成所有标签[/dim]")
            return

        console.print(f"\n[bold]开始打标签[/bold] · 共 {len(target_docs)} 个文档\n")

        try:
            tagger = Tagger()
        except LLMError as e:
            console.print(f"[red]LLM 初始化失败:[/red] {e}")
            return

        success, fail = 0, 0
        for i, doc in enumerate(target_docs, 1):
            chunks = self.storage.get_chunks(doc.id)
            content_preview = "\n".join(c.content for c in chunks)
            console.print(f"[{i}/{len(target_docs)}] [cyan]{doc.title[:50]}[/cyan]")
            try:
                tags = tagger.generate_tags(
                    title=doc.title, file_type=doc.file_type, content=content_preview,
                )
                if tags:
                    self.storage.update_document_tags(doc.id, tags)
                    console.print(f"  [green]✓[/green] [dim]{', '.join(tags)}[/dim]")
                    success += 1
                else:
                    console.print("  [yellow]未生成标签[/yellow]")
                    fail += 1
            except Exception as e:
                console.print(f"  [red]失败: {e}[/red]")
                fail += 1

        console.print(f"\n[bold]完成[/bold] · 成功 {success} / 失败 {fail}\n")

    def _cmd_watch(self, arg: str) -> None:
        """监控文件夹变化自动入库。"""
        if not arg.strip():
            console.print("[yellow]用法: /watch <目录路径> [-i 间隔秒] [--once][/yellow]")
            console.print("[dim]示例: /watch ~/Documents/政策文件[/dim]")
            return

        parts = arg.split()
        dir_path = parts[0]
        interval = 10
        once = "--once" in arg

        for i, p in enumerate(parts):
            if p in ("-i", "--interval") and i + 1 < len(parts):
                try:
                    interval = int(parts[i + 1])
                except ValueError:
                    pass

        path = Path(dir_path).expanduser().resolve()
        if not path.is_dir():
            console.print(f"[red]路径不是文件夹: {path}[/red]")
            return

        console.print(f"[bold green]📡 文件监控启动[/bold green]")
        console.print(f"  目录: [cyan]{path}[/cyan]")
        console.print(f"  间隔: {interval}秒" + ("（单次模式）" if once else "（持续模式，Ctrl+C 退出）"))
        console.print(f"  支持格式: {', '.join(sorted(SUPPORTED_EXTENSIONS))}\n")

        import time
        seen = set()

        def scan_once() -> int:
            files = []
            for ext in SUPPORTED_EXTENSIONS:
                files.extend(path.rglob(f"*{ext}"))
            files = sorted(set(files))
            new_files = [f for f in files if str(f) not in seen]
            if not new_files:
                return 0
            console.print(f"[dim]{time.strftime('%H:%M:%S')} 发现 {len(new_files)} 个新文件[/dim]")
            success = 0
            for f in new_files:
                seen.add(str(f))
                if self._ingest_one(f):
                    success += 1
                    self._pet_gain_exp(30, "ingest")
            if success:
                console.print(f"[green]✓ 本次入库 {success} 个文件[/green]\n")
            return success

        try:
            scan_once()
            if once:
                return
            while True:
                time.sleep(interval)
                scan_once()
        except KeyboardInterrupt:
            console.print(f"\n[yellow]监控已停止[/yellow]")

    def _cmd_web(self, arg: str) -> None:
        """启动/停止 FastAPI Web 后台。
        用法:
          /web                  启动 Web（默认 127.0.0.1:8501）
          /web --host 0.0.0.0 --port 8080  自定义地址和端口
          /web stop             停止 Web 后台服务
        """
        try:
            import uvicorn
        except ImportError:
            console.print("[red]缺少 Web 依赖，请运行: pip install uvicorn fastapi[/red]")
            return

        parts = arg.strip().split()

        # ---- 停止子命令 ----
        if parts and parts[0] == "stop":
            if self._web_server is None:
                console.print("[yellow]Web 服务未在运行[/yellow]")
                return
            console.print("[yellow]正在停止 Web 服务...[/yellow]")
            self._web_server.should_exit = True
            if self._web_thread is not None:
                self._web_thread.join(timeout=5)
            self._web_server = None
            self._web_thread = None
            console.print("[green]✓ Web 服务已停止[/green]")
            return

        # ---- 已运行时给出提示 ----
        if self._web_server is not None:
            console.print("[yellow]Web 服务已在运行中，请先执行 /web stop 停止[/yellow]")
            return

        host = "127.0.0.1"
        port = 8501
        for i, p in enumerate(parts):
            if p in ("--host", "-h") and i + 1 < len(parts):
                host = parts[i + 1]
            elif p in ("-p", "--port") and i + 1 < len(parts):
                port = int(parts[i + 1])

        from web.app import create_app
        app = create_app()
        config = uvicorn.Config(app, host=host, port=port, log_level="warning")
        self._web_server = uvicorn.Server(config)

        def _run_server():
            try:
                self._web_server.run()
            except Exception:
                pass

        self._web_thread = threading.Thread(target=_run_server, daemon=True)
        self._web_thread.start()

        console.print(f"\n[bold green]🚀 IMA Web 后台启动[/bold green]\n")
        console.print(f"  地址: [cyan]http://{host}:{port}[/cyan]")
        console.print(f"  停止: [dim]/web stop[/dim]\n")

    # ---- 同步与维护 ----

    def _cmd_sync(self, arg: str) -> None:
        """增量同步目录：/sync <目录> 或 /sync reset"""
        if not arg:
            console.print("[yellow]用法:[/yellow]")
            console.print("  [cyan]/sync <目录路径>[/cyan]  增量同步目录")
            console.print("  [cyan]/sync reset[/cyan]      清空文件追踪记录（下次全量重建）")
            return
        # 子命令: reset
        if arg.strip().lower() == "reset":
            from core.sync.tracker import FileTracker
            tracker = FileTracker(storage_path=settings.storage_path)
            confirm = Prompt.ask(
                "确定清空所有文件追踪记录？下次同步将全量重建。",
                choices=["y", "n"], default="n",
            )
            if confirm != "y":
                console.print("[dim]已取消[/dim]")
                return
            count = tracker.reset()
            console.print(f"[green]✓ 已清空 {count} 条追踪记录[/green]")
            return
        from core.sync.tracker import FileTracker
        tracker = FileTracker(storage_path=settings.storage_path)

        def on_progress(action: str, fp: str) -> None:
            if action == "added":
                console.print(f"  [green]✓ 新增[/green]: {Path(fp).name}")
            elif action == "updated":
                console.print(f"  [yellow]↻ 更新[/yellow]: {Path(fp).name}")
            elif action == "deleted":
                console.print(f"  [red]✗ 删除[/red]: {Path(fp).name}")

        with console.status("[bold yellow]扫描同步...[/bold yellow]", spinner="dots"):
            result = tracker.sync_directory(arg, self.storage, on_progress=on_progress)

        console.print(
            f"\n[bold]同步完成[/bold]  新增 {len(result.added)} / "
            f"更新 {len(result.updated)} / 删除 {len(result.deleted)} / "
            f"跳过 {len(result.skipped)}"
        )
        if result.errors:
            console.print(f"[red]错误 {len(result.errors)} 个[/red]")

    def _cmd_health(self, arg: str) -> None:
        """数据质量报告：/health [list]"""
        from core.sync.checker import QualityChecker
        checker = QualityChecker()

        with console.status("[bold yellow]检查质量...[/bold yellow]", spinner="dots"):
            docs = self.storage.list_documents(limit=1000)
            all_results = []
            for doc in docs:
                chunks = self.storage.get_chunks(doc.id)
                all_results.extend(checker.check_document(chunks))
            report = checker.generate_report(all_results)

        console.print(f"\n[bold]📊 知识库健康报告[/bold]\n")
        console.print(f"  文档: {len(docs)}  Chunk: {report.total_chunks}")
        console.print(f"  ✓ 正常: {report.normal} ({report.normal_pct}%)")
        console.print(f"  ⚠ 低质量: {report.low_quality}")
        if report.ocr_poor:
            console.print(f"  ⚠ OCR 乱码: {report.ocr_poor}")
        console.print(f"  [bold]健康分: {report.health_score}/100[/bold]")

        # 子命令: list - 列出低质量 chunk
        if arg.strip().lower() in ("list", "detail", "low"):
            low_quality = [r for r in all_results if r.score < 0.6]
            if not low_quality:
                console.print("\n[green]无低质量 chunk[/green]")
                return
            console.print(f"\n[bold]低质量 Chunk（共 {len(low_quality)} 个）[/bold]\n")
            table = Table(show_lines=False, border_style="yellow")
            table.add_column("Chunk ID", style="cyan", width=14)
            table.add_column("文档", style="white")
            table.add_column("评分", style="yellow", width=6)
            table.add_column("问题", style="red")
            for r in low_quality[:20]:
                issues = "、".join(r.issues) if r.issues else ""
                table.add_row(r.chunk_id[:12], r.doc_id[:8], f"{r.score:.2f}", issues)
            console.print(table)
            if len(low_quality) > 20:
                console.print(f"[dim]... 还有 {len(low_quality) - 20} 个[/dim]")
            console.print("\n[dim]用 /dedup delete <chunk_id> 删除问题 chunk[/dim]")

    def _cmd_dedup(self, arg: str) -> None:
        """扫描近似重复：/dedup [delete <chunk_id>]"""
        # 子命令: delete
        parts = arg.split(maxsplit=1) if arg else []
        if parts and parts[0].lower() in ("delete", "del", "rm"):
            if len(parts) < 2 or not parts[1].strip():
                console.print("[yellow]用法: /dedup delete <chunk_id>[/yellow]")
                return
            chunk_id = parts[1].strip()
            # 支持简写前缀匹配
            if len(chunk_id) < 32:
                # 搜索匹配的 chunk
                docs = self.storage.list_documents(limit=1000)
                matched = []
                for doc in docs:
                    chunks = self.storage.get_chunks(doc.id)
                    for c in chunks:
                        if c.id.startswith(chunk_id):
                            matched.append(c.id)
                if not matched:
                    console.print(f"[red]未找到 chunk: {chunk_id}[/red]")
                    return
                if len(matched) > 1:
                    console.print(f"[yellow]ID 前缀匹配多个 chunk，请提供更完整的 ID[/yellow]")
                    for cid in matched[:5]:
                        console.print(f"  [dim]{cid}[/dim]")
                    return
                chunk_id = matched[0]
            confirm = Prompt.ask(
                f"确定删除 chunk [cyan]{chunk_id[:12]}[/cyan]？",
                choices=["y", "n"], default="n",
            )
            if confirm != "y":
                console.print("[dim]已取消[/dim]")
                return
            ok = self.storage.delete_chunk(chunk_id)
            if ok:
                # 同步删除向量索引
                if hasattr(self.storage, '_vector_index') and self.storage._vector_index is not None:
                    try:
                        self.storage._vector_index.delete_chunk(chunk_id)
                    except Exception:
                        pass
                console.print(f"[green]✓ 已删除 chunk[/green] [dim]({chunk_id[:12]})[/dim]")
                console.print("[dim]建议运行 /rebuild 重建 BM25 索引[/dim]")
            else:
                console.print(f"[red]删除失败（chunk 不存在）[/red]")
            return

        from core.sync.dedup import DedupScanner
        scanner = DedupScanner(threshold=0.85)

        with console.status("[bold yellow]扫描重复...[/bold yellow]", spinner="dots"):
            docs = self.storage.list_documents(limit=1000)
            for doc in docs:
                chunks = self.storage.get_chunks(doc.id)
                for c in chunks:
                    scanner.add_chunk(c.id, c.doc_id, c.content)
            results = scanner.scan()

        duplicates = [r for r in results if r.is_duplicate]
        if not duplicates:
            console.print("[green]✓ 未发现近似重复[/green]")
            return

        console.print(f"发现 {len(duplicates)} 个近似重复:")
        for d in duplicates:
            console.print(
                f"  {d.chunk_id[:8]} ← 重复于 {d.duplicate_of[:8]}  "
                f"相似度 {d.similarity:.1%}"
            )
        console.print(f"\n[dim]用 /dedup delete <chunk_id> 删除重复 chunk[/dim]")


    # ---- 图像生成 ----

    def _cmd_draw(self, arg: str) -> None:
        """基于文档内容生成配图：/draw <文档ID前8位> [--style 风格]"""
        from core.image import ImageGenerator, ImageError

        if not arg:
            console.print("[yellow]用法: /draw <文档ID前8位> [--style 水墨/赛博/绘本/简洁信息图][/yellow]")
            console.print("[dim]示例: /draw 862e0973 --style 水墨[/dim]")
            return

        # 解析参数
        doc_id_prefix = arg.split("--")[0].strip()
        style = "简洁信息图"
        if "--style" in arg:
            parts = arg.split("--style")
            if len(parts) > 1:
                style = parts[1].lstrip(" ").split("--")[0].strip() or "简洁信息图"

        try:
            gen = ImageGenerator()
        except ImageError as e:
            console.print(f"[red]图像生成未配置:[/red] {e}")
            console.print("[dim]请在 .env 中设置 AGNES_API_KEY（与 LLM 共用）[/dim]")
            return

        # 获取文档
        doc = self.storage.get_document(doc_id_prefix)
        if not doc:
            console.print(f"[red]文档不存在:[/red] {doc_id_prefix}")
            return

        # 获取文档前几段内容
        try:
            chunks = self.storage.get_chunks_by_doc(doc.id, limit=3)
            content = "\n".join(c.content for c in chunks)[:500]
        except Exception:
            content = doc.title

        # 生成图片
        console.print(f"[bold yellow]🎨 正在为「{doc.title}」生成配图...[/bold yellow] [dim](风格: {style})[/dim]")
        try:
            url = gen.doc_to_image(doc.title, content, style=style)
            console.print(f"\n[green]✓ 配图已生成[/green] [dim]({url})[/dim]")
            console.print("[dim]在浏览器中打开图片 URL 查看[/dim]")
            # 尝试打开浏览器
            import webbrowser
            webbrowser.open(url)
        except ImageError as e:
            console.print(f"[red]✗ 生图失败:[/red] {e}")
            console.print("[dim]检查 AGNES_API_KEY 是否正确配置[/dim]")

    def _cmd_daily(self, arg: str) -> None:
        """生成每日知识卡片：/daily [--date YYYY-MM-DD] [--topics 主题1,主题2]"""
        from datetime import datetime
        from core.image import ImageGenerator, ImageError

        try:
            gen = ImageGenerator()
        except ImageError as e:
            console.print(f"[red]图像生成未配置:[/red] {e}")
            return

        # 解析参数
        date_str = datetime.now().strftime("%Y-%m-%d")
        topics = []

        if "--date" in arg:
            parts = arg.split("--date")
            if len(parts) > 1:
                date_str = parts[1].split("--")[0].strip() or date_str

        if "--topics" in arg:
            parts = arg.split("--topics")
            if len(parts) > 1:
                topic_str = parts[1].split("--")[0].strip()
                topics = [t.strip() for t in topic_str.split(",") if t.strip()]

        # 如果没有手动指定主题，从记忆中提取
        if not topics and self.memory_store:
            try:
                profile = self.memory_store.get_profile()
                if profile.focus_topics:
                    topics = profile.focus_topics[:5]
            except Exception:
                pass

        # 如果还是没有主题，生成一个默认的
        if not topics:
            topics = [f"2026年7月知识回顾"]

        console.print(f"[bold yellow]📋 正在生成每日知识卡片...[/bold yellow] [dim]({date_str})[/dim]")
        try:
            url = gen.daily_card(topics, date_str)
            console.print(f"\n[green]✓ 知识卡片已生成[/green] [dim]({url})[/dim]")
            import webbrowser
            webbrowser.open(url)
        except ImageError as e:
            console.print(f"[red]✗ 生图失败:[/red] {e}")

    def _cmd_pic(self, arg: str) -> None:
        """直接文生图：/pic <描述>"""
        from core.image import ImageGenerator, ImageError

        if not arg.strip():
            console.print("[yellow]用法: /pic <图像描述>[/yellow]")
            console.print("[dim]示例: /pic 一只在竹林中散步的猫[/dim]")
            return

        try:
            gen = ImageGenerator()
        except ImageError as e:
            console.print(f"[red]图像生成未配置:[/red] {e}")
            return

        console.print(f"[bold yellow]🎨 正在生成图像...[/bold yellow]")
        try:
            url = gen.text_to_image(arg.strip())
            console.print(f"\n[green]✓ 图像已生成[/green] [dim]({url})[/dim]")
            console.print("[dim]正在打开浏览器...[/dim]")
            import webbrowser
            webbrowser.open(url)
        except ImageError as e:
            console.print(f"[red]✗ 生图失败:[/red] {e}")

    # ---- 会话持久化 ----

    def _cmd_save(self, arg: str) -> None:
        """保存当前会话：/save [名称]"""
        from core.session.store import SessionStore
        if not self.history:
            console.print("[yellow]当前对话为空，无需保存[/yellow]")
            return
        if not arg:
            # 用时间作默认名
            from datetime import datetime
            arg = datetime.now().strftime("session_%m%d_%H%M")
        ss = SessionStore()
        meta = {"doc_count": self.storage.stats().get("documents", 0)}
        path = ss.save(arg, self.history, meta=meta)
        console.print(
            f"[green]✓ 已保存会话[/green] [bold]{arg}[/bold]  "
            f"[dim]({len(self.history)} 条消息 → {path.name})[/dim]"
        )

    def _cmd_load(self, arg: str) -> None:
        """恢复会话：/load <名称>"""
        from core.session.store import SessionStore
        if not arg:
            console.print("[yellow]用法: /load <会话名称>[/yellow]")
            console.print("[dim]用 /sessions 查看所有已保存会话[/dim]")
            return
        ss = SessionStore()
        history = ss.load(arg)
        if history is None:
            console.print(f"[red]未找到会话: {arg}[/red]")
            console.print("[dim]用 /sessions 查看所有已保存会话[/dim]")
            return
        self.history = history
        console.print(
            f"[green]✓ 已恢复会话[/green] [bold]{arg}[/bold]  "
            f"[dim]({len(history)} 条消息)[/dim]"
        )
        # 显示最后 2 条对话作为预览
        if history:
            console.print("\n[bold]最后对话预览：[/bold]")
            for msg in history[-2:]:
                role = "🧑" if msg.get("role") == "user" else "🤖"
                content = msg.get("content", "")[:150]
                console.print(f"  {role} {content}{'...' if len(msg.get('content', '')) > 150 else ''}")
            console.print()

    def _cmd_sessions(self) -> None:
        """列出所有已保存会话：/sessions"""
        from core.session.store import SessionStore
        ss = SessionStore()
        sessions = ss.list_sessions()
        if not sessions:
            console.print("[yellow]暂无已保存的会话[/yellow]  [dim]用 /save <名称> 保存当前对话[/dim]")
            return
        console.print(f"\n[bold]已保存的会话[/bold] [dim]（共 {len(sessions)} 个）[/dim]\n")
        table = Table(show_lines=False)
        table.add_column("名称", style="cyan")
        table.add_column("消息数", justify="right", style="yellow")
        table.add_column("保存时间", style="dim")
        for s in sessions:
            table.add_row(s["name"], str(s["message_count"]), s["saved_at"])
        console.print(table)
        console.print("\n[dim]恢复: /load <名称>  导出: /export <名称>[/dim]\n")

    def _cmd_export(self, arg: str) -> None:
        """导出会话为 Markdown：/export <名称> [输出路径]"""
        from core.session.store import SessionStore
        if not arg:
            console.print("[yellow]用法: /export <会话名称> [输出路径][/yellow]")
            console.print("[dim]不指定路径默认导出到 storage/sessions/<名称>.md[/dim]")
            return
        parts = arg.split(maxsplit=1)
        name = parts[0]
        out_path = Path(parts[1]) if len(parts) > 1 else None
        ss = SessionStore()
        try:
            path = ss.export_markdown(name, output_path=out_path)
            console.print(
                f"[green]✓ 已导出[/green] [bold]{name}[/bold] → [cyan]{path}[/cyan]"
            )
        except FileNotFoundError:
            console.print(f"[red]会话不存在: {name}[/red]")
            console.print("[dim]用 /sessions 查看所有已保存会话[/dim]")

    def _cmd_session(self, arg: str) -> None:
        """会话管理子命令：/session save|load|list|export|delete [参数]

        整合了 /save /load /sessions /export 四个命令。
        """
        if not arg:
            console.print("[bold]会话管理[/bold] [dim]（/session save|load|list|export|delete）[/dim]\n")
            console.print("  [cyan]/session save [名称][/cyan]     保存当前会话")
            console.print("  [cyan]/session load <名称>[/cyan]     恢复已保存的会话")
            console.print("  [cyan]/session list[/cyan]           列出所有已保存会话")
            console.print("  [cyan]/session export <名称> [路径][/cyan]  导出为 Markdown")
            console.print("  [cyan]/session delete <名称>[/cyan]  删除已保存的会话")
            console.print("\n[dim]别名: /save /load /sessions /export 仍可使用[/dim]")
            return

        parts = arg.split(maxsplit=1)
        sub = parts[0].lower()
        sub_arg = parts[1].strip() if len(parts) > 1 else ""

        if sub == "save":
            self._cmd_save(sub_arg)
        elif sub == "load":
            self._cmd_load(sub_arg)
        elif sub in ("list", "ls"):
            self._cmd_sessions()
        elif sub == "export":
            self._cmd_export(sub_arg)
        elif sub == "delete":
            self._cmd_session_delete(sub_arg)
        else:
            console.print(f"[red]未知子命令: {sub}[/red]")
            console.print("[dim]可用: save / load / list / export / delete[/dim]")

    def _cmd_session_delete(self, name: str) -> None:
        """删除已保存的会话。"""
        if not name:
            console.print("[yellow]用法: /session delete <名称>[/yellow]")
            console.print("[dim]用 /session list 查看已保存的会话[/dim]")
            return
        try:
            from core.session.store import SessionStore
            ss = SessionStore()
            deleted = ss.delete(name)
            if deleted:
                console.print(f"[green]✓ 已删除会话: [cyan]{name}[/cyan][/green]")
            else:
                console.print(f"[yellow]未找到会话: {name}[/yellow]")
        except Exception as e:
            err_msg = str(e).replace("[", "\\[")
            console.print(f"[red]删除会话失败: {err_msg}[/red]")

    # ---- 报告生成 ----

    def _cmd_report(self, arg: str) -> None:
        """生成文档分析报告：/report <文档ID> [输出路径]"""
        if not arg:
            console.print("[yellow]用法: /report <文档ID> [输出路径][/yellow]")
            console.print("[dim]文档 ID 可简写前 8 位，用 /list 查看[/dim]")
            return
        if not self.llm_available:
            console.print("[red]LLM 未配置，无法生成报告[/red]")
            return
        parts = arg.split(maxsplit=1)
        doc_id = parts[0]
        out_path = Path(parts[1]) if len(parts) > 1 else None

        from core.report.generator import ReportGenerator
        from rich.live import Live
        from rich.spinner import Spinner

        try:
            rg = ReportGenerator(storage=self.storage)
            console.print(f"\n[bold]📋 生成报告...[/bold] [dim]ID: {doc_id}[/dim]")
            with Live(Spinner("dots", text="[cyan]AI 分析文档 + 生成结构化报告...[/cyan]"),
                      console=console, transient=True):
                path = rg.generate(doc_id, output_path=out_path)
            console.print(f"\n[green]✓ 报告已生成[/green] → [cyan]{path}[/cyan]")
            console.print(f"  [dim]打开: open '{path}'[/dim]\n")
            # 宠物经验埋点：report 行为
            self._pet_gain_exp(20, "report")
        except FileNotFoundError as e:
            console.print(f"[red]{e}[/red]")
            console.print("[dim]用 /list 查看所有文档 ID[/dim]")
        except Exception as e:
            err_msg = str(e).replace("[", "\\[")
            console.print(f"[red]生成失败:[/red] {type(e).__name__}: {err_msg}")

    # ---- 智能阅读 ----

    def _cmd_read(self, arg: str) -> None:
        """智能阅读模式：/read <文档ID>

        进入后：
        - 默认显示第 1 段 + AI 解读
        - 输入 n / next 下一段，p / prev 上一段
        - 输入数字跳到指定段
        - 输入 i / interpret 重新解读当前段
        - 直接输入文本 = 针对当前段提问
        - q / quit 退出阅读模式
        """
        if not arg:
            # 如果已经在阅读模式，显示当前段
            if self.reader is not None:
                self._render_read_chunk()
                return
            console.print("[yellow]用法: /read <文档ID>[/yellow]")
            console.print("[dim]文档 ID 可简写前 8 位，用 /list 查看[/dim]")
            return
        if not self.llm_available:
            console.print("[red]LLM 未配置，无法使用智能阅读[/red]")
            return

        from core.reader.reader import SmartReader
        try:
            sr = SmartReader(storage=self.storage)
            state = sr.open(arg)
        except FileNotFoundError as e:
            console.print(f"[red]{e}[/red]")
            return
        except Exception as e:
            err_msg = str(e).replace("[", "\\[")
            console.print(f"[red]打开失败: {err_msg}[/red]")
            return

        self.reader = sr
        console.print(f"\n[bold cyan]📖 进入阅读模式[/bold cyan]")
        console.print(f"  文档: [bold]{state.doc_title}[/bold]")
        console.print(f"  共 {state.total_chunks} 段\n")
        self._render_read_chunk()
        console.print("[dim]命令: n=下一段 p=上一段 数字=跳段 i=重新解读 q=退出[/dim]")
        # 宠物经验埋点：read 行为
        self._pet_gain_exp(10, "read")
        console.print("[dim]直接输入文本 = 针对当前段提问[/dim]\n")

    def _render_read_chunk(self) -> None:
        """渲染当前阅读段。"""
        if self.reader is None or self.reader.state is None:
            return
        chunk = self.reader.current_chunk()
        if chunk is None:
            return
        s = self.reader.state
        # 段标题
        console.print(
            f"[bold yellow]━━━ 第 {s.current_index + 1}/{s.total_chunks} 段 "
            f"({chunk.token_count} tokens) ━━━[/bold yellow]"
        )
        # 段内容
        console.print(chunk.content)
        console.print()
        # AI 解读
        with console.status("[bold yellow]AI 解读中...[/bold yellow]", spinner="dots"):
            interpretation = self.reader.interpret()
        console.print(Panel(
            Text(interpretation),
            title="[bold cyan]💡 AI 解读[/bold cyan]",
            border_style="cyan",
            padding=(1, 2),
        ))

    def _cmd_compare(self, arg: str) -> None:
        """智能对比：/compare A B

        A 和 B 可以是文档 ID（前 8 位）或文件路径。
        """
        if not arg:
            console.print("[yellow]用法: /compare <A> <B>[/yellow]")
            console.print("[dim]A 和 B 可以是文档 ID（前 8 位）或文件路径[/dim]")
            console.print("[dim]示例: /compare 24ea6ac3 8f3b9012[/dim]")
            console.print("[dim]示例: /compare 24ea6ac3 ~/Desktop/数据.xlsx[/dim]")
            console.print("[dim]示例: /compare file1.pdf file2.pdf[/dim]")
            return
        if not self.llm_available:
            console.print("[red]LLM 未配置，无法使用智能对比[/red]")
            return

        parts = arg.split(maxsplit=1)
        if len(parts) < 2:
            console.print("[red]请提供两个对比对象[/red]")
            return
        a, b = parts[0], parts[1].strip()

        from core.reader.comparator import Comparator
        from rich.live import Live
        from rich.spinner import Spinner

        try:
            cmp = Comparator(storage=self.storage)
        except Exception as e:
            console.print(f"[red]初始化失败: {e}[/red]")
            return

        # 判断类型：是文档 ID 还是文件路径
        def is_doc_id(s: str) -> bool:
            return not s.startswith("/") and not s.startswith("~") and len(s) <= 32 \
                and all(c in "0123456789abcdef" for c in s.lower())

        console.print(f"\n[bold]🔍 对比中[/bold]")
        console.print(f"  A: [cyan]{a}[/cyan]")
        console.print(f"  B: [cyan]{b}[/cyan]\n")

        try:
            with Live(Spinner("dots", text="[cyan]AI 读取 + 对比 + 生成报告...[/cyan]"),
                      console=console, transient=True):
                if is_doc_id(a) and is_doc_id(b):
                    result = cmp.compare_docs(a, b)
                elif not is_doc_id(a) and not is_doc_id(b):
                    result = cmp.compare_files(Path(a).expanduser(), Path(b).expanduser())
                elif is_doc_id(a) and not is_doc_id(b):
                    result = cmp.compare_doc_and_file(a, Path(b).expanduser())
                else:
                    result = cmp.compare_doc_and_file(b, Path(a).expanduser())
            console.print(Panel(
                Text(result),
                title="[bold yellow]📊 智能对比报告[/bold yellow]",
                border_style="yellow",
                padding=(1, 2),
            ))
            # 宠物经验埋点：compare 行为
            self._pet_gain_exp(10, "compare")
        except FileNotFoundError as e:
            console.print(f"[red]{e}[/red]")
        except Exception as e:
            err_msg = str(e).replace("[", "\\[")
            console.print(f"[red]对比失败: {type(e).__name__}: {err_msg}[/red]")

    # ---- Agent 模式 ----

    def _cmd_agent(self, arg: str) -> None:
        """Agent 模式：/agent <任务描述>

        LLM 自主调工具完成复杂任务（搜索、读文档、分析数据等）。
        """
        if not arg:
            console.print("[yellow]用法: /agent <任务描述>[/yellow]")
            console.print("[dim]示例:[/dim]")
            console.print("  [cyan]/agent 列出所有关于骨灰安置的政策并总结要点[/cyan]")
            console.print("  [cyan]/agent 找到最新政策，阅读第 1 段并解读[/cyan]")
            console.print("  [cyan]/agent 分析 ~/Desktop/数据.xlsx 并跟入库文档对比[/cyan]")
            return
        if not self.llm_available:
            console.print("[red]LLM 未配置，无法使用 Agent 模式[/red]")
            return

        from core.agent.agent import Agent
        try:
            ag = Agent(storage=self.storage)
        except Exception as e:
            console.print(f"[red]初始化失败: {e}[/red]")
            return

        console.print(f"\n[bold magenta]🤖 Agent 启动[/bold magenta]")
        console.print(f"  任务: [cyan]{arg}[/cyan]\n")

        # 步骤回调
        def on_step(step_type: str, content: str) -> None:
            if step_type == "thought":
                console.print(f"  [dim italic]💭 {content}[/dim italic]")
            elif step_type == "tool":
                console.print(f"  [yellow]🔧 调用工具[/yellow] [bold]{content}[/bold]")
            elif step_type == "result":
                # 截断显示
                preview = content[:300] + ("..." if len(content) > 300 else "")
                console.print(f"  [green]✓ 返回结果[/green] [dim]({len(content)} 字符)[/dim]")
                console.print(f"  [dim]{preview}[/dim]\n")
            elif step_type == "error":
                console.print(f"  [red]✗ {content}[/red]\n")
            elif step_type == "done":
                console.print(f"  [bold magenta]✓ 任务完成[/bold magenta]\n")

        try:
            with console.status("[bold yellow]Agent 思考中...[/bold yellow]", spinner="dots"):
                pass
            result = ag.run(arg, on_step=on_step)
            console.print(Panel(
                Text(result),
                title="[bold magenta]🎯 最终答案[/bold magenta]",
                border_style="magenta",
                padding=(1, 2),
            ))
            # 宠物经验埋点：agent 行为
            self._pet_gain_exp(15, "agent")
        except Exception as e:
            err_msg = str(e).replace("[", "\\[")
            err_lower = err_msg.lower()
            # 识别网络类错误，给出排查建议
            is_network_err = any(
                kw in err_lower
                for kw in ("connection", "apiconnection", "apitimeout", "timeout", "5xx", "502", "503", "504")
            )
            console.print(f"[red]Agent 执行失败: {type(e).__name__}: {err_msg}[/red]")
            if is_network_err:
                console.print(
                    "\n[yellow]⚠️ 这是网络连接错误，常见原因：[/yellow]\n"
                    "  - 网络不稳定或已断开\n"
                    "  - VPN/代理未开启或已掉线\n"
                    "  - DNS 解析失败\n"
                    "  - Agnes AI 服务端瞬时不可用\n\n"
                    "[bold]建议：[/bold]\n"
                    "  1. 检查网络连接是否正常\n"
                    "  2. 确认 VPN/代理已开启\n"
                    "  3. 稍后重试（已自动重试 3 次，可能仍失败）\n"
                    "  4. 用 [cyan]/stats[/cyan] 查看知识库状态，确认 LLM 在线"
                )

    def _cmd_smart(self, arg: str) -> None:
        """智能路由：/smart <自然语言描述> — AI 自动选功能执行。

        示例:
            /smart 总结 862e0973          → 自动调 /report
            /smart 对比 862e 和 02fd      → 自动调 /compare
            /smart 分析 数据.xlsx          → 自动调 /analyze
            /smart 阅读 862e0973          → 自动调 /read
            /smart 找骨灰安置政策并总结    → 自动调 /agent
        """
        if not arg:
            console.print("[yellow]用法: /smart <自然语言描述>[/yellow]")
            console.print("[dim]示例:[/dim]")
            console.print("  [cyan]/smart 总结 862e0973[/cyan]")
            console.print("  [cyan]/smart 对比 862e 和 02fd[/cyan]")
            console.print("  [cyan]/smart 分析 ~/Desktop/数据.xlsx[/cyan]")
            console.print("  [cyan]/smart 找骨灰安置政策并总结[/cyan]")
            console.print("\n[dim]AI 会根据描述自动选择 /report /compare /analyze /read /agent[/dim]")
            return
        if not self.llm_available:
            console.print("[red]LLM 未配置[/red]")
            return

        # 让 LLM 判断该用什么命令
        router_prompt = f"""根据用户描述，判断该用哪个命令。只输出命令行，不要解释。

可用命令：
- /report <文档ID>          → 生成文档分析报告（当用户说"总结/报告/分析某个文档"时）
- /compare <A> <B>          → 对比两个文档或文件（当用户说"对比/比较"时）
- /analyze <文件路径>        → 分析数据表（当用户说"分析数据表/Excel/CSV"时）
- /read <文档ID>            → 智能阅读（当用户说"阅读/看/读某个文档"时）
- /agent <任务描述>          → Agent 模式（当任务复杂，需要搜索+多步操作时）
- /search <关键词>           → 简单搜索（当用户只想"找/搜索"内容时）

用户描述: {arg}

请输出最合适的命令（含参数），只输出一行，不要解释："""

        try:
            llm = get_llm()
            messages = [
                {"role": "system", "content": "你是命令路由助手，只输出命令，不解释。"},
                {"role": "user", "content": router_prompt},
            ]
            with console.status("[bold yellow]🤔 判断该用什么命令...[/bold yellow]", spinner="dots"):
                cmd_line = llm.chat(messages, temperature=0.0, max_tokens=100).strip()

            # 清理可能的 markdown 标记
            cmd_line = cmd_line.strip("`").strip()
            if not cmd_line.startswith("/"):
                # 如果 LLM 没输出 / 开头，尝试提取
                import re
                m = re.search(r"(/\w+[\s\S]*)", cmd_line)
                if m:
                    cmd_line = m.group(1)
                else:
                    console.print(f"[red]无法识别命令: {cmd_line}[/red]")
                    return

            console.print(f"[green]✓ 智能路由[/green] → [bold cyan]{cmd_line}[/bold cyan]\n")
            # 宠物经验埋点：smart 行为
            self._pet_gain_exp(8, "smart")
            # 执行路由到的命令
            self._handle_command(cmd_line)
        except LLMError as e:
            err_msg = str(e).replace("[", "\\[")
            console.print(f"[red]路由失败:[/red] {err_msg}")
            # 404 通常意味着模型下线了，给出排查建议
            if "404" in err_msg or "NotFound" in err_msg:
                console.print("\n[yellow]💡 可能原因：模型已下线或 API 地址变更[/yellow]")
                console.print("[dim]  1. 检查模型名是否正确：[/dim]")
                console.print(f"[dim]     cat .env | grep LLM_MODEL[/dim]")
                console.print("[dim]  2. 尝试备用模型 agnes-1.5-flash：[/dim]")
                console.print(f"[dim]     sed -i '' 's/LLM_MODEL=.*/LLM_MODEL=agnes-1.5-flash/' .env[/dim]")
            console.print("[dim]  你也可以直接用对应命令：/search /report /compare /analyze /read /agent[/dim]")

    def _cmd_theme(self, arg: str) -> None:
        """切换主题：/theme [claude|mimo|minimal]"""
        themes = list_themes()
        if not arg:
            # 无参数：列出所有主题
            cur = get_theme()
            console.print(f"\n[bold]可用主题[/bold] [dim]（当前: {cur.label}）[/dim]\n")
            for name, t in themes.items():
                marker = "[green]✓[/green]" if name == cur.name else " "
                console.print(
                    f"  {marker} [cyan]{name:10s}[/cyan] "
                    f"[bold]{t.label}[/bold]  [dim]{t.desc}[/dim]"
                )
            console.print("\n[dim]用法: /theme claude  或  /theme mimo  或  /theme minimal[/dim]\n")
            return

        name = arg.strip().lower()
        try:
            new_t = set_theme(name)
        except ValueError as e:
            console.print(f"[red]{e}[/red]")
            return
        # 更新输入框样式
        global _INPUT_STYLE
        _INPUT_STYLE = PtStyle.from_dict({
            "prompt": new_t.colors["prompt"],
            "completion-menu.completion": "bg:ansiblack fg:ansiwhite",
            "completion-menu.completion.current": f"bg:{new_t.colors['primary']} fg:ansiblack bold",
            "completion-menu.meta.completion": "bg:ansiblue fg:ansiwhite",
            "completion-menu.meta.completion.current": "bg:ansicyan fg:ansiblack bold",
            "completion-menu.progress-button": "bg:ansiblue",
            "completion-menu.progress-bar": "bg:ansiblue",
        })
        console.print(f"[green]✓ 已切换主题[/green] [bold]{new_t.label}[/bold]")
        console.print(f"[dim]{new_t.desc}[/dim]\n")
        # 重新渲染欢迎面板
        stats = self.storage.stats()
        _render_welcome_panel(stats, self.llm_available, pet=self.pet)

    # ---- 记忆管理 ----

    def _cmd_memory(self, arg: str) -> None:
        """记忆管理子命令：/memory [show|clear|add|tasks|format|style|topic|region|task|workflow]。

        - /memory                    显示记忆概览
        - /memory show               同上，显示完整 profile
        - /memory clear              清空所有记忆（profile + tasks + workflow）
        - /memory add <描述>          添加一条任务到记忆
        - /memory tasks              列出所有未完成任务
        - /memory format <值>        设置格式偏好（table/list/prose/auto 或留空清除）
        - /memory style <值>         设置风格偏好（auto/scholar/warrior/artisan）
        - /memory topic add <主题>    手动添加关注主题
        - /memory topic remove <主题> 删除指定主题
        - /memory topic clear        清空所有主题
        - /memory region add <地区>    手动添加关注地区
        - /memory region remove <地区> 删除指定地区
        - /memory region clear        清空所有地区
        - /memory task done <id>      标记任务为已完成
        - /memory task cancel <id>    取消任务
        - /memory task reopen <id>    重开任务（pending）
        - /memory task start <id>     标记任务为进行中
        - /memory task delete <id>    彻底删除任务
        - /memory workflow clear      清空工作流模式记录
        - /memory workflow suggest on|off  启用/关闭下一步推荐
        """
        if self.memory_store is None:
            console.print("[yellow]记忆模块未初始化（需要先领养宠物）[/yellow]")
            return

        parts = arg.split(maxsplit=1) if arg else []
        sub = parts[0].lower() if parts else ""
        sub_arg = parts[1].strip() if len(parts) > 1 else ""

        # 子命令缩写（支持 /m c = /memory clear, /m f table = /memory format table）
        SUB_ALIASES = {
            "c": "clear", "cl": "clear",
            "f": "format", "fmt": "format",
            "s": "style", "sty": "style",
            "t": "tasks", "ts": "tasks",
            "top": "topic", "tp": "topic",
            "reg": "region", "r": "region",
            "ta": "task", "tk": "task",
            "w": "workflow", "wf": "workflow",
            "a": "add", "sh": "show",
        }
        sub = SUB_ALIASES.get(sub, sub)

        if sub in ("", "show"):
            self._memory_show()
        elif sub == "clear":
            self._memory_clear()
        elif sub == "add":
            if not sub_arg:
                console.print("[yellow]用法: /memory add <任务描述>[/yellow]")
                return
            self._memory_add_task(sub_arg)
        elif sub == "tasks":
            self._memory_show_tasks()
        elif sub == "format":
            self._memory_set_format(sub_arg)
        elif sub == "style":
            self._memory_set_style(sub_arg)
        elif sub == "topic":
            self._memory_manage_topic(sub_arg)
        elif sub == "region":
            self._memory_manage_region(sub_arg)
        elif sub == "task":
            self._memory_manage_task(sub_arg)
        elif sub == "workflow":
            self._memory_manage_workflow(sub_arg)
        else:
            console.print("[bold]记忆管理[/bold] [dim](/memory 子命令)[/dim]\n")
            console.print("  [cyan]/memory[/cyan]                    显示记忆概览")
            console.print("  [cyan]/memory show[/cyan]               显示完整 profile")
            console.print("  [cyan]/memory clear[/cyan]              清空所有记忆")
            console.print("  [cyan]/memory add <描述>[/cyan]         添加一条任务")
            console.print("  [cyan]/memory tasks[/cyan]              列出未完成任务")
            console.print("  [cyan]/memory format <值>[/cyan]        设置格式 (table/list/prose/auto)")
            console.print("  [cyan]/memory style <值>[/cyan]         设置风格 (auto/scholar/warrior/artisan)")
            console.print("  [cyan]/memory topic add <主题>[/cyan]    添加关注主题")
            console.print("  [cyan]/memory topic remove <主题>[/cyan] 删除主题")
            console.print("  [cyan]/memory topic clear[/cyan]        清空所有主题")
            console.print("  [cyan]/memory region add <地区>[/cyan]    添加关注地区")
            console.print("  [cyan]/memory region remove <地区>[/cyan] 删除地区")
            console.print("  [cyan]/memory region clear[/cyan]        清空所有地区")
            console.print("  [cyan]/memory task done <id>[/cyan]      标记任务完成")
            console.print("  [cyan]/memory task cancel <id>[/cyan]    取消任务")
            console.print("  [cyan]/memory task reopen <id>[/cyan]    重开任务")
            console.print("  [cyan]/memory task delete <id>[/cyan]    彻底删除任务")
            console.print("  [cyan]/memory workflow clear[/cyan]      清空工作流模式")
            console.print("  [cyan]/memory workflow suggest on|off[/cyan]  开关推荐")

    def _memory_set_format(self, value: str) -> None:
        """设置格式偏好。"""
        from core.memory.profile import VALID_FORMATS
        mgr = ProfileManager(self.memory_store)
        value = value.strip().lower()
        # 允许 "none"/"clear"/"默认" 表示清除
        if value in ("none", "clear", "默认", "auto"):
            value = "auto" if value == "auto" else ""
        if value not in VALID_FORMATS:
            console.print(
                f"[red]无效的格式: '{value}'[/red]  "
                f"允许: [cyan]table / list / prose / auto[/cyan] 或留空清除"
            )
            return
        try:
            mgr.update_format_preference(value)
            label = value if value else "（已清除）"
            console.print(f"[green]✓ 格式偏好已设置: [cyan]{label}[/cyan][/green]")
        except ValueError as e:
            console.print(f"[red]{e}[/red]")

    def _memory_set_style(self, value: str) -> None:
        """设置风格偏好。"""
        from core.memory.profile import VALID_STYLES
        mgr = ProfileManager(self.memory_store)
        value = value.strip().lower()
        if value not in VALID_STYLES:
            console.print(
                f"[red]无效的风格: '{value}'[/red]  "
                f"允许: [cyan]auto / scholar / warrior / artisan[/cyan]"
            )
            return
        try:
            mgr.update_style_preference(value)
            labels = {"auto": "自动", "scholar": "学者", "warrior": "战士", "artisan": "工匠"}
            console.print(f"[green]✓ 风格偏好已设置: [cyan]{labels[value]}[/cyan][/green]")
        except ValueError as e:
            console.print(f"[red]{e}[/red]")

    def _memory_manage_topic(self, arg: str) -> None:
        """主题管理：/memory topic [add|remove|clear] [主题]"""
        parts = arg.split(maxsplit=1) if arg else []
        action = parts[0].lower() if parts else ""
        topic = parts[1].strip() if len(parts) > 1 else ""

        if action == "":
            console.print("[yellow]用法: /memory topic <add|remove|clear> [主题][/yellow]")
            console.print("  [cyan]/memory topic add <主题>[/cyan]    添加关注主题")
            console.print("  [cyan]/memory topic remove <主题>[/cyan] 删除指定主题")
            console.print("  [cyan]/memory topic clear[/cyan]        清空所有主题")
            return

        mgr = ProfileManager(self.memory_store)

        if action == "add":
            if not topic:
                console.print("[yellow]用法: /memory topic add <主题>[/yellow]")
                return
            try:
                added = mgr.add_topic(topic)
                if added:
                    console.print(f"[green]✓ 已添加主题: [magenta]{topic}[/magenta][/green]")
                else:
                    console.print(f"[yellow]主题已存在（或被包含）: {topic}[/yellow]")
            except ValueError as e:
                console.print(f"[red]{e}[/red]")

        elif action == "remove":
            if not topic:
                console.print("[yellow]用法: /memory topic remove <主题>[/yellow]")
                return
            removed = mgr.remove_topic(topic)
            if removed:
                console.print(f"[green]✓ 已删除主题: [magenta]{topic}[/magenta][/green]")
            else:
                console.print(f"[yellow]未找到主题: {topic}[/yellow]")

        elif action == "clear":
            count = mgr.clear_topics()
            console.print(f"[green]✓ 已清空 {count} 个主题[/green]")

        else:
            console.print(f"[red]未知操作: '{action}'[/red]  允许: add / remove / clear")

    def _memory_manage_region(self, arg: str) -> None:
        """地区管理：/memory region [add|remove|clear] [地区]"""
        parts = arg.split(maxsplit=1) if arg else []
        action = parts[0].lower() if parts else ""
        region = parts[1].strip() if len(parts) > 1 else ""

        if action == "":
            console.print("[yellow]用法: /memory region <add|remove|clear> [地区][/yellow]")
            console.print("  [cyan]/memory region add <地区>[/cyan]    添加关注地区")
            console.print("  [cyan]/memory region remove <地区>[/cyan] 删除指定地区")
            console.print("  [cyan]/memory region clear[/cyan]        清空所有地区")
            return

        mgr = ProfileManager(self.memory_store)

        if action == "add":
            if not region:
                console.print("[yellow]用法: /memory region add <地区>[/yellow]")
                return
            try:
                added = mgr.add_region(region)
                if added:
                    console.print(f"[green]✓ 已添加地区: [magenta]{region}[/magenta][/green]")
                else:
                    console.print(f"[yellow]地区已存在: {region}[/yellow]")
            except ValueError as e:
                console.print(f"[red]{e}[/red]")

        elif action == "remove":
            if not region:
                console.print("[yellow]用法: /memory region remove <地区>[/yellow]")
                return
            removed = mgr.remove_region(region)
            if removed:
                console.print(f"[green]✓ 已删除地区: [magenta]{region}[/magenta][/green]")
            else:
                console.print(f"[yellow]未找到地区: {region}[/yellow]")

        elif action == "clear":
            count = mgr.clear_regions()
            console.print(f"[green]✓ 已清空 {count} 个地区[/green]")

        else:
            console.print(f"[red]未知操作: '{action}'[/red]  允许: add / remove / clear")

    def _memory_manage_task(self, arg: str) -> None:
        """任务状态管理：/memory task [done|cancel|reopen|start|delete] <id>"""
        parts = arg.split(maxsplit=1) if arg else []
        action = parts[0].lower() if parts else ""
        task_id = parts[1].strip() if len(parts) > 1 else ""

        if action == "":
            console.print("[yellow]用法: /memory task <done|cancel|reopen|start|delete> <id>[/yellow]")
            console.print("  [cyan]/memory task done <id>[/cyan]      标记为已完成")
            console.print("  [cyan]/memory task cancel <id>[/cyan]    取消任务")
            console.print("  [cyan]/memory task reopen <id>[/cyan]    重开任务（pending）")
            console.print("  [cyan]/memory task start <id>[/cyan]     标记为进行中")
            console.print("  [cyan]/memory task delete <id>[/cyan]    彻底删除任务")
            return

        if not task_id:
            console.print(f"[yellow]用法: /memory task {action} <id>[/yellow]")
            return

        mgr = TaskManager(self.memory_store)

        # 允许 task_id 简写（前缀匹配）
        all_tasks = mgr.get_all_tasks()
        matched = [t for t in all_tasks if t.id.startswith(task_id) or task_id in t.id]
        if not matched:
            console.print(f"[red]未找到任务: {task_id}[/red]")
            console.print("[dim]用 /memory tasks 查看任务列表[/dim]")
            return
        if len(matched) > 1:
            console.print(f"[yellow]ID 前缀匹配多个任务，请提供更完整的 ID[/yellow]")
            for t in matched[:5]:
                console.print(f"  [dim]{t.id}[/dim]  {t.description}")
            return
        full_id = matched[0].id

        status_map = {
            "done": "completed",
            "cancel": "cancelled",
            "reopen": "pending",
            "start": "in_progress",
        }

        if action in status_map:
            new_status = status_map[action]
            ok = mgr.update_task(full_id, new_status)
            if ok:
                labels = {
                    "completed": "已完成",
                    "cancelled": "已取消",
                    "pending": "已重开",
                    "in_progress": "进行中",
                }
                console.print(f"[green]✓ 任务状态: [cyan]{labels[new_status]}[/cyan][/green]")
                console.print(f"  [dim]{full_id}[/dim]")
            else:
                console.print(f"[red]更新失败（状态无效或任务不存在）[/red]")
        elif action == "delete":
            ok = mgr.delete_task(full_id)
            if ok:
                console.print(f"[green]✓ 已删除任务[/green] [dim]({full_id})[/dim]")
            else:
                console.print(f"[red]删除失败：未找到任务[/red]")
        else:
            console.print(f"[red]未知操作: '{action}'[/red]")
            console.print("[dim]允许: done / cancel / reopen / start / delete[/dim]")

    def _memory_manage_workflow(self, arg: str) -> None:
        """工作流管理：/memory workflow [clear|suggest on|off]"""
        parts = arg.split(maxsplit=1) if arg else []
        action = parts[0].lower() if parts else ""

        if action == "":
            console.print("[yellow]用法: /memory workflow <clear|suggest> [参数][/yellow]")
            console.print("  [cyan]/memory workflow clear[/cyan]            清空所有模式记录")
            console.print("  [cyan]/memory workflow suggest on|off[/cyan]    启用/关闭下一步推荐")
            return

        from core.memory.workflow import WorkflowTracker
        tracker = WorkflowTracker(self.memory_store)

        if action == "clear":
            count = tracker.clear_patterns()
            console.print(f"[green]✓ 已清空 {count} 个工作流模式[/green]")
        elif action == "suggest":
            val = parts[1].strip().lower() if len(parts) > 1 else ""
            if val in ("on", "true", "1", "开", "启用"):
                tracker.set_suggestions_enabled(True)
                console.print("[green]✓ 已启用下一步推荐[/green]")
            elif val in ("off", "false", "0", "关", "关闭"):
                tracker.set_suggestions_enabled(False)
                console.print("[green]✓ 已关闭下一步推荐[/green]")
            elif val == "":
                # 无参数：显示当前状态
                data = self.memory_store.get_data() if self.memory_store else {}
                enabled = data.get("workflow", {}).get("suggestions_enabled", True)
                state = "[green]已启用[/green]" if enabled else "[red]已关闭[/red]"
                console.print(f"  工作流推荐: {state}")
                console.print("[dim]  用法: /memory workflow suggest on|off[/dim]")
            else:
                console.print(f"[red]无效值: '{val}'[/red]  允许: on / off")
        else:
            console.print(f"[red]未知操作: '{action}'[/red]  允许: clear / suggest")

    def _memory_show(self) -> None:
        """显示记忆概览。"""
        data = self.memory_store.get_data()
        profile = data.get("profile", {})
        tasks = data.get("tasks", [])
        workflow = data.get("workflow", {})

        console.print("\n[bold cyan]🧠 记忆概览[/bold cyan]\n")

        # Profile 区块
        preferred_style = profile.get("preferred_style", "auto")
        style_label = {"scholar": "学者", "warrior": "战士", "artisan": "工匠", "auto": "自动"}.get(
            preferred_style, preferred_style)
        preferred_format = profile.get("preferred_format", "")
        format_label = {
            "table": "表格", "list": "列表", "prose": "散文", "auto": "自动", "": "（未设置）"
        }.get(preferred_format, preferred_format)
        console.print(f"  [bold]用户偏好[/bold]")
        console.print(f"    风格: [cyan]{style_label}[/cyan]")
        console.print(f"    格式: [cyan]{format_label}[/cyan]  [dim](/memory format 设置)[/dim]")
        topics = profile.get("focus_topics", [])
        if topics:
            console.print(f"    关注主题: [magenta]{'、'.join(topics[:5])}[/magenta]"
                          + (f" [dim]等 {len(topics)} 个[/dim]" if len(topics) > 5 else ""))
        regions = profile.get("focus_regions", [])
        if regions:
            console.print(f"    关注地区: [magenta]{'、'.join(regions[:5])}[/magenta]"
                          + (f" [dim]等 {len(regions)} 个[/dim]" if len(regions) > 5 else ""))
        console.print(f"    互动次数: [cyan]{profile.get('interaction_count', 0)}[/cyan]")
        console.print(f"    最后活跃: [dim]{profile.get('last_active', '（无）')}[/dim]")

        # Tasks 区块
        active = [t for t in tasks if t.get("status") != "completed"]
        console.print(f"\n  [bold]任务[/bold] [dim]（{len(active)} 个未完成 / 共 {len(tasks)} 个）[/dim]")
        if active:
            for t in active[:5]:
                console.print(f"    - [cyan]{t['id'][:12]}[/cyan] {t['description']} "
                              f"[dim]({t.get('status', 'pending')})[/dim]")

        # Workflow 区块
        patterns = workflow.get("patterns", [])
        console.print(f"\n  [bold]工作流[/bold]")
        console.print(f"    模式数: [cyan]{len(patterns)}[/cyan]")
        console.print(f"    推荐启用: [cyan]{workflow.get('suggestions_enabled', True)}[/cyan]")
        if patterns:
            top = sorted(patterns, key=lambda p: p.get("count", 0), reverse=True)[:3]
            for p in top:
                seq = p.get("sequence", [])
                console.print(f"    [dim]{' → '.join(seq)} ×{p.get('count', 0)}[/dim]")
        console.print()

    def _memory_clear(self) -> None:
        """清空所有记忆。"""
        confirm = Prompt.ask(
            "确定清空所有记忆（profile + tasks + workflow）？",
            choices=["y", "n"], default="n",
        )
        if confirm != "y":
            console.print("[dim]已取消[/dim]")
            return
        self.memory_store.clear()
        console.print("[green]✓ 已清空所有记忆[/green]")

    def _memory_add_task(self, description: str) -> None:
        """添加一条任务到记忆。"""
        try:
            mgr = TaskManager(self.memory_store)
            task_id = mgr.add_task(description)
            console.print(f"[green]✓ 已添加任务[/green] [dim]({task_id})[/dim]")
            console.print(f"  [cyan]{description}[/cyan]")
        except Exception as e:
            err_msg = str(e).replace("[", "\\[")
            console.print(f"[red]添加任务失败: {err_msg}[/red]")

    def _memory_show_tasks(self) -> None:
        """列出所有未完成任务。"""
        try:
            mgr = TaskManager(self.memory_store)
            tasks = mgr.get_active_tasks()
        except Exception as e:
            err_msg = str(e).replace("[", "\\[")
            console.print(f"[red]读取任务失败: {err_msg}[/red]")
            return
        if not tasks:
            console.print("[yellow]暂无未完成任务[/yellow]  [dim]用 /memory add <描述> 添加[/dim]")
            return
        console.print(f"\n[bold]未完成任务[/bold] [dim]（共 {len(tasks)} 个）[/dim]\n")
        table = Table(show_lines=False, border_style="cyan")
        table.add_column("ID", style="cyan", width=14)
        table.add_column("描述", style="white")
        table.add_column("状态", style="yellow")
        table.add_column("创建时间", style="dim")
        for t in tasks:
            table.add_row(t.id[:12], t.description, t.status, t.created_at[:19])
        console.print(table)
        console.print()

    def _cmd_clear(self) -> None:
        """清空对话历史。"""
        n = len(self.history)
        self.history.clear()
        # 同时清掉数据分析追问 + 阅读模式状态
        cleared = []
        if self.current_analysis is not None:
            self.current_analysis = None
            cleared.append("数据分析")
        if self.reader is not None:
            self.reader.close()
            self.reader = None
            cleared.append("阅读模式")
        if cleared:
            console.print(
                f"[green]✓ 已清空对话历史[/green] [dim]({n} 条记录 + {'/'.join(cleared)})[/dim]"
            )
        else:
            console.print(f"[green]✓ 已清空对话历史[/green] [dim]({n} 条记录)[/dim]")

    # ---- 知识图谱 ----

    def _cmd_graph(self, arg: str) -> None:
        """知识图谱子命令：/graph <build|stats|neighbors|export|clear> [参数]"""
        from core.graph.store import GraphStore

        if not arg:
            console.print("[yellow]用法:[/yellow]")
            console.print("  [cyan]/graph stats[/cyan]              图谱统计")
            console.print("  [cyan]/graph build[/cyan] [--force]    构建图谱")
            console.print("  [cyan]/graph neighbors <名称>[/cyan]   查询邻居")
            console.print("  [cyan]/graph export[/cyan]             导出 HTML")
            console.print("  [cyan]/graph clear[/cyan]              清空图谱")
            return

        # 拆出子命令和参数
        parts = arg.split(maxsplit=1)
        sub = parts[0].lower()
        sub_arg = parts[1].strip() if len(parts) > 1 else ""

        gs = GraphStore()

        if sub == "stats":
            self._graph_stats(gs)
        elif sub == "build":
            self._graph_build(gs, sub_arg)
        elif sub in ("neighbor", "neighbors", "nb"):
            if not sub_arg:
                console.print("[yellow]用法: /graph neighbors <节点名称>[/yellow]")
                return
            self._graph_neighbors(gs, sub_arg)
        elif sub == "export":
            self._graph_export(gs)
        elif sub == "clear":
            self._graph_clear(gs)
        elif sub in ("delete", "del", "rm"):
            self._graph_delete_node(gs, sub_arg)
        elif sub in ("rename", "mv"):
            self._graph_rename_node(gs, sub_arg)
        else:
            console.print(f"[red]未知子命令:[/red] {sub}")
            console.print("[dim]可用: stats / build / neighbors / export / clear / delete / rename[/dim]")

    def _graph_stats(self, gs) -> None:
        """图谱统计。"""
        s = gs.stats()
        if s["nodes"] == 0:
            console.print("[yellow]图谱为空[/yellow]  [dim]用 /graph build 构建[/dim]")
            return

        console.print("\n[bold]📊 知识图谱统计[/bold]\n")
        console.print(f"  节点总数:  [cyan]{s['nodes']}[/cyan]")
        console.print(f"  边总数:    [cyan]{s['edges']}[/cyan]")

        type_names = {"document": "政策文档", "region": "地区", "agency": "机构", "topic": "主题"}
        if s["nodes_by_type"]:
            console.print("\n  [bold]按节点类型:[/bold]")
            for ntype, cnt in sorted(s["nodes_by_type"].items(), key=lambda x: -x[1]):
                console.print(f"    {type_names.get(ntype, ntype):8s} {cnt}")

        rel_names = {"published_in": "发布于", "published_by": "发布机构", "covers_topic": "涉及主题"}
        if s["edges_by_relation"]:
            console.print("\n  [bold]按关系类型:[/bold]")
            for rel, cnt in sorted(s["edges_by_relation"].items(), key=lambda x: -x[1]):
                console.print(f"    {rel_names.get(rel, rel):8s} {cnt}")

        # 节点列表（前 15 个）
        nodes = gs.list_nodes()
        if nodes:
            console.print(f"\n  [bold]节点列表[/bold] [dim]（前 15 个，按连接数排序）[/dim]")
            table = Table(show_lines=False)
            table.add_column("名称", style="white")
            table.add_column("类型", style="cyan", width=8)
            table.add_column("连接数", justify="right", style="yellow")
            table.add_column("关联文档", justify="right", style="magenta")
            for n in nodes[:15]:
                table.add_row(
                    n["label"],
                    type_names.get(n["type"], n["type"]),
                    str(n["degree"]),
                    str(n["doc_count"]),
                )
            console.print(table)
        console.print()

    def _graph_build(self, gs, arg: str) -> None:
        """构建图谱：/graph build [--force] [-d ID] [-n N]"""
        from core.graph.extractor import GraphExtractor
        from core.llm.client import LLMError

        if not self.llm_available:
            console.print("[red]LLM 未配置，无法抽取实体关系[/red]")
            return

        # 简单解析参数
        force = "--force" in arg or "-f" in arg
        doc_id_filter = None
        limit = None
        # 支持 -d ID / -n N
        toks = arg.split()
        i = 0
        while i < len(toks):
            if toks[i] in ("-d", "--doc-id") and i + 1 < len(toks):
                doc_id_filter = toks[i + 1]
                i += 2
            elif toks[i] in ("-n", "--limit") and i + 1 < len(toks):
                try:
                    limit = int(toks[i + 1])
                except ValueError:
                    pass
                i += 2
            else:
                i += 1

        if force:
            gs.clear()
            console.print("[yellow]已清空旧图谱[/yellow]")

        # 选目标文档
        all_docs = self.storage.list_documents(limit=10000)
        if doc_id_filter:
            target_docs = [d for d in all_docs if d.id.startswith(doc_id_filter)]
            if not target_docs:
                console.print(f"[red]未找到文档: {doc_id_filter}[/red]")
                return
        else:
            # 跳过已抽取的
            existing_doc_ids = set()
            for n, d in gs.graph.nodes(data=True):
                existing_doc_ids.update(d.get("doc_ids", []))
            target_docs = [d for d in all_docs if d.id not in existing_doc_ids]
            if limit:
                target_docs = target_docs[:limit]

        if not target_docs:
            console.print("[yellow]没有需要抽取的文档[/yellow]  [dim]用 --force 重建[/dim]")
            return

        console.print(f"\n[bold]开始构建图谱[/bold] · 共 {len(target_docs)} 个文档\n")

        try:
            extractor = GraphExtractor()
        except LLMError as e:
            console.print(f"[red]LLM 初始化失败:[/red] {e}")
            return

        success, fail = 0, 0
        for i, doc in enumerate(target_docs, 1):
            chunks = self.storage.get_chunks(doc.id)
            content = "\n".join(c.content for c in chunks)
            title_display = doc.title[:50]
            content_preview = content.strip()[:200]

            # 预检：内容过短或无实质信息的文档，跳过 LLM 调用
            if len(content_preview) < 50:
                console.print(f"[{i}/{len(target_docs)}] [cyan]{title_display}[/cyan]")
                console.print(f"  [dim]跳过（内容过短 {len(content)} 字）[/dim]")
                fail += 1
                continue

            console.print(f"[{i}/{len(target_docs)}] [cyan]{title_display}[/cyan]")
            try:
                result = extractor.extract_from_document(
                    doc_id=doc.id, doc_title=doc.title, content=content,
                )
                if result.entities:
                    gs.add_extraction(result)
                    gs.save()
                    console.print(
                        f"  [green]✓[/green] {len(result.entities)} 实体 · {len(result.relations)} 关系"
                    )
                    success += 1
                else:
                    console.print("  [dim]该文档无可抽取的实体（内容可能非政策/无实质信息）[/dim]")
                    fail += 1
            except Exception as e:
                err_msg = str(e).replace("[", "\\[")
                console.print(f"  [red]失败: {type(e).__name__}: {err_msg}[/red]")
                fail += 1

        s = gs.stats()
        console.print(
            f"\n[bold]完成[/bold] · 抽取 {success}/{len(target_docs)} · "
            f"图谱 {s['nodes']} 节点 / {s['edges']} 边\n"
        )
        # 宠物经验埋点：graph_build 行为
        if success > 0:
            self._pet_gain_exp(30, "graph_build")

    def _graph_neighbors(self, gs, name: str) -> None:
        """查询节点邻居：/graph neighbors <名称>"""
        if name not in gs.graph:
            # 模糊匹配
            matches = gs.search_nodes(name)
            if not matches:
                console.print(f"[red]未找到节点: {name}[/red]")
                return
            console.print(f"[yellow]找到 {len(matches)} 个匹配:[/yellow]")
            for m in matches[:5]:
                console.print(f"  [cyan]{m['label']}[/cyan] [dim]({m['type']}, 连接 {m['degree']})[/dim]")
            console.print(f"\n[dim]重试: /graph neighbors \"{matches[0]['label']}\"[/dim]")
            return

        neighbors = gs.neighbors(name)
        node_data = gs.graph.nodes[name]
        type_names = {"document": "政策文档", "region": "地区", "agency": "机构", "topic": "主题"}

        console.print(
            f"\n[bold cyan]{name}[/bold cyan] "
            f"[dim]({type_names.get(node_data.get('type', ''), '')})[/dim]"
        )
        console.print(
            f"  关联文档: {node_data.get('doc_count', 0)} · 连接数: {len(neighbors)}\n"
        )

        if neighbors:
            table = Table(show_lines=False)
            table.add_column("邻居节点", style="white")
            table.add_column("类型", style="cyan", width=10)
            table.add_column("关系", style="yellow")
            for nb in neighbors:
                table.add_row(
                    nb["node"],
                    type_names.get(nb["type"], nb["type"]),
                    nb["relation_label"],
                )
            console.print(table)
        console.print()

    def _graph_export(self, gs) -> None:
        """导出 HTML 可视化：/graph export"""
        import webbrowser
        from core.graph.visualizer import generate_html

        if gs.graph.number_of_nodes() == 0:
            console.print("[yellow]图谱为空[/yellow]  [dim]先 /graph build[/dim]")
            return

        html_path = generate_html(gs)
        s = gs.stats()
        console.print(f"\n[green]✓ 已导出[/green]")
        console.print(f"  文件: {html_path}")
        console.print(f"  节点: {s['nodes']} · 边: {s['edges']}")

        # 自动打开浏览器
        file_url = html_path.as_uri()
        webbrowser.open(file_url)
        console.print(f"  [green]✓ 已在浏览器中打开[/green]\n")

    def _graph_clear(self, gs) -> None:
        """清空图谱：/graph clear"""
        gs.clear()
        console.print("[green]✓ 已清空知识图谱[/green]")

    def _graph_delete_node(self, gs, name: str) -> None:
        """删除图谱节点：/graph delete <节点名>"""
        if not name:
            console.print("[yellow]用法: /graph delete <节点名>[/yellow]")
            console.print("[dim]用 /graph neighbors <节点> 查看节点[/dim]")
            return
        if name not in gs.graph:
            console.print(f"[red]节点不存在: {name}[/red]")
            return
        # 显示节点信息供确认
        node_data = gs.graph.nodes[name]
        degree = gs.graph.degree(name)
        console.print(f"  [dim]类型: {node_data.get('type', '?')} · 连接: {degree}[/dim]")
        confirm = Prompt.ask(
            f"确定删除节点 [cyan]{name}[/cyan] 及其 {degree} 条连边？",
            choices=["y", "n"], default="n",
        )
        if confirm != "y":
            console.print("[dim]已取消[/dim]")
            return
        ok = gs.delete_node(name)
        if ok:
            gs.save()
            console.print(f"[green]✓ 已删除节点: {name}[/green]")
        else:
            console.print(f"[red]删除失败[/red]")

    def _graph_rename_node(self, gs, arg: str) -> None:
        """重命名图谱节点：/graph rename <旧名> <新名>"""
        if not arg:
            console.print("[yellow]用法: /graph rename <旧名> <新名>[/yellow]")
            return
        parts = arg.split(maxsplit=1)
        if len(parts) < 2:
            console.print("[yellow]用法: /graph rename <旧名> <新名>[/yellow]")
            return
        old_name, new_name = parts[0].strip(), parts[1].strip()
        if not new_name:
            console.print("[yellow]新名称不能为空[/yellow]")
            return
        ok = gs.rename_node(old_name, new_name)
        if ok:
            gs.save()
            console.print(f"[green]✓ 已重命名: [/green][dim]{old_name} → [/dim][cyan]{new_name}[/cyan]")
        else:
            console.print(f"[red]重命名失败（节点不存在或新名称已存在）[/red]")

    # ---- AI 对话 ----

    def _handle_chat(self, user_input: str) -> None:
        """AI 对话（带多轮历史 + RAG 检索 + Spinner 动画）。"""
        if not self.llm_available:
            console.print("[red]LLM 未配置，无法问答[/red]")
            console.print("[dim]请在 .env 中设置 AGNES_API_KEY[/dim]")
            return

        # 优先走 PetAdministrator（编排检索 + 重排 + 记忆 + 人格 + 引用）
        # 失败时降级到下方原有 RAG 逻辑
        if self.administrator is not None and self.current_analysis is None:
            try:
                with console.status("[bold yellow]🐾 管理员思考中...[/bold yellow]", spinner="dots"):
                    result = self.administrator.ask(user_input)
                self._render_answer(result)
                # 保存到对话历史（修复 /session save 无法保存 bug）
                self.history.append({"role": "user", "content": user_input})
                self.history.append({"role": "assistant", "content": result.text})
                if len(self.history) > 20:
                    self.history = self.history[-20:]
                # 记忆持久化 + 工作流记录
                if self.memory_store is not None:
                    try:
                        self.memory_store.save()
                    except Exception:
                        pass
                self._record_workflow("qa")
                # 恢复能量
                if self.pet is not None:
                    self.pet.energy = min(100, self.pet.energy + 2)
                    self.pet_storage.save(self.pet)
                return
            except Exception as e:
                err_msg = str(e).replace("[", "\\[")
                console.print(f"[yellow]管理员问答失败，降级为普通问答: {err_msg}[/yellow]")

        # 数据分析追问模式：如果刚 /analyze 过，且用户输入像追问
        if self.current_analysis is not None:
            az, result = self.current_analysis
            # 检测是否是追问（短问题 + 含疑问/分析关键词）
            q = user_input.strip()
            is_followup = (
                len(q) < 100
                and any(k in q for k in ["?", "？", "汇总", "统计", "分组", "排序",
                                          "最大", "最小", "平均", "多少", "哪个", "哪些",
                                          "按", "分布", "趋势", "缺失", "空值", "相关性",
                                          "汇总", "group", "sort", "top", "前"])
            )
            if is_followup:
                console.print("[bold yellow]⏺[/bold yellow] [dim]基于数据分析回答...[/dim]")
                try:
                    answer = az.ask(result, q)
                    console.print(f"[bold yellow]⏺[/bold yellow] [bold cyan]数据分析助手[/bold cyan]")
                    console.print(answer)
                    console.print()
                except Exception as e:
                    err_msg = str(e).replace("[", "\\[")
                    console.print(f"[red]追问失败:[/red] {type(e).__name__}: {err_msg}")
                return

        # 懒加载 RAGChain（已升级为混合检索 + 多轮 query expansion）
        if self.rag is None:
            try:
                self.rag = RAGChain(storage=self.storage)
            except LLMError as e:
                console.print(f"[red]LLM 初始化失败:[/red] {e}")
                self.llm_available = False
                return

        # 使用改进的 RAGChain：混合检索 + 重排序 + 多轮上下文扩展
        with console.status("[bold yellow]🔍 混合检索知识库...[/bold yellow]", spinner="dots"):
            answer = self.rag.ask(user_input, history=self.history)

        if not answer.has_answer:
            console.print("[yellow]⚠ 知识库中没有相关资料，尝试基于通用知识回答[/yellow]\n")
            # 退化为纯对话
            try:
                console.print("[bold yellow]⏺[/bold yellow] [dim]AI 正在思考...[/dim]")
                full_content: list[str] = []
                first_token = True
                for token in self.rag.llm.chat_stream(
                    [{"role": "user", "content": user_input}], temperature=0.5
                ):
                    if first_token:
                        sys.stdout.write("\033[1A\r")
                        sys.stdout.write("\033[K")
                        sys.stdout.flush()
                        console.print("[bold yellow]⏺[/bold yellow] [bold cyan]AI[/bold cyan]", end="")
                        first_token = False
                    sys.stdout.write(token)
                    sys.stdout.flush()
                    full_content.append(token)
                console.print()
                assistant_content = "".join(full_content)
            except LLMError:
                console.print("[yellow]（AI 暂时无法回答）[/yellow]\n")
                return
        else:
            # 同步模式：RAGChain 已生成完整回答，直接输出
            console.print("[bold yellow]⏺[/bold yellow] [bold cyan]AI[/bold cyan]")
            assistant_content = answer.content

        # 显示引用来源
        if answer.citations:
            console.print()
            ref_lines = []
            for c in answer.citations:
                score_str = f" (相关度 {c.get('score', 0):.4f})" if 'score' in c else ""
                source_str = f" [{c.get('source', '?')}]" if 'source' in c else ""
                ref_lines.append(
                    f"  [{c['index']}] [cyan]{c['doc_title']}[/cyan]"
                    f"[dim]{score_str}{source_str}[/dim]"
                )
            if answer.low_confidence:
                ref_lines.insert(0, "  [dim]⚠ 检索相关度较低，仅供参考[/dim]")
            ref_panel = Panel(
                "\n".join(ref_lines),
                border_style="cyan",
                title="[bold cyan]📚 引用来源[/bold cyan]",
                title_align="left",
                padding=(0, 1),
            )
            console.print(ref_panel)
            console.print()

        # 保存历史
        self.history.append({"role": "user", "content": user_input})
        self.history.append({"role": "assistant", "content": assistant_content})
        if len(self.history) > 20:
            self.history = self.history[-20:]

        # 宠物经验 + 能量
        self._pet_gain_exp(10, "qa")
        if self.pet:
            self.pet.energy = min(100, self.pet.energy + 2)
            self.pet_storage.save(self.pet)

    # ---- 管理员回答渲染 + 工作流 ----
    # ---- 管理员回答渲染 + 工作流 ----

    def _render_answer(self, result: AnswerResult) -> None:
        """渲染带引用的管理员回答：宠物头像标题 + Markdown 回答面板 + 引用溯源 + 经验提示。"""
        t = get_theme()

        # 宠物头像标题栏（带系别标签）
        if self.pet is not None:
            avatar = {"scholar": "🦉", "warrior": "🐺", "artisan": "🦡"}.get(self.pet.branch, "🐣")
            color = {"scholar": "cyan", "warrior": "red", "artisan": "yellow"}.get(self.pet.branch, "white")
            branch_label = {"scholar": "学者", "warrior": "战士", "artisan": "工匠"}.get(self.pet.branch, "")
            branch_tag = f" · {branch_label}" if branch_label else ""
            header = (
                f"[{color}]{avatar}[/{color}] "
                f"[bold magenta]{self.pet.name}[/bold magenta] "
                f"[dim]Lv{self.pet.level}{branch_tag}[/dim]"
            )
        else:
            header = f"[{t.colors['ai_marker']}]⏺[/{t.colors['ai_marker']}] [bold]AI 助手[/bold]"

        # 回答正文（Markdown 渲染，带面板）
        subtitle = (
            f"[dim]基于 {len(result.citations)} 条引用[/dim]"
            if result.citations else "[dim]基于知识库回答[/dim]"
        )
        answer_panel = Panel(
            Markdown(result.text),
            title=header,
            title_align="left",
            border_style=t.colors["border_ai"],
            padding=(1, 2),
            subtitle=subtitle,
            subtitle_align="right",
        )
        console.print(answer_panel)
        console.print()

        # 引用溯源区块（更紧凑的编号列表）
        if result.citations:
            ref_lines = []
            for i, c in enumerate(result.citations, 1):
                ref_lines.append(
                    f"  [bold cyan]{i}.[/bold cyan] [cyan]{c.title}[/cyan] "
                    f"[dim]§{c.paragraph_num} · doc:{c.doc_id[:8]}[/dim]"
                )
            ref_panel = Panel(
                "\n".join(ref_lines),
                border_style="dim cyan",
                title="[dim]📚 引用溯源[/dim]",
                title_align="left",
                padding=(0, 1),
            )
            console.print(ref_panel)
            console.print()

        # 宠物事件提示（升级 / 分系）
        events = result.pet_events or {}
        if events.get("leveled_up"):
            console.print(f"[bold magenta]🎉 {self.pet.name if self.pet else '宠物'} 升到 "
                          f"Lv{events.get('new_level', '?')}！[/bold magenta]")
        if events.get("branched"):
            branch_label = {"scholar": "学者", "warrior": "战士", "artisan": "工匠"}.get(
                events.get("branch", ""), "")
            console.print(f"[bold magenta]✨ 进化为 {branch_label}系！[/bold magenta]")

    def _record_workflow(self, cmd: str) -> None:
        """记录命令到工作流追踪器，并显示下一步推荐。"""
        if self.workflow_tracker is None:
            return
        # 过滤掉不需要记录的命令
        skip = {"/exit", "/quit", "/help", "/clear", "/theme", "/memory"}
        if cmd in skip:
            return
        try:
            self.workflow_tracker.record_command(cmd)
            # 推荐下一步（基于历史模式）
            suggestion = self.workflow_tracker.suggest_next(cmd)
            if suggestion:
                console.print(f"[dim]💡 接下来可以试试: {suggestion}[/dim]")
        except Exception:
            # 工作流记录失败不影响主流程
            pass

    # ---- 虚拟宠物 ----

    def _cmd_pet(self, arg: str) -> None:
        """虚拟宠物子命令。"""
        parts = arg.split(maxsplit=1)
        sub = parts[0].lower() if parts else ""
        sub_arg = parts[1].strip() if len(parts) > 1 else ""

        if sub in ("", "status"):
            self._pet_show_status()
        elif sub == "adopt":
            self._pet_adopt(sub_arg)
        elif sub == "feed":
            self._pet_interact("feed")
        elif sub == "play":
            self._pet_interact("play")
        elif sub == "train":
            self._pet_interact("train")
        elif sub == "wash":
            self._pet_interact("wash")
        elif sub == "sleep":
            self._pet_interact("sleep")
        elif sub == "name":
            self._pet_rename(sub_arg)
        elif sub == "tasks":
            self._pet_show_tasks()
        elif sub == "shop":
            self._pet_show_shop()
        elif sub == "buy":
            self._pet_buy(sub_arg)
        elif sub == "use":
            self._pet_use(sub_arg)
        elif sub == "style":
            self._pet_style(sub_arg)
        elif sub == "reset":
            self._pet_reset(sub_arg)
        elif sub in ("bag", "inventory", "inv"):
            self._pet_show_bag()
        else:
            console.print("[bold]虚拟宠物[/bold] [dim](/pet 子命令)[/dim]\n")
            console.print("  [cyan]/pet[/cyan]                查看宠物状态")
            console.print("  [cyan]/pet adopt <名字>[/cyan]    领养宠物")
            console.print("  [cyan]/pet feed[/cyan]            喂食")
            console.print("  [cyan]/pet play[/cyan]            玩耍")
            console.print("  [cyan]/pet train[/cyan]           训练")
            console.print("  [cyan]/pet wash[/cyan]            清洁")
            console.print("  [cyan]/pet sleep[/cyan]           睡觉（恢复能量）")
            console.print("  [cyan]/pet name <新名>[/cyan]     改名")
            console.print("  [cyan]/pet style <风格>[/cyan]    切换人格风格（scholar/warrior/artisan/auto）")
            console.print("  [cyan]/pet tasks[/cyan]           每日任务")
            console.print("  [cyan]/pet shop[/cyan]            道具商店")
            console.print("  [cyan]/pet buy <id>[/cyan]        购买道具")
            console.print("  [cyan]/pet use <id>[/cyan]        使用道具")
            console.print("  [cyan]/pet bag[/cyan]             查看道具栏")
            console.print("  [cyan]/pet reset <stats|effects>[/cyan]  重置行为统计/清空限时效果")

    def _pet_show_status(self) -> None:
        """显示宠物详情面板。"""
        if self.pet is None:
            console.print("[yellow]还没有宠物，输入 /pet adopt <名字> 领养[/yellow]")
            return
        p = self.pet
        branch_label = {"scholar": "学者", "warrior": "战士", "artisan": "工匠"}.get(p.branch, "未分系")
        art = self.art_lib.get(p.branch, p.level)
        color = {"scholar": "cyan", "warrior": "red", "artisan": "yellow"}.get(p.branch, "white")

        art_text = Text(art, style=color)
        info = Group(
            art_text,
            Text(""),
            Text.from_markup(f"  [bold magenta]{p.name}[/bold magenta]  Lv{p.level} {branch_label}"),
            Text(""),
            Text.from_markup(f"  ❤️ 饱食   {_render_bar(p.hunger)}  [dim]{p.hunger}/100[/dim]"),
            Text.from_markup(f"  😊 心情   {_render_bar(p.mood)}  [dim]{p.mood}/100[/dim]"),
            Text.from_markup(f"  ⚡ 能量   {_render_bar(p.energy)}  [dim]{p.energy}/100[/dim]"),
            Text.from_markup(f"  🛁 清洁   {_render_bar(p.cleanliness)}  [dim]{p.cleanliness}/100[/dim]"),
            Text(""),
            Text.from_markup(f"  ✨ 经验   {_render_bar(round(p.exp / p.exp_needed() * 100))}  [dim]{p.exp}/{p.exp_needed()}[/dim]" + (
                f"  →Lv{p.level+1} 还需 {p.exp_remaining()}" if p.level < 10 else "  [dim](最高级)[/dim]"
            )),
        )
        console.print(Panel(info, border_style="magenta", title=f"[bold magenta]🐾 {p.name}[/bold magenta]", padding=(1, 2)))

    def _pet_adopt(self, name: str) -> None:
        """领养宠物。"""
        if self.pet is not None:
            console.print(f"[yellow]已经领养过 {self.pet.name} 了[/yellow]")
            return
        if not name:
            console.print("[yellow]用法: /pet adopt <名字>[/yellow]")
            return
        self.pet = self.pet_storage.create(name)
        console.print(f"[bold green]✓ 领养成功！[/bold green] 你的宠物叫 [magenta]{name}[/magenta]")
        self._pet_show_status()

    def _pet_interact(self, action: str) -> None:
        """执行互动。"""
        if self.pet is None:
            console.print("[yellow]还没有宠物，/pet adopt 领养[/yellow]")
            return
        try:
            method = getattr(self.pet_interactor, action)
            result = method(self.pet)
            self.pet_storage.save(self.pet)
            console.print(f"[green]{result['message']}[/green]")
        except InteractError as e:
            console.print(f"[yellow]{e}[/yellow]")

    def _pet_rename(self, new_name: str) -> None:
        """改名。"""
        if self.pet is None:
            console.print("[yellow]还没有宠物[/yellow]")
            return
        if not new_name:
            console.print("[yellow]用法: /pet name <新名字>[/yellow]")
            return
        old = self.pet.name
        self.pet.name = new_name
        self.pet_storage.save(self.pet)
        console.print(f"[green]✓ {old} 改名为 {new_name}[/green]")

    def _pet_show_tasks(self) -> None:
        """显示每日任务。"""
        if self.pet is None:
            console.print("[yellow]还没有宠物[/yellow]")
            return
        # 检查是否需要刷新
        if self.task_manager._should_refresh(self.pet):
            self.task_manager.refresh(self.pet)
            self.pet_storage.save(self.pet)
        tasks = self.task_manager.list_tasks(self.pet)
        if not tasks:
            console.print("[yellow]今日任务已刷新，请稍后再试[/yellow]")
            return
        t = Table(title="📋 今日任务", border_style="magenta")
        t.add_column("任务", style="white")
        t.add_column("进度", style="cyan")
        t.add_column("奖励", style="yellow")
        t.add_column("状态", style="green")
        for task in tasks:
            status = "✓ 完成" if task["completed"] else "进行中"
            t.add_row(
                task["description"],
                f"{task['progress']}/{task['target']}",
                f"+{task['reward']}",
                status,
            )
        console.print(t)

    def _pet_show_shop(self) -> None:
        """显示商店。"""
        t = Table(title="🛒 道具商店", border_style="yellow")
        t.add_column("ID", style="cyan")
        t.add_column("名称", style="white")
        t.add_column("价格", style="yellow")
        t.add_column("效果", style="dim")
        for item in self.shop.list_items():
            effect_str = str(item["effect"])
            t.add_row(item["id"], item["name"], f"{item['price']} 经验", effect_str)
        console.print(t)
        console.print("[dim]用 /pet buy <id> 购买，/pet use <id> 使用[/dim]")

    def _pet_buy(self, item_id: str) -> None:
        """购买道具。"""
        if self.pet is None:
            console.print("[yellow]还没有宠物[/yellow]")
            return
        if not item_id:
            console.print("[yellow]用法: /pet buy <id>[/yellow]")
            return
        try:
            result = self.shop.buy(self.pet, item_id)
            self.pet_storage.save(self.pet)
            console.print(f"[green]{result['message']}[/green]")
        except ShopError as e:
            console.print(f"[red]{e}[/red]")

    def _pet_use(self, item_id: str) -> None:
        """使用道具。支持序号（/pet use 1）或道具 ID（/pet use energy_drink）。"""
        if self.pet is None:
            console.print("[yellow]还没有宠物[/yellow]")
            return
        if not item_id:
            console.print("[yellow]用法: /pet use <序号|id>[/yellow]")
            return
        inv = self.pet.inventory
        if not inv:
            console.print("[yellow]道具栏是空的[/yellow]")
            return
        # 如果输入是数字序号，转换为 item_id
        try:
            idx = int(item_id) - 1  # 1-based → 0-based
            if 0 <= idx < len(inv):
                item_id = inv[idx]["item_id"]
            else:
                console.print(f"[red]无效序号: {item_id}（共 {len(inv)} 种道具）[/red]")
                return
        except ValueError:
            pass  # 不是数字，当作 item_id 直接使用
        try:
            result = self.shop.use(self.pet, item_id)
            self.pet_storage.save(self.pet)
            console.print(f"[green]{result['message']}[/green]")
        except ShopError as e:
            console.print(f"[red]{e}[/red]")

    def _pet_style(self, style: str) -> None:
        """切换人格风格：/pet style <scholar|warrior|artisan|auto>。"""
        if self.pet is None:
            console.print("[yellow]还没有宠物，/pet adopt 领养[/yellow]")
            return
        valid = {"scholar", "warrior", "artisan", "auto"}
        if not style:
            # 显示当前风格
            if self.memory_store is not None:
                try:
                    mgr = ProfileManager(self.memory_store)
                    cur = mgr.get_profile().preferred_style
                    console.print(f"[dim]当前人格风格: [cyan]{cur}[/cyan][/dim]")
                except Exception:
                    pass
            console.print("[dim]用法: /pet style <scholar|warrior|artisan|auto>[/dim]")
            return
        s = style.strip().lower()
        if s not in valid:
            console.print(f"[red]未知风格: {s}[/red]  [dim]可选: scholar / warrior / artisan / auto[/dim]")
            return
        if self.memory_store is None:
            console.print("[yellow]记忆模块未初始化，无法保存风格偏好[/yellow]")
            return
        try:
            mgr = ProfileManager(self.memory_store)
            mgr.update_style_preference(s)
            label = {"scholar": "学者", "warrior": "战士", "artisan": "工匠", "auto": "自动"}.get(s, s)
            console.print(f"[green]✓ 人格风格已切换为[/green] [bold cyan]{label}[/bold cyan]")
            if s == "auto":
                console.print("[dim]（auto = 跟随宠物分系）[/dim]")
        except Exception as e:
            err_msg = str(e).replace("[", "\\[")
            console.print(f"[red]切换失败: {err_msg}[/red]")

    def _pet_reset(self, target: str) -> None:
        """重置宠物数据：/pet reset <stats|effects>。

        - stats:   清空行为统计（用于重新分系判定）
        - effects: 清空所有限时效果（active_effects）
        """
        if self.pet is None:
            console.print("[yellow]还没有宠物，/pet adopt 领养[/yellow]")
            return
        target = (target or "").strip().lower()
        if target not in ("stats", "effects"):
            console.print("[yellow]用法: /pet reset <stats|effects>[/yellow]")
            console.print("  [cyan]/pet reset stats[/cyan]    清空行为统计（重新分系判定）")
            console.print("  [cyan]/pet reset effects[/cyan]  清空所有限时效果")
            return
        if target == "stats":
            confirm = Prompt.ask(
                f"确定清空 {self.pet.name} 的行为统计？这会影响分系判定。",
                choices=["y", "n"], default="n",
            )
            if confirm != "y":
                console.print("[dim]已取消[/dim]")
                return
            self.pet.reset_stats()
            self.pet_storage.save(self.pet)
            console.print(f"[green]✓ 已清空行为统计[/green] [dim]（等级/经验/属性保留）[/dim]")
        elif target == "effects":
            count = self.pet.clear_active_effects()
            self.pet_storage.save(self.pet)
            console.print(f"[green]✓ 已清空 {count} 个限时效果[/green]")

    def _pet_show_bag(self) -> None:
        """查看道具栏：/pet bag"""
        if self.pet is None:
            console.print("[yellow]还没有宠物，/pet adopt 领养[/yellow]")
            return
        inv = self.pet.inventory
        if not inv:
            console.print(f"[yellow]{self.pet.name} 的道具栏是空的[/yellow]")
            console.print("[dim]用 /pet shop 查看商店，/pet buy <id> 购买道具[/dim]")
            return
        console.print(f"\n[bold]🎒 {self.pet.name} 的道具栏[/bold] [dim]（共 {len(inv)} 种）[/dim]\n")
        table = Table(show_lines=False, border_style="magenta")
        table.add_column("#", style="dim", width=4)
        table.add_column("名称", style="white")
        table.add_column("数量", style="cyan", width=6)
        table.add_column("效果", style="yellow")

        # 从商店获取道具定义（name + effect）
        shop_items = self.shop.list_items()
        item_map = {si["id"]: si for si in shop_items}

        for i, slot in enumerate(inv):
            item_data = item_map.get(slot.get("item_id", ""), {})
            name = item_data.get("name", "?")
            count = slot.get("count", 0)
            effect = item_data.get("effect", {})
            # 效果描述
            effect_desc = ""
            if isinstance(effect, dict) and effect:
                parts = []
                for k, v in effect.items():
                    if k == "hunger":
                        parts.append(f"饱食+{v}")
                    elif k == "mood":
                        parts.append(f"心情+{v}")
                    elif k == "energy":
                        parts.append(f"能量+{v}")
                    elif k == "cleanliness":
                        parts.append(f"清洁+{v}")
                    elif k == "exp_multi":
                        dur = effect.get("duration_sec", 0) // 3600
                        parts.append(f"经验×{v}({dur}h)")
                    elif k == "auto_revive":
                        parts.append("凤凰之羽")
                    elif k == "reset_stats":
                        parts.append("重置属性")
                    else:
                        parts.append(f"{k}+{v}")
                effect_desc = "、".join(parts)
            table.add_row(str(i + 1), name, str(count), effect_desc)
        console.print(table)
        console.print("\n[dim]用 /pet use <序号> 使用道具[/dim]\n")

    def _pet_gain_exp(self, amount: int, action_type: str) -> None:
        """宠物获取经验（埋点辅助方法）。"""
        if self.pet is None:
            return
        events = self.pet.gain_exp(amount, action_type)
        # 检查每日任务进度
        completed = self.task_manager.check_progress(self.pet, action_type)
        # 发放任务奖励
        for task in completed:
            self.pet.gain_exp(task["reward"], "task_reward")
            console.print(f"[green]✓ 每日任务完成: {task['description']} (+{task['reward']} 经验)[/green]")
        # 升级提示
        if events.get("leveled_up"):
            console.print(f"[bold magenta]🎉 {self.pet.name} 升到 Lv{events['new_level']}！[/bold magenta]")
        # 分系提示
        if events.get("branched"):
            branch_label = {"scholar": "学者", "warrior": "战士", "artisan": "工匠"}.get(events["branch"], "")
            console.print(f"[bold magenta]✨ {self.pet.name} 进化为 {branch_label}系！[/bold magenta]")
        self.pet_storage.save(self.pet)

    # ---- 辅助 ----

    def _resolve_doc_id(self, short_id: str) -> Optional[str]:
        """根据前缀匹配完整 doc_id。"""
        if len(short_id) >= 32:
            return short_id
        docs = self.storage.list_documents(limit=1000)
        matched = [d for d in docs if d.id.startswith(short_id)]
        return matched[0].id if matched else None


def main() -> None:
    """REPL 入口。"""
    try:
        repl = REPL()
        repl.run()
    except KeyboardInterrupt:
        console.print("\n[dim]再见 👋[/dim]")
    except Exception as e:
        # 错误信息可能含 rich markup 字符，用 [red]...[/] 简写避免闭合问题
        err_msg = str(e).replace("[", "\\[")
        console.print(f"\n[red]错误:[/red] {type(e).__name__}: {err_msg}")
        sys.exit(1)


if __name__ == "__main__":
    main()

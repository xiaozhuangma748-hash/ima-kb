"""REPL CLI 模块级常量与全局变量。

集中存放所有命令列表、别名表、子命令菜单、派发表等，供 completer / repl /
各 Mixin 共享。console 实例在此创建，其他文件 import 使用。

注意：
- 本文件不 import 任何 core/cli/ 内部模块，避免循环导入。
- _INPUT_STYLE 是可变全局（_cmd_theme 会重赋值），跨模块访问须通过
  ``constants._INPUT_STYLE`` 属性读取/写入，不能用 ``from ... import`` 快照。
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from rich.console import Console

from prompt_toolkit.history import FileHistory
from prompt_toolkit.styles import Style as PtStyle

from config import settings, PROJECT_ROOT

# ============================================================
# 共享 Console 实例
# ============================================================
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

# 像素风宠物（Claude Code 风格启动页 mascot）
PIXEL_PET_ASCII = r"""
    ▄▄▄▄▄
   █     █
   █ ▀ ▀ █
   █     █
   █▄▄▄▄▄█
  ▄▄     ▄▄
  ▀▀     ▀▀
"""

# ============================================================
# 活动记录（用于启动页 Recent activity）
# ============================================================

_ACTIVITY_PATH = PROJECT_ROOT / "storage" / "activity.json"

# 命令历史持久化（prompt_toolkit FileHistory）
_cmd_history = FileHistory(str(PROJECT_ROOT / "storage" / "cmd_history"))

_ICON_MAP: dict[str, str] = {
    "qa":       "Q",
    "ingest":   "+",
    "search":   "S",
    "analyze":  "A",
    "read":     "R",
    "compare":  "C",
    "pic":      "P",
    "draw":     "D",
    "daily":    "K",
    "graph":    "G",
    "summarize":"M",
}

_LABEL_MAP: dict[str, str] = {
    "qa":       "Q&A",
    "ask":      "Q&A",
    "ingest":   "Ingest",
    "search":   "Search",
    "analyze":  "Analyze",
    "read":     "Read",
    "compare":  "Compare",
    "draw":     "Draw",
    "pic":      "Image",
    "daily":    "Daily",
    "graph":    "Graph",
    "summarize":"Summary",
}

_NAME_MAP = {
    "qa":       ("问答", "️"),
    "ask":      ("问答", "️"),
    "ingest":   ("入库", ""),
    "search":   ("搜索", ""),
    "analyze":  ("分析", ""),
    "read":     ("阅读", ""),
    "compare":  ("对比", ""),
    "draw":     ("配图", ""),
    "pic":      ("生图", ""),
    "daily":    ("卡片", ""),
    "graph":    ("图谱", ""),
    "summarize":("摘要", ""),
}

# 帮助文本
HELP_TEXT = """\
[bold green]基础[/bold green]
  /search <关键词>     BM25 智能搜索    /ingest <路径>      入库文件/目录
  /ask <问题>          AI 问答          /note <文本>        文本直入库

[bold green]文档[/bold green]
  /read <ID>           智能阅读模式     /compare <A> <B>    对比文档
  /report <ID>         生成分析报告     /analyze <文件>     数据表分析

[bold green]系统[/bold green]
  /stats               知识库统计       /tags              标签管理
  /memory              记忆管理         /graph             知识图谱
  /health              健康检查         /dedup             去重

[bold green]高级[/bold green]
  /agent <任务>        Agent 多步执行   /smart <描述>       智能路由
  /session <子命令>    会话管理         /pet <子命令>       宠物管理

[dim]示例: /search 骨灰 | /agent 找骨灰安置政策并总结 | /session save[/dim]
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

# 别名 → 完整命令（补全器用的小表）
_CMD_ALIASES = {
    '/s': '/search', '/l': '/list', '/sh': '/show', '/st': '/stats',
    '/i': '/ingest', '/r': '/read', '/a': '/agent', '/t': '/tag',
    '/m': '/memory', '/g': '/graph', '/p': '/pet', '/h': '/help',
    '/q': '/quit',
}


# ============================================================
# REPL 命令派发相关（原 REPL 类属性，现作为模块常量共享）
# ============================================================

# 命令别名：短名 → 完整命令（派发用的大表）
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

# 命令派发表：命令名 → 处理器方法名
_COMMAND_DISPATCH = {
    "/help": "_cmd_help",
    "/exit": "_cmd_exit",
    "/quit": "_cmd_exit",
    "exit": "_cmd_exit",
    "quit": "_cmd_exit",
    "/search": "_cmd_search",
    "/ingest": "_cmd_ingest",
    "/note": "_cmd_note",
    "/clip": "_cmd_clip",
    "/url": "_cmd_url",
    "/analyze": "_cmd_analyze",
    "/list": "_cmd_list",
    "/show": "_cmd_show",
    "/tag": "_cmd_tag",
    "/delete": "_cmd_delete",
    "/reparse": "_cmd_reparse",
    "/edit": "_cmd_edit",
    "/stats": "_cmd_stats",
    "/rebuild": "_cmd_rebuild",
    "/retag": "_cmd_retag",
    "/watch": "_cmd_watch",
    "/web": "_cmd_web",
    "/clear": "_cmd_clear",
    "/session": "_cmd_session",
    "/session_save": "_cmd_save",
    "/session_load": "_cmd_load",
    "/session_list": "_cmd_sessions",
    "/session_export": "_cmd_export",
    "/report": "_cmd_report",
    "/read": "_cmd_read",
    "/compare": "_cmd_compare",
    "/agent": "_cmd_agent",
    "/smart": "_cmd_smart",
    "/graph": "_cmd_graph",
    "/pet": "_cmd_pet",
    "/memory": "_cmd_memory",
    "/theme": "_cmd_theme",
    "/sync": "_cmd_sync",
    "/health": "_cmd_health",
    "/dedup": "_cmd_dedup",
    "/draw": "_cmd_draw",
    "/daily": "_cmd_daily",
    "/pic": "_cmd_pic",
}

# ============================================================
# 输入提示符样式（橙色粗体 > Claude Code 风格）
# 注意：_cmd_theme 会重赋值此变量，跨模块访问须用 constants._INPUT_STYLE
# ============================================================
_INPUT_STYLE = PtStyle.from_dict({
    "prompt": "bold fg:ansiyellow",
    "completion-menu.completion": "bg:ansiblack fg:ansiwhite",
    "completion-menu.completion.current": "bg:ansiyellow fg:ansiblack bold",
    "completion-menu.meta.completion": "bg:ansiblue fg:ansiwhite",
    "completion-menu.meta.completion.current": "bg:ansicyan fg:ansiblack bold",
    "completion-menu.progress-button": "bg:ansiblue",
    "completion-menu.progress-bar": "bg:ansiblue",
})

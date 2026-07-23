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
[bold green]核心[/bold green]
  /smart <描述>        智能路由           /search <关键词>    BM25 搜索 (/s)
  /agent <任务>        Agent 多步执行     直接输入问题       AI 问答

[bold green]入库[/bold green]
  /ingest <路径>       文件/目录入库      /note <文本>        文本直入库
  /clip                剪贴板入库         /url <链接>         网页入库

[bold green]文档[/bold green]
  /list                列出所有文档       /show <ID>          查看文档详情
  /read <ID>           智能阅读模式       /compare <A> <B>    对比文档
  /report <ID>         生成分析报告       /analyze <文件>     数据表分析
  /delete <ID>         删除文档

[bold green]记忆与个性化[/bold green]
  /memory              记忆管理           /cross              跨会话记忆
  /pet                 虚拟宠物           /theme              切换主题

[bold green]桌面宠物[/bold green]
  /desktop [start|stop|status]  Electron 桌面宠物开关

[bold green]系统[/bold green]
  /stats               知识库统计         /tag                标签管理
  /health              健康检查           /dedup              去重
  /sync                增量同步           /session            会话管理

[bold green]生成与其他[/bold green]
  /draw <ID>           基于文档生成配图   /daily              每日知识卡片
  /pic <描述>          文生图             /todo               每日任务

[dim]示例: 杭州火化政策 | /search 骨灰 | /agent 找骨灰安置政策并总结[/dim]
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
    ("/pet",     "虚拟宠物（adopt/feed/play/train/wash/sleep/name/tasks/shop/buy/use/style/bag/reset）"),
    ("/desktop", "Electron 桌面宠物（start/stop/status）"),
    ("/memory",  "记忆管理（show/clear/add/tasks）"),
    ("/todo",    "每日任务（add/done/cancel/history）"),
    ("/cross",   "跨会话记忆（list/add/remove/clear）"),
    ("/exit",    "退出"),
    ("/q",       "= /quit（别名）"),
    ("/quit",    "退出"),
]

# NestedCompleter：输入命令+空格后自动弹出子命令补全
# 格式：命令 → 子命令 → 选项（多级嵌套）
_SUB_MENU_NESTED = {
    '/memory': {
        'show': None,
        'clear': None,
        'add': None,
        'format': {'table': None, 'list': None, 'prose': None, 'auto': None, 'none': None},
        'style': {'scholar': None, 'warrior': None, 'artisan': None, 'auto': None},
        'topic': {'add': None, 'remove': None, 'clear': None},
        'region': {'add': None, 'remove': None, 'clear': None},
        'task': {'add': None, 'done': None, 'cancel': None, 'reopen': None, 'start': None, 'delete': None},
        'tasks': None,
        'workflow': {'clear': None, 'suggest': {'on': None, 'off': None}, 'analyze': None},
    },
    '/pet': {
        'adopt': None,
        'feed': None, 'play': None, 'train': None, 'wash': None, 'sleep': None,
        'name': None,
        'tasks': None, 'shop': None, 'buy': None, 'use': None,
        'style': {'scholar': None, 'warrior': None, 'artisan': None, 'auto': None},
        'bag': None,
        'reset': {'stats': None, 'effects': None},
    },
    '/desktop': {
        'start': None,
        'stop': None,
        'status': None,
    },
    '/graph': {
        'stats': None, 'build': None, 'neighbors': None, 'export': None,
        'clear': None, 'delete': None, 'rename': None,
    },
    '/agent': {
        'think': {'on': None, 'off': None},
    },
    '/sync': {'reset': None},
    '/session': {'save': None, 'load': None, 'list': None, 'export': None, 'delete': None},
    '/tag': {'rename': None, 'merge': None},
    '/dedup': {'delete': None},
    '/health': {'list': None},
    '/theme': {'claude': None, 'mimo': None, 'minimal': None},
    '/web': {'stop': None},
    '/search': {'config': {'tag': None, 'limit': None, 'reset': None}},
    '/cross': {
        'list': None,
        'add': {'preference': None, 'topic': None, 'question': None, 'fact': None},
        'remove': {'topic': None},
        'clear': None,
    },
    '/todo': {
        'add': None, 'done': None, 'cancel': None, 'reopen': None,
        'del': None, 'edit': None, 'pri': None,
        'history': None, 'clear': None, 'carry': None, 'list': None,
    },
}

# 子命令中文描述（path → 描述，path 是命令+各层级子命令组成的 tuple）
_SUB_MENU_DESC = {
    ('/memory', 'show'): '显示记忆概览',
    ('/memory', 'clear'): '清空所有记忆',
    ('/memory', 'add'): '添加任务',
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
    ('/memory', 'workflow'): '清空/推荐/分析工作流',
    ('/memory', 'workflow', 'clear'): '清空',
    ('/memory', 'workflow', 'suggest'): '推荐工作流',
    ('/memory', 'workflow', 'suggest', 'on'): '启用',
    ('/memory', 'workflow', 'suggest', 'off'): '关闭',
    ('/memory', 'workflow', 'analyze'): '分析低效操作',
    ('/pet', 'adopt'): '领养宠物',
    ('/pet', 'feed'): '喂食',
    ('/pet', 'play'): '玩耍',
    ('/pet', 'train'): '训练',
    ('/pet', 'wash'): '洗澡',
    ('/pet', 'sleep'): '睡觉',
    ('/pet', 'name'): '改名',
    ('/pet', 'tasks'): '查看任务',
    ('/pet', 'shop'): '商店',
    ('/pet', 'buy'): '购买道具',
    ('/pet', 'use'): '使用道具',
    ('/pet', 'style'): '切换人格风格',
    ('/pet', 'style', 'scholar'): '学者风格',
    ('/pet', 'style', 'warrior'): '战士风格',
    ('/pet', 'style', 'artisan'): '工匠风格',
    ('/pet', 'style', 'auto'): '自动',
    ('/pet', 'bag'): '背包',
    ('/pet', 'reset'): '重置宠物',
    ('/pet', 'reset', 'stats'): '重置属性',
    ('/pet', 'reset', 'effects'): '重置效果',
    ('/desktop', 'start'): '启动桌面宠物',
    ('/desktop', 'stop'): '停止桌面宠物',
    ('/desktop', 'status'): '查看运行状态',
    ('/graph', 'stats'): '统计信息',
    ('/graph', 'build'): '构建图谱',
    ('/graph', 'neighbors'): '查询邻居',
    ('/graph', 'export'): '导出 HTML',
    ('/graph', 'clear'): '清空图谱',
    ('/graph', 'delete'): '删除节点',
    ('/graph', 'rename'): '重命名节点',
    ('/agent', 'think'): '思考过程显示',
    ('/agent', 'think', 'on'): '显示',
    ('/agent', 'think', 'off'): '隐藏',
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
    ('/theme', 'claude'): 'Claude 风格',
    ('/theme', 'mimo'): 'MiMo 风格',
    ('/theme', 'minimal'): '极简风格',
    ('/web', 'stop'): '停止 Web 服务',
    ('/search', 'config'): '搜索默认配置 (tag/limit/reset)',
    ('/search', 'config', 'tag'): '设置默认标签',
    ('/search', 'config', 'limit'): '设置默认数量',
    ('/search', 'config', 'reset'): '重置配置',
    ('/cross', 'list'): '显示跨会话记忆',
    ('/cross', 'add'): '添加跨会话记忆 (preference/topic/question/fact)',
    ('/cross', 'add', 'preference'): '添加用户偏好 (键:值)',
    ('/cross', 'add', 'topic'): '添加关注主题',
    ('/cross', 'add', 'question'): '记录未解决问题',
    ('/cross', 'add', 'fact'): '记录关键事实',
    ('/cross', 'remove'): '移除跨会话记忆 (topic)',
    ('/cross', 'remove', 'topic'): '移除关注主题',
    ('/cross', 'clear'): '清空所有跨会话记忆',
    ('/todo', 'add'): '添加任务',
    ('/todo', 'done'): '标记完成',
    ('/todo', 'cancel'): '取消任务',
    ('/todo', 'reopen'): '重开任务',
    ('/todo', 'del'): '彻底删除',
    ('/todo', 'edit'): '编辑描述',
    ('/todo', 'pri'): '修改优先级',
    ('/todo', 'history'): '历史记录',
    ('/todo', 'clear'): '清空今日',
    ('/todo', 'carry'): '跨天处理',
    ('/todo', 'list'): '显示今日任务',
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
    "/td": "/todo",      # 每日任务
}

# 子命令菜单：主命令 → [(子命令参数, 描述), ...]
# 子命令菜单已禁用（用户偏好直接输入命令）
SUBCOMMAND_MENU = {}

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
    "/desktop": "_cmd_desktop",
    "/memory": "_cmd_memory",
    "/cross": "_cmd_cross",
    "/theme": "_cmd_theme",
    "/sync": "_cmd_sync",
    "/health": "_cmd_health",
    "/dedup": "_cmd_dedup",
    "/draw": "_cmd_draw",
    "/daily": "_cmd_daily",
    "/pic": "_cmd_pic",
    "/todo": "_cmd_todo",
}

# ============================================================
# 输入提示符样式（橙色粗体 > Claude Code 风格）
# 注意：_cmd_theme 会重赋值此变量，跨模块访问须用 constants._INPUT_STYLE
# ============================================================
_INPUT_STYLE = PtStyle.from_dict({
    "prompt": "bold fg:ansiyellow",
    "completion-menu.completion": "bg:ansiblack fg:ansiwhite",
    "completion-menu.completion.current": "bg:ansiyellow fg:ansiblack bold",
    "completion-menu.meta.completion": "bg:ansicyan fg:ansiwhite",
    "completion-menu.meta.completion.current": "bg:ansiyellow fg:ansiblack bold",
    "completion-menu.progress-button": "bg:ansicyan",
    "completion-menu.progress-bar": "bg:ansicyan",
})

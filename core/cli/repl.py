"""REPL 主类（瘦壳），聚合所有 Mixin。

从 repl.py 第 633-1367 行迁移：
- ``__init__`` 初始化所有子系统
- ``_init_administrator`` 延迟初始化 PetAdministrator
- ``run`` 启动 REPL 主循环
- ``_handle_read_input`` 阅读模式输入处理
- ``_show_subcommand_menu`` 子命令交互菜单
- ``_prompt_subcmd_params`` 占位符参数提示
- ``_handle_command`` 命令派发
- ``_cmd_help`` 帮助
- ``_cmd_exit`` 退出

类属性 ``CMD_ALIASES`` / ``SUBCOMMAND_MENU`` / ``_COMMAND_DISPATCH`` 从
``core.cli.constants`` 引用赋值，保持 ``REPL.CMD_ALIASES`` 测试兼容。
"""
from __future__ import annotations

import os
import threading
from datetime import datetime
from typing import List, Optional

from rich.panel import Panel
from rich.text import Text
from rich.prompt import Prompt

from config import settings
from core.storage import Storage
from core.qa.chain import RAGChain
from core.pet.pet import Pet
from core.pet.storage import PetStorage
from core.pet.art import ArtLibrary
from core.pet.interact import PetInteractor
from core.pet.tasks import DailyTaskManager
from core.pet.shop import Shop
from core.pet.administrator import PetAdministrator
from core.memory.store import MemoryStore
from core.memory.workflow import WorkflowTracker
from core.memory.cross_session import CrossSessionMemory
from core.retrieval.hybrid import HybridRetriever
from core.retrieval.vector import VectorIndex
from core.retrieval.rerank import Reranker
from core.llm.client import get_llm

from core.cli import constants
from core.cli.constants import console, HELP_TEXT
from core.cli.welcome import _render_welcome_panel
from core.cli.completer import _read_input
from core.cli.chat import ChatMixin
from core.cli.commands.docs import DocsMixin
from core.cli.commands.analyze import AnalyzeMixin
from core.cli.commands.agent import AgentMixin
from core.cli.commands.sync import SyncMixin
from core.cli.commands.session import SessionMixin
from core.cli.commands.memory import MemoryMixin
from core.cli.commands.graph import GraphMixin
from core.cli.commands.pet import PetMixin
from core.cli.commands.pipe import PipeMixin
from core.cli.commands.todo import TodoMixin


class REPL(
    TodoMixin,
    PipeMixin,
    PetMixin,
    GraphMixin,
    MemoryMixin,
    SessionMixin,
    SyncMixin,
    AnalyzeMixin,
    AgentMixin,
    DocsMixin,
    ChatMixin,
):
    """交互式 REPL，聚合所有命令 Mixin。"""

    # 类属性：从 constants 引用，保持 REPL.CMD_ALIASES 等测试兼容
    CMD_ALIASES = constants.CMD_ALIASES
    SUBCOMMAND_MENU = constants.SUBCOMMAND_MENU
    _COMMAND_DISPATCH = constants._COMMAND_DISPATCH

    def __init__(self) -> None:
        self.storage = Storage()
        self.rag: Optional[RAGChain] = None
        # 对话历史（多轮）
        self.history: List[dict] = []
        # 当前活跃会话名
        self.active_session_name: Optional[str] = None
        # 早期对话摘要（history 超过 20 条时自动生成，保留长期记忆）
        self.conversation_summary: Optional[str] = None
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
        # 延迟初始化：首次问答时才加载向量索引等重组件
        self.administrator: Optional[PetAdministrator] = None
        self.memory_store: Optional[MemoryStore] = None
        self.workflow_tracker: Optional[WorkflowTracker] = None
        self.cross_session_memory: Optional[CrossSessionMemory] = None
        self._admin_init_failed: bool = False
        self._vector_available: Optional[bool] = None  # None=未检测, True/False=已检测
        if self.pet:
            try:
                self.memory_store = MemoryStore()
                self.workflow_tracker = WorkflowTracker(self.memory_store)
            except Exception as e:
                console.print(f"[dim]记忆系统初始化失败: {e}[/dim]")
        # 跨会话记忆延迟初始化（会话确定后按会话名加载）
        self.cross_session_memory: Optional[CrossSessionMemory] = None

    def _init_administrator(self) -> None:
        """延迟初始化 PetAdministrator（首次问答时调用）。"""
        if self.administrator is not None or self._admin_init_failed:
            return
        if not self.pet:
            return
        try:
            vector_index = None
            try:
                from core.retrieval.vector import VectorIndex
                vector_index = VectorIndex()
                self._vector_available = True
            except Exception:
                self._vector_available = False
                console.print("[dim]! 向量检索不可用，使用纯 BM25 检索[/dim]")

            hybrid = HybridRetriever(
                bm25_index=self.storage.bm25, vector_index=vector_index,
                storage=self.storage,
            )
            llm = get_llm() if settings.has_llm() else None
            reranker = Reranker(llm) if llm else None
            if llm and reranker:
                # 复用 TodoMixin 的 todo_mgr（懒加载的 TodoManager）
                todo_mgr = getattr(self, "_todo_mgr", None)
                if todo_mgr is None:
                    from core.todo.manager import TodoManager
                    todo_mgr = TodoManager()
                    self._todo_mgr = todo_mgr
                self.administrator = PetAdministrator(
                    pet=self.pet,
                    storage=self.storage,
                    memory_store=self.memory_store,
                    hybrid_retriever=hybrid,
                    reranker=reranker,
                    llm=llm,
                    todo_manager=todo_mgr,
                )
        except Exception as e:
            console.print(f"[dim]宠物管理员初始化失败，降级为普通问答: {e}[/dim]")
            self._admin_init_failed = True

    # ---- 活跃会话管理 ----

    def _init_active_session(self) -> None:
        """初始化活跃会话：显示启动页后询问用户恢复或新建（只渲染一次启动页）。

        流程：
        1. 渲染启动页（显示上次活跃会话名，若无则留空）
        2. 在启动页下方询问：恢复上次会话 or 新建会话
        3. 用户输入后只追加一行确认，不刷新启动页
        """
        from core.session.store import SessionStore
        ss = SessionStore()
        active_name = ss.get_active_session()

        # 1. 渲染启动页（只一次，显示上次会话名或留空）
        console.clear()
        stats = self.storage.stats()
        _render_welcome_panel(
            stats, self.llm_available, pet=self.pet,
            session_name=active_name,
        )
        # 底部提示
        import shutil as _shutil
        _width = _shutil.get_terminal_size((80, 24)).columns
        _left = "/help for shortcuts"
        _right = "Ctrl+C to exit"
        _middle = _width - len(_left) - len(_right)
        if _middle < 1:
            _middle = 1
        console.print(f"[dim]{_left}{' ' * _middle}{_right}[/dim]")
        console.print()

        # 2. 会话选择
        sessions = ss.list_sessions()
        if sessions:
            # 有历史会话：termios raw 模式 + os.read 直接读按键
            import sys as _sys
            import os as _os
            import tty as _tty
            import termios as _termios
            import select as _select

            total = len(sessions) + 1  # +1 for "新建会话"
            selected = 0
            num_lines = total + 1  # 选项行 + 提示行

            def _build_menu():
                lines = []
                for i, s in enumerate(sessions):
                    time_str = s["saved_at"][:16].replace("T", " ") if s["saved_at"] else ""
                    msg_str = f"{s['message_count']}条" if s["message_count"] else "空"
                    marker = " ← 上次" if s["name"] == active_name else ""
                    arrow = "▶" if selected == i else " "
                    lines.append(f" {arrow} {i+1}. {s['name']}  ({msg_str}, {time_str}){marker}")
                arrow = "▶" if selected == len(sessions) else " "
                lines.append(f" {arrow} 0. 新建会话")
                lines.append("按 ↑↓ 选择，Enter 确认")
                return lines

            def _print_menu():
                out = "\r\n".join(_build_menu()) + "\r\n"
                _sys.stdout.write(out)
                _sys.stdout.flush()

            # 首次打印菜单
            _print_menu()

            fd = _sys.stdin.fileno()
            old_settings = _termios.tcgetattr(fd)
            try:
                _tty.setraw(fd)
                while True:
                    ch = _os.read(fd, 1).decode("utf-8", errors="replace")
                    key = None
                    if ch == "\x1b":
                        if _select.select([fd], [], [], 0.2)[0]:
                            ch2 = _os.read(fd, 1).decode("utf-8", errors="replace")
                            if ch2 == "[":
                                if _select.select([fd], [], [], 0.2)[0]:
                                    ch3 = _os.read(fd, 1).decode("utf-8", errors="replace")
                                    if ch3 == "A":
                                        key = "up"
                                    elif ch3 == "B":
                                        key = "down"
                            else:
                                key = None
                        else:
                            key = "esc"
                    elif ch in ("\r", "\n"):
                        key = "enter"
                    elif ch == "\x03":
                        raise KeyboardInterrupt
                    else:
                        key = None

                    if key == "up" and selected > 0:
                        selected -= 1
                    elif key == "down" and selected < total - 1:
                        selected += 1
                    elif key == "enter":
                        break
                    else:
                        continue
                    # 重绘：上移 + 清除 + 重新打印
                    _sys.stdout.write(f"\033[{num_lines}A\033[J")
                    _print_menu()
            finally:
                _termios.tcsetattr(fd, _termios.TCSADRAIN, old_settings)

            # 清除菜单行
            _sys.stdout.write(f"\033[{num_lines}A\033[J")
            _sys.stdout.flush()

            choice = selected

            if choice == len(sessions):
                # 新建会话
                default_name = f"会话_{datetime.now().strftime('%m%d_%H%M')}"
                name = Prompt.ask("[dim]新会话名称[/dim]", default=default_name)
                ss.create_session(name)
                self.active_session_name = name
                self.history = []
                self._init_session_memory(name)
            elif 0 <= choice < len(sessions):
                # 选择历史会话
                chosen = sessions[choice]
                name = chosen["name"]
                history = ss.load(name)
                if history is not None:
                    self.history = history
                self.active_session_name = name
                self._init_session_memory(name)
            else:
                # 回退到上次会话或新建
                if active_name:
                    history = ss.load(active_name)
                    if history is not None:
                        self.history = history
                    self.active_session_name = active_name
                    self._init_session_memory(active_name)
                else:
                    name = f"会话_{datetime.now().strftime('%m%d_%H%M')}"
                    ss.create_session(name)
                    self.active_session_name = name
                    self.history = []
                    self._init_session_memory(name)
        else:
            # 无历史会话：直接问新名称
            default_name = f"会话_{datetime.now().strftime('%m%d_%H%M')}"
            name = Prompt.ask("[dim]新会话名称[/dim]", default=default_name)
            ss.create_session(name)
            self.active_session_name = name
            self.history = []
            self._init_session_memory(name)
        # 不刷新启动页——只渲染一次

    def _init_session_memory(self, session_name: str) -> None:
        """为指定会话初始化独立的跨会话记忆文件。"""
        try:
            from pathlib import Path as _Path
            session_safe = session_name.replace("/", "_").replace("\\", "_").replace(" ", "_")
            memory_path = settings.storage_path / "memory" / "sessions" / session_safe
            self.cross_session_memory = CrossSessionMemory(storage_path=memory_path)
        except Exception as e:
            console.print(f"[dim]会话记忆初始化失败: {e}[/dim]")
            self.cross_session_memory = None

    def _save_active_session(self) -> None:
        """保存当前活跃会话（退出时调用）。"""
        if not self.active_session_name:
            return
        try:
            from core.session.store import SessionStore
            ss = SessionStore()
            ss.save(self.active_session_name, self.history)
            ss.save_active_session(self.active_session_name)
        except Exception:
            pass

    def _auto_save_session(self) -> None:
        """自动保存会话（每次对话后调用）。"""
        if not self.active_session_name or not self.history:
            return
        try:
            from core.session.store import SessionStore
            ss = SessionStore()
            ss.save(self.active_session_name, self.history)
        except Exception:
            pass

    # ---- 启动 ----

    def run(self) -> None:
        """启动 REPL 主循环。"""
        # 初始化活跃会话（内部已处理启动页渲染 + 会话询问 + 刷新）
        self._init_active_session()
        # 跨天检查：提示用户处理昨日未完成任务
        try:
            self._check_carry_over()
        except Exception:
            pass  # 跨天检查失败不影响 REPL 启动

        while self.running:
            try:
                user_input = _read_input()
            except (EOFError, KeyboardInterrupt):
                console.print("\n[dim]再见[/dim]")
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

        # 退出时自动保存活跃会话
        self._save_active_session()

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
                title="[bold cyan]AI 解读[/bold cyan]",
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
            with console.status("[bold yellow]AI Thinking...[/bold yellow]", spinner="dots"):
                answer = self.reader.ask(user_input)
            console.print(Panel(
                Text(answer),
                title="[bold cyan]阅读助手[/bold cyan]",
                border_style="cyan",
                padding=(1, 2),
            ))

    # ---- 命令处理 ----

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
        # 1. 空参数（如 "/memory"）：显示菜单让用户选
        # 2. 参数为纯数字（如 "/memory 3"）：作为菜单编号处理
        # 3. 非数字参数（如 "/memory clear"）：跳过菜单，直接执行
        # _menu_skip 标志用于递归调用时跳过菜单（避免死循环）
        trigger_menu = False
        menu_numeric_arg = None
        if cmd in self.SUBCOMMAND_MENU and not getattr(self, '_menu_skip', False):
            if not arg or arg.isdigit():
                # 空参数 → 显示菜单；纯数字参数 → 菜单编号选择
                trigger_menu = True
                if arg.isdigit():
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

        # dict 派发
        handler_name = self._COMMAND_DISPATCH.get(cmd)
        if handler_name is None:
            console.print(f"[red]未知命令:[/red] {cmd}  [dim]输入 /help 查看所有命令[/dim]")
            return

        handler = getattr(self, handler_name)
        handler(arg)

        # 工作流模式记录 + 下一步推荐（除 exit/unknown）
        if cmd not in ("/exit", "/quit", "exit", "quit"):
            self._record_workflow(cmd)

    # ---- 各命令实现 ----

    def _cmd_help(self, arg: str) -> None:
        """显示帮助信息。"""
        console.print(Panel(
            HELP_TEXT,
            border_style="yellow",
            title="[bold yellow]帮助[/bold yellow]",
            title_align="left",
            padding=(1, 2),
        ))

    def _cmd_exit(self, arg: str) -> None:
        """退出 REPL。"""
        self.running = False
        console.print("[dim]再见[/dim]")

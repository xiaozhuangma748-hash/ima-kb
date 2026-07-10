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


class REPL(
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
        self._admin_init_failed: bool = False
        self._vector_available: Optional[bool] = None  # None=未检测, True/False=已检测
        if self.pet:
            try:
                self.memory_store = MemoryStore()
                self.workflow_tracker = WorkflowTracker(self.memory_store)
            except Exception as e:
                console.print(f"[dim]记忆系统初始化失败: {e}[/dim]")

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
            self._admin_init_failed = True

    # ---- 启动 ----

    def run(self) -> None:
        """启动 REPL 主循环。"""
        # 清屏 + 渲染欢迎面板
        console.clear()
        stats = self.storage.stats()
        _render_welcome_panel(stats, self.llm_available, pet=self.pet)

        # 底部提示只在启动时显示一次
        import shutil
        _width = shutil.get_terminal_size((80, 24)).columns
        _left = "/help for shortcuts"
        _right = "Ctrl+C to exit"
        _middle = _width - len(_left) - len(_right)
        if _middle < 1:
            _middle = 1
        console.print(f"[dim]{_left}{' ' * _middle}{_right}[/dim]")
        console.print()

        # 续接上次会话 (--continue)
        if os.environ.get("IMA_CONTINUE"):
            try:
                from core.session.store import SessionStore
                ss = SessionStore()
                sessions = ss.list_sessions()
                if sessions:
                    latest = sessions[0]
                    loaded = ss.load(latest["name"])
                    self.history = loaded if isinstance(loaded, list) else []
                    console.print(f"[green]已恢复会话: {latest['name']} ({latest['message_count']} 条消息)[/green]\n")
                else:
                    console.print("[dim]无已保存会话[/dim]\n")
            except Exception as e:
                console.print(f"[dim]恢复会话失败: {e}[/dim]\n")

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
            with console.status("[bold yellow]AI 思考中...[/bold yellow]", spinner="dots"):
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

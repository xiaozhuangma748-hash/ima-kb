"""Agent 模式 Mixin。

从 repl.py 第 2842-3001 行迁移：
- ``_cmd_agent`` Agent 模式（LLM 自主调工具完成复杂任务）
- ``_cmd_smart`` 智能路由（AI 自主决策执行）
"""
from __future__ import annotations

import json
import time
from pathlib import Path

from rich.markdown import Markdown
from rich.live import Live
from rich.spinner import Spinner
from rich.text import Text

from core.llm.client import get_llm, LLMError
from core.cli.constants import console


# Agent 配置持久化路径
_AGENT_CONFIG_PATH = Path(__file__).resolve().parents[3] / "storage" / "agent_config.json"


def _load_agent_config() -> dict:
    """加载 Agent 配置。"""
    if not _AGENT_CONFIG_PATH.exists():
        return {"show_thoughts": False}
    try:
        with open(_AGENT_CONFIG_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"show_thoughts": False}


def _save_agent_config(config: dict) -> None:
    """保存 Agent 配置。"""
    try:
        _AGENT_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(_AGENT_CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(config, f, ensure_ascii=False, indent=2)
    except Exception as e:
        console.print(f"[yellow]保存 Agent 配置失败: {e}[/yellow]")


def _wrap_indented(content: str, indent: int = 4, width: int = 0) -> list[Text]:
    """将内容按指定宽度换行，每行带缩进。

    Args:
        content: 内容文本
        indent: 缩进空格数
        width: 每行最大宽度（0 = 不限制）

    Returns:
        Text 对象列表
    """
    if not width:
        width = console.width - indent
    if width <= 10:
        width = 50

    lines = []
    remaining = content
    while remaining:
        if len(remaining) <= width:
            lines.append(remaining)
            break
        break_pos = width
        for i in range(width, max(0, width - 20), -1):
            if remaining[i] in (" ", "，", "。", "、", "；", "：", ",", ".", ";", ":"):
                break_pos = i + 1
                break
        lines.append(remaining[:break_pos])
        remaining = remaining[break_pos:]

    result = []
    for line in lines:
        t = Text()
        t.append(" " * indent)
        t.append(line, style="dim")
        result.append(t)
    return result


class _ThinkingStatus:
    """Show Thoughts 模式下的动态 Thinking 显示。"""

    def __init__(self, start_time: float) -> None:
        self._start = start_time

    def __rich_console__(self, console, options):
        elapsed = time.time() - self._start
        desc = f"Thinking {elapsed:.1f}s"
        yield Spinner("dots", text=Text(f" {desc}", style="dim"), style="cyan")


class _AgentStatus:
    """Dynamic status renderable for Hide Thoughts mode.

    Implements __rich_console__ so Live's refresh loop creates a fresh
    Spinner each frame — both the animation frame and the text are
    always up-to-date. No timer thread needed.

    States:
    - thinking: shows elapsed seconds (e.g. "Thinking 3s")
    - static:   shows tool name + optional detail (e.g. "search · 1234 chars")
    """

    def __init__(self, task_start: float) -> None:
        self._thinking = True
        self._label = "Thinking"
        self._detail = ""
        self._start = task_start

    def set_thinking(self) -> None:
        self._thinking = True
        # 不重置 _start，让计时器从任务开始持续增长

    def set_static(self, label: str, detail: str = "") -> None:
        self._thinking = False
        self._label = label
        self._detail = detail

    def __rich_console__(self, console, options):
        if self._thinking:
            elapsed = time.time() - self._start
            desc = f"Thinking {elapsed:.1f}s"
        else:
            desc = self._label
            if self._detail:
                desc = f"{desc} · {self._detail}"
        yield Spinner("dots", text=Text(f" {desc}", style="dim"), style="cyan")


class AgentMixin:
    """Agent 模式与智能路由。"""

    def _make_agent_on_step(self, show_thoughts: bool = True):
        """创建 Agent on_step 回调 — 极简垂直流风格。

        Show Thoughts 模式展示完整的 ReAct 链路：
          Thinking 2.3s
            用户在问爱情的定义，我需要从多个角度...
          > search "爱情 定义"
            10 results · top 4.85

        Hide Thoughts 模式只显示动态 spinner：
          Thinking 12.4s

        Args:
            show_thoughts: 是否显示 thought 详细内容

        返回 (on_step, stop_spinner, t0, step_n) 四元组。
        """
        t0 = time.time()
        llm_start = [0]
        spinner = [None]
        live = [None]
        agent_status = _AgentStatus(t0)
        step_n = [0]
        last_tool = [None]
        # 流式输出状态
        stream_live = [None]
        stream_text = [""]
        final_displayed = [False]  # 最终答案是否已在 done 事件中输出

        def _stop_spinner():
            if spinner[0]:
                spinner[0].stop()
                spinner[0] = None

        def _stop_live():
            if live[0]:
                live[0].stop()
                live[0] = None

        def _stop_stream_live():
            if stream_live[0]:
                stream_live[0].stop()
                stream_live[0] = None

        def _stop():
            _stop_spinner()
            _stop_live()
            _stop_stream_live()

        def _ensure_live():
            if live[0] is None:
                live[0] = Live(
                    agent_status, console=console, transient=True,
                    refresh_per_second=8,
                )
                live[0].start()

        def on_step(step_type: str, content: str) -> None:
            if step_type == "llm_start":
                step_n[0] += 1
                llm_start[0] = time.time()
                _stop_spinner()
                if show_thoughts:
                    # Show Thoughts: 步骤间用细线分隔（第一步除外）
                    if step_n[0] > 1:
                        console.print(Text("  " + "─" * 40, style="bright_black"))
                    # 启动 Thinking spinner
                    thinking_status = _ThinkingStatus(llm_start[0])
                    spinner[0] = Live(
                        thinking_status, console=console, transient=True,
                        refresh_per_second=8,
                    )
                    spinner[0].start()
                else:
                    agent_status.set_thinking()
                    _ensure_live()

            elif step_type == "thought":
                if show_thoughts:
                    # Show Thoughts: 停止 spinner，打印思考时间和内容
                    _stop_spinner()
                    elapsed = time.time() - llm_start[0]
                    # 打印思考时间
                    console.print(f"  [dim]Thinking {elapsed:.1f}s[/dim]")
                    # 缩进显示思考内容（dim 风格，4 空格缩进）
                    if content.strip():
                        indented_lines = _wrap_indented(content, indent=4)
                        for line in indented_lines:
                            console.print(line)
                # Hide Thoughts: 不打印任何内容，保持 spinner 继续运行

            elif step_type == "tool":
                last_tool[0] = content
                _stop_spinner()
                if show_thoughts:
                    # Show Thoughts: 用箭头前缀显示工具调用
                    console.print(f"  [bold yellow]→[/bold yellow] [cyan]{content}[/cyan]")
                    # 启动工具执行 spinner
                    spinner[0] = Live(
                        Spinner("dots", text=Text("    executing...", style="dim")),
                        console=console, transient=True, refresh_per_second=10,
                    )
                    spinner[0].start()
                # Hide Thoughts: 不显示工具调用，保持 Thinking spinner 即可

            elif step_type == "result":
                _stop_spinner()
                if show_thoughts:
                    # Show Thoughts: 显示工具结果摘要
                    summary = content.replace('\n', ' ').strip()
                    if len(summary) > 120:
                        summary = summary[:120] + "..."
                    console.print(f"    [dim]{summary}[/dim]")
                    console.print()  # 空行分隔
                # Hide Thoughts: 不打印工具结果

            elif step_type == "error":
                _stop()
                err = content.replace('\n', ' ').strip()
                if len(err) > 150:
                    err = err[:150] + "..."
                if show_thoughts:
                    console.print(f"  [red]✗ {err}[/red]")
                    console.print()
                else:
                    console.print(f"  [red][ERR] {err}[/red]")

            elif step_type == "stream_start":
                # 流式输出开始：停止 spinner，启动 Live 组件
                _stop_spinner()
                _stop_live()
                stream_text[0] = ""
                stream_live[0] = Live(
                    Text(""),
                    console=console,
                    refresh_per_second=30,
                    transient=True,
                )
                stream_live[0].start()

            elif step_type == "stream_token":
                # 流式输出 token：实时更新文本
                if stream_live[0]:
                    stream_text[0] += content
                    # 流式过程中用纯文本渲染（去掉 ** 标记），保证流畅性
                    clean_text = stream_text[0].replace("**", "")
                    stream_live[0].update(Text(clean_text))

            elif step_type == "done":
                _stop()
                # 如果有流式输出，用 Markdown 重新渲染最终结果，并加"总结"标题
                if stream_text[0]:
                    _stop_stream_live()
                    console.print()
                    console.print("[bold green]总结[/bold green]")
                    console.print()
                    console.print(Markdown(stream_text[0]))
                    stream_text[0] = ""
                    final_displayed[0] = True

        return on_step, _stop, t0, step_n, final_displayed

    def _cmd_agent(self, arg: str) -> None:
        """Agent 模式：/agent <任务描述>

        LLM 自主调工具完成复杂任务（搜索、读文档、分析数据等）。

        子命令：
        - /agent think on     Show thoughts
        - /agent think off    Hide thoughts (default)
        """
        if not arg:
            console.print("[yellow]Usage: /agent <task description>[/yellow]")
            console.print("  [cyan]/agent think on[/cyan]  · Show thoughts")
            console.print("  [cyan]/agent think off[/cyan] · Hide thoughts (default)")
            console.print("[dim]示例:[/dim]")
            console.print("  [cyan]/agent 列出所有关于骨灰安置的政策并总结要点[/cyan]")
            console.print("  [cyan]/agent 找到最新政策，阅读第 1 段并解读[/cyan]")
            console.print("  [cyan]/agent 分析 ~/Desktop/数据.xlsx 并跟入库文档对比[/cyan]")
            return

        # 处理子命令 /agent think on|off
        parts = arg.strip().split(maxsplit=1)
        if parts and parts[0].lower() == "think":
            self._cmd_agent_think(parts[1] if len(parts) > 1 else "")
            return

        if not self.llm_available:
            console.print("[red]LLM 未配置，无法使用 Agent 模式[/red]")
            return

        config = _load_agent_config()
        show_thoughts = bool(config.get("show_thoughts", False))

        from core.agent.agent import Agent
        try:
            ag = Agent(storage=self.storage)
        except Exception as e:
            console.print(f"[red]初始化失败: {e}[/red]")
            return

        mode_hint = " · Show Thoughts" if show_thoughts else " · Hide Thoughts"
        console.print(f"\n[bold magenta]Agent[/bold magenta] · Task: [cyan]{arg}[/cyan][dim]{mode_hint}[/dim]\n")

        on_step, stop_spinner, t0, step_n, final_displayed = self._make_agent_on_step(show_thoughts=show_thoughts)

        try:
            result = ag.run(arg, on_step=on_step, show_thoughts=show_thoughts)
            stop_spinner()
            # 如果 done 事件已经输出了最终答案，不再重复输出
            if not final_displayed[0]:
                console.print()
                console.print("[bold green]总结[/bold green]")
                console.print()
                console.print(Markdown(result))
            console.print()
            elapsed = time.time() - t0
            console.print(f"[bold magenta]✻ ✓ Complete[/bold magenta] [dim]· Brewed for {elapsed:.1f}s · {step_n[0]} Steps[/dim]\n")
            # 宠物经验埋点：agent 行为
            self._pet_gain_exp(15, "agent")
        except LLMError as e:
            stop_spinner()
            err_msg = str(e).replace("[", "\\[")
            console.print(f"\n[red]LLM 调用失败: {err_msg}[/red]")
            console.print("[dim]  请检查 API_KEY 和网络连接[/dim]")
        except Exception as e:
            stop_spinner()
            err_msg = str(e).replace("[", "\\[")
            err_lower = err_msg.lower()
            # 识别网络类错误，给出排查建议
            is_network_err = any(
                kw in err_lower
                for kw in ("connection", "apiconnection", "apitimeout", "timeout", "5xx", "502", "503", "504")
            )
            console.print(f"\n[red]Agent 执行失败: {type(e).__name__}: {err_msg}[/red]")
            if is_network_err:
                console.print(
                    "\n[yellow]! 这是网络连接错误，常见原因：[/yellow]\n"
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

    def _cmd_agent_think(self, arg: str) -> None:
        """控制 Agent 思考过程显示：/agent think on|off"""
        arg = arg.strip().lower()
        config = _load_agent_config()
        if arg == "on":
            config["show_thoughts"] = True
            _save_agent_config(config)
            console.print("[green]✅ Thoughts shown[/green]")
            console.print("[dim]Detailed reasoning will be displayed in next /agent task[/dim]")
        elif arg == "off" or arg == "":
            config["show_thoughts"] = False
            _save_agent_config(config)
            console.print("[green]✅ Thoughts hidden[/green]")
            console.print("[dim]Only tool status will be displayed in next /agent task[/dim]")
        else:
            console.print(f"[yellow]Usage: /agent think on|off (current: {'on' if config.get('show_thoughts') else 'off'})[/yellow]")

    def _cmd_smart(self, arg: str) -> None:
        """智能路由：/smart <自然语言描述> — AI 自主决策执行。

        优先走 Agent ReAct 循环(Thought -> Tool -> Result -> Next)，
        失败时回退到旧的 LLM 命令路由。
        """
        if not arg:
            console.print("[yellow]用法: /smart <自然语言描述>[/yellow]")
            console.print("[dim]示例:[/dim]")
            console.print("  [cyan]/smart 总结 862e0973[/cyan]")
            console.print("  [cyan]/smart 对比 862e 和 02fd[/cyan]")
            console.print("  [cyan]/smart 找骨灰安置政策并总结[/cyan]")
            return

        if not self.llm_available:
            console.print("[red]LLM 未配置[/red]")
            return

        # 优先: Agent ReAct 循环
        on_step = None
        stop_spinner = None
        try:
            from core.agent.agent import Agent
            agent = Agent(storage=self.storage)
            config = _load_agent_config()
            show_thoughts = bool(config.get("show_thoughts", False))
            mode_hint = " · Show Thoughts" if show_thoughts else " · Hide Thoughts"
            console.print(f"[bold magenta]Agent[/bold magenta] · Task: [cyan]{arg}[/cyan][dim]{mode_hint}[/dim]\n")

            on_step, stop_spinner, t0, step_n, final_displayed = self._make_agent_on_step(show_thoughts=show_thoughts)
            result = agent.run(arg, on_step=on_step, show_thoughts=show_thoughts)
            stop_spinner()
            # 如果 done 事件已经输出了最终答案，不再重复输出
            if not final_displayed[0] and result:
                console.print()
                console.print("[bold green]总结[/bold green]")
                console.print()
                console.print(Markdown(result))
            console.print()
            elapsed = time.time() - t0
            console.print(f"[bold magenta]✻ ✓ Complete[/bold magenta] [dim]· Brewed for {elapsed:.1f}s · {step_n[0]} Steps[/dim]\n")
            # 宠物经验埋点
            self._pet_gain_exp(8, "smart")
            return
        except Exception as e:
            if stop_spinner:
                stop_spinner()
            console.print(f"[dim]Agent 模式失败，回退到命令路由: {e}[/dim]\n")

        # 回退: 旧的 LLM 命令路由
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
            with console.status("[bold yellow]判断该用什么命令...[/bold yellow]", spinner="dots"):
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

            console.print(f"[green]智能路由[/green] → [bold cyan]{cmd_line}[/bold cyan]\n")
            # 宠物经验埋点：smart 行为
            self._pet_gain_exp(8, "smart")
            # 执行路由到的命令
            self._handle_command(cmd_line)
        except LLMError as e:
            err_msg = str(e).replace("[", "\\[")
            console.print(f"[red]路由失败:[/red] {err_msg}")
            # 404 通常意味着模型下线了，给出排查建议
            if "404" in err_msg or "NotFound" in err_msg:
                console.print("\n[yellow]可能原因：模型已下线或 API 地址变更[/yellow]")
                console.print("[dim]  1. 检查模型名是否正确：[/dim]")
                console.print(f"[dim]     cat .env | grep LLM_MODEL[/dim]")
                console.print("[dim]  2. 尝试备用模型 agnes-1.5-flash：[/dim]")
                console.print(f"[dim]     sed -i '' 's/LLM_MODEL=.*/LLM_MODEL=agnes-1.5-flash/' .env[/dim]")
            console.print("[dim]  你也可以直接用对应命令：/search /report /compare /analyze /read /agent[/dim]")

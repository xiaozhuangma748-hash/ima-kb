"""Agent 模式 Mixin。

从 repl.py 第 2842-3001 行迁移：
- ``_cmd_agent`` Agent 模式（LLM 自主调工具完成复杂任务）
- ``_cmd_smart`` 智能路由（AI 自主决策执行）
"""
from __future__ import annotations

import time

from rich.markdown import Markdown
from rich.live import Live
from rich.spinner import Spinner
from rich.text import Text

from core.llm.client import get_llm, LLMError
from core.cli.constants import console


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


class AgentMixin:
    """Agent 模式与智能路由。"""

    def _make_agent_on_step(self):
        """创建 Agent on_step 回调 — Trae 垂直风格。

        参考 Trae IDE 的展示方式：
        - 每个步骤有图标 + 标题
        - 内容缩进显示在标题下方
        - 无竖线装饰，层次清晰

        返回 (on_step, stop_spinner, t0, step_n) 四元组。
        """
        t0 = time.time()
        llm_start = [0]
        spinner = [None]
        step_n = [0]
        last_tool = [None]

        def _stop():
            if spinner[0]:
                spinner[0].stop()
                spinner[0] = None

        def on_step(step_type: str, content: str) -> None:
            if step_type == "llm_start":
                llm_start[0] = time.time()
                _stop()
                spinner[0] = Live(
                    Spinner("dots", text=" [dim]思考中...[/dim]"),
                    console=console, transient=True, refresh_per_second=10,
                )
                spinner[0].start()

            elif step_type == "thought":
                _stop()
                step_n[0] += 1
                elapsed = time.time() - llm_start[0]
                thought = content.replace('\n', ' ').replace('\\n', ' ').strip()
                if len(thought) > 150:
                    thought = thought[:150] + "..."
                # 标题行：图标 + 思考 + 耗时
                header = Text()
                header.append("  ", style="bright_black")
                header.append("[T]", style="bright_black")
                header.append("  ", style="bright_black")
                header.append(f"思考  {elapsed:.1f}s", style="bold dim")
                console.print(header)
                # 内容缩进（与 [T] 对齐）
                for line in _wrap_indented(thought, indent=2):
                    console.print(line)

            elif step_type == "tool":
                _stop()
                last_tool[0] = content
                spinner[0] = Live(
                    Spinner("dots", text=f" [dim]{content}[/dim]"),
                    console=console, transient=True, refresh_per_second=10,
                )
                spinner[0].start()

            elif step_type == "result":
                _stop()
                tool = last_tool[0] or "tool"
                tool_parts = tool.split()
                tool_name = tool_parts[0] if tool_parts else tool
                header = Text()
                header.append("  ", style="bright_black")
                header.append("[OK]", style="green")
                header.append("  ", style="bright_black")
                header.append(f"{tool_name}  ({len(content)} 字符)", style="dim")
                console.print(header)

            elif step_type == "error":
                _stop()
                err = content.replace('\n', ' ').strip()
                if len(err) > 150:
                    err = err[:150] + "..."
                header = Text()
                header.append("  ", style="bright_black")
                header.append("[ERR]", style="red")
                header.append("  ", style="bright_black")
                header.append(err, style="red")
                console.print(header)

            elif step_type == "done":
                _stop()

        return on_step, _stop, t0, step_n

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

        console.print(f"\n[bold magenta]Agent 启动[/bold magenta] · 任务: [cyan]{arg}[/cyan]\n")

        on_step, stop_spinner, t0, step_n = self._make_agent_on_step()

        try:
            result = ag.run(arg, on_step=on_step)
            stop_spinner()
            elapsed = time.time() - t0
            console.print(f"\n[bold magenta]✓ 完成[/bold magenta] [dim]· {elapsed:.1f}s · 共 {step_n[0]} 步[/dim]\n")
            # 直接 Markdown 输出，不用 Panel 包裹
            console.print(Markdown(result))
            console.print()
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
        try:
            from core.agent.agent import Agent
            agent = Agent(storage=self.storage)
            console.print(f"[bold magenta]Agent 启动[/bold magenta] · 任务: [cyan]{arg}[/cyan]\n")

            on_step, stop_spinner, t0, step_n = self._make_agent_on_step()
            result = agent.run(arg, on_step=on_step)
            stop_spinner()
            elapsed = time.time() - t0
            console.print(f"\n[bold magenta]✓ 完成[/bold magenta] [dim]· {elapsed:.1f}s · 共 {step_n[0]} 步[/dim]\n")
            if result:
                console.print(Markdown(result))
            console.print()
            # 宠物经验埋点
            self._pet_gain_exp(8, "smart")
            return
        except Exception as e:
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

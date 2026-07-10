"""Agent 模式 Mixin。

从 repl.py 第 2842-3001 行迁移：
- ``_cmd_agent`` Agent 模式（LLM 自主调工具完成复杂任务）
- ``_cmd_smart`` 智能路由（AI 自主决策执行）
"""
from __future__ import annotations

from rich.panel import Panel
from rich.text import Text
from rich.markdown import Markdown

from core.llm.client import get_llm, LLMError
from core.cli.constants import console


class AgentMixin:
    """Agent 模式与智能路由。"""

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
            console.print("[dim]Agent 模式启动...[/dim]\n")
            result = agent.run(arg)
            if result:
                console.print(Markdown(result))
            console.print()
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

"""分析 Mixin。

从 repl.py 第 2665-2838 行迁移：
- ``_cmd_report`` 生成文档分析报告
- ``_cmd_read`` 智能阅读模式
- ``_render_read_chunk`` 渲染当前阅读段
- ``_cmd_compare`` 智能对比
"""
from __future__ import annotations

from pathlib import Path

from rich.panel import Panel
from rich.text import Text
from rich.live import Live
from rich.spinner import Spinner

from core.cli.constants import console
from core.cli.welcome import _record_activity


class AnalyzeMixin:
    """数据分析与智能阅读相关命令。"""

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
            console.print(f"\n[bold]生成报告...[/bold] [dim]ID: {doc_id}[/dim]")
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
        console.print(f"\n[bold cyan]进入阅读模式[/bold cyan]")
        console.print(f"  文档: [bold]{state.doc_title}[/bold]")
        console.print(f"  共 {state.total_chunks} 段\n")
        _record_activity("read", state.doc_title[:40])
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
            title="[bold cyan]AI 解读[/bold cyan]",
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

        console.print(f"\n[bold]对比中[/bold]")
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
                title="[bold yellow]智能对比报告[/bold yellow]",
                border_style="yellow",
                padding=(1, 2),
            ))
            # 宠物经验埋点：compare 行为
            self._pet_gain_exp(10, "compare")
            _record_activity("compare", f"{a[:15]} vs {b[:15]}")
        except FileNotFoundError as e:
            console.print(f"[red]{e}[/red]")
        except Exception as e:
            err_msg = str(e).replace("[", "\\[")
            console.print(f"[red]对比失败: {type(e).__name__}: {err_msg}[/red]")

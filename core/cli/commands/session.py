"""会话管理 Mixin。

从 repl.py 第 2529-2664 行迁移，包含：
- ``_cmd_save`` 保存当前会话
- ``_cmd_load`` 恢复已保存的会话
- ``_cmd_sessions`` 列出所有已保存会话
- ``_cmd_export`` 导出会话为 Markdown
- ``_cmd_session`` 会话管理子命令入口
- ``_cmd_session_delete`` 删除已保存的会话
"""
from __future__ import annotations

from pathlib import Path

from rich.table import Table

from core.cli.constants import console

try:
    from core.desktop.cli_sync import _try_push_content as _try_pet_push
except Exception:
    _try_pet_push = None


class SessionMixin:
    """会话管理相关命令。"""

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

    def _cmd_sessions(self, arg: str = "") -> None:
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
        # P3: 推送会话列表到桌宠气泡
        if _try_pet_push:
            lines = [f"📋 已保存会话（共 {len(sessions)} 个）"]
            for s in sessions[:6]:
                lines.append(f"- **{s['name']}** · {s['message_count']}条 · {s['saved_at'][:10]}")
            if len(sessions) > 6:
                lines.append(f"... 还有 {len(sessions) - 6} 个")
            _try_pet_push("\n".join(lines), "markdown")

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
        """会话管理子命令：/session new|save|load|list|export|delete [参数]

        整合了 /save /load /sessions /export 四个命令，并新增 new 用于新建会话。
        """
        if not arg:
            console.print("[bold]会话管理[/bold] [dim]（/session new|save|load|list|export|delete）[/dim]\n")
            console.print("  [cyan]/session new[/cyan]             新建会话（清空当前对话历史）")
            console.print("  [cyan]/session save [名称][/cyan]     保存当前会话")
            console.print("  [cyan]/session load <名称>[/cyan]     恢复已保存的会话")
            console.print("  [cyan]/session list[/cyan]           列出所有已保存会话")
            console.print("  [cyan]/session export <名称> [路径][/cyan]  导出为 Markdown")
            console.print("  [cyan]/session delete <名称>[/cyan]  删除已保存的会话")
            console.print("\n[dim]别名: /save /load /sessions /export /clear 仍可使用[/dim]")
            return

        parts = arg.split(maxsplit=1)
        sub = parts[0].lower()
        sub_arg = parts[1].strip() if len(parts) > 1 else ""

        if sub in ("new", "reset"):
            # 新建会话：清空历史 + 问新名称 + 创建会话 + 切换活跃会话
            # 不能只调 _cmd_clear（那样 active_session_name 不变，新对话会存到旧会话下）
            self._cmd_session_new(sub_arg)
        elif sub == "save":
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
            console.print("[dim]可用: new / save / load / list / export / delete[/dim]")

    def _cmd_session_new(self, name: str = "") -> None:
        """新建会话：清空历史 + 创建新会话 + 切换活跃会话。

        与 /clear 的区别：/clear 只清空历史但 active_session_name 不变，
        后续对话会存到旧会话下；/session new 会创建新会话并切换。
        """
        from core.session.store import SessionStore
        from datetime import datetime
        from core.cli.terminal_helpers import repl_input as _repl_input

        # 如果未提供名称，询问
        if not name:
            default_name = f"会话_{datetime.now().strftime('%m%d_%H%M')}"
            name = _repl_input("新会话名称", default=default_name)
            if not name:
                name = default_name

        ss = SessionStore()
        ss.create_session(name)
        # 清空当前对话历史 + 早期摘要
        self.history = []
        self.conversation_summary = None
        # 切换活跃会话
        self.active_session_name = name
        # 初始化新会话的跨会话记忆
        self._init_session_memory(name)
        # 清掉数据分析追问 + 阅读模式状态
        cleared = []
        if self.current_analysis is not None:
            self.current_analysis = None
            cleared.append("数据分析")
        if self.reader is not None:
            self.reader.close()
            self.reader = None
            cleared.append("阅读模式")
        extra = f" + {'/'.join(cleared)}" if cleared else ""
        console.print(
            f"[green]✓ 已新建会话[/green] [bold]{name}[/bold] [dim](历史已清空{extra})[/dim]"
        )

    def _cmd_session_delete(self, name: str) -> None:
        """删除已保存的会话，支持批量: /session delete 王七 王六 王五。"""
        if not name:
            console.print("[yellow]用法: /session delete <名称> [<名称> ...][/yellow]")
            console.print("[dim]支持一次删除多个会话，用空格分隔[/dim]")
            console.print("[dim]用 /session list 查看已保存的会话[/dim]")
            return
        names = name.split()
        try:
            from core.session.store import SessionStore
            ss = SessionStore()
            ok_count = 0
            fail_count = 0
            for n in names:
                if ss.delete(n):
                    console.print(f"[green]✓ 已删除会话: [cyan]{n}[/cyan][/green]")
                    ok_count += 1
                else:
                    console.print(f"[yellow]未找到会话: {n}[/yellow]")
                    fail_count += 1
            if len(names) > 1:
                console.print(f"[dim]共删除 {ok_count} 个" +
                              (f"，{fail_count} 个未找到" if fail_count else "") + "[/dim]")
        except Exception as e:
            err_msg = str(e).replace("[", "\\[")
            console.print(f"[red]删除会话失败: {err_msg}[/red]")

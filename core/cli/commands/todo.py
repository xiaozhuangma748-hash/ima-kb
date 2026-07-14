"""每日任务（todo）命令 Mixin。

提供 /todo 命令族：
- /todo                    显示今日任务
- /todo add <描述>          添加任务（-p high -n 备注）
- /todo done <序号|id>      标记完成
- /todo cancel <序号|id>    取消
- /todo reopen <序号|id>    重开
- /todo del <序号|id>       彻底删除
- /todo edit <序号|id> <新>  编辑描述
- /todo pri <序号|id> <p>   改优先级
- /todo history [N|日期]    历史记录
- /todo clear               清空今日
- /todo carry               手动触发跨天处理
"""
from __future__ import annotations

from typing import Optional

from rich.table import Table
from rich.prompt import Prompt

from core.todo.manager import TodoManager, TodoItem, VALID_PRIORITIES
from core.cli.constants import console


# 优先级显示标记
_PRIORITY_MARK = {"high": "[red]高[/red]", "medium": "[yellow]中[/yellow]", "low": "[dim]低[/dim]"}
_PRIORITY_TAG = {"high": "high", "medium": "med", "low": "low"}
_STATUS_MARK = {"pending": " ", "done": "[green]v[/green]", "cancelled": "[dim]x[/dim]"}


class TodoMixin:
    """每日任务相关命令。"""

    @property
    def todo_mgr(self) -> TodoManager:
        """懒加载 TodoManager（实例级，避免跨实例共享）。"""
        mgr = getattr(self, "_todo_mgr", None)
        if mgr is None:
            mgr = TodoManager()
            self._todo_mgr = mgr
        return mgr

    def _cmd_todo(self, arg: str) -> None:
        """每日任务入口：/todo [子命令] [参数]"""
        parts = arg.split(maxsplit=1) if arg else []
        sub = parts[0].lower() if parts else ""
        sub_arg = parts[1].strip() if len(parts) > 1 else ""

        # 子命令缩写
        ALIASES = {
            "a": "add", "d": "done", "dn": "done",
            "c": "cancel", "cc": "cancel",
            "r": "reopen", "ro": "reopen",
            "del": "del", "rm": "del", "delete": "del",
            "e": "edit", "ed": "edit",
            "p": "pri", "pr": "pri", "priority": "pri",
            "h": "history", "hist": "history",
            "cl": "clear", "cls": "clear",
            "cy": "carry",
            "l": "list", "ls": "list",
        }
        sub = ALIASES.get(sub, sub)

        if sub in ("", "list"):
            self._todo_show_today()
        elif sub == "add":
            self._todo_add(sub_arg)
        elif sub == "done":
            self._todo_set_status(sub_arg, "done")
        elif sub == "cancel":
            self._todo_set_status(sub_arg, "cancelled")
        elif sub == "reopen":
            self._todo_set_status(sub_arg, "pending")
        elif sub == "del":
            self._todo_delete(sub_arg)
        elif sub == "edit":
            self._todo_edit(sub_arg)
        elif sub == "pri":
            self._todo_set_priority(sub_arg)
        elif sub == "history":
            self._todo_history(sub_arg)
        elif sub == "clear":
            self._todo_clear()
        elif sub == "carry":
            self._todo_carry_prompt()
        else:
            self._todo_help()

    # ---- 显示 ----

    def _todo_show_today(self) -> None:
        """显示今日任务。"""
        items = self.todo_mgr.list_day()
        stats = self.todo_mgr.stats_day()
        today = stats["date"]

        if not items:
            console.print(f"\n[bold]今日任务[/bold] [dim]· {today}[/dim]")
            console.print("[dim]暂无任务  用 /todo add <描述> 添加[/dim]\n")
            return

        console.print(
            f"\n[bold]今日任务[/bold] [dim]· {today} "
            f"({stats['done']}/{stats['total']} 完成)[/dim]\n"
        )
        self._render_todo_list(items)
        console.print()

    def _render_todo_list(self, items: list[TodoItem]) -> None:
        """渲染任务列表（带序号）。"""
        for i, item in enumerate(items, 1):
            mark = _STATUS_MARK.get(item.status, " ")
            pri = _PRIORITY_TAG.get(item.priority, "med")
            # 完成和取消的任务描述变暗
            if item.status == "done":
                desc = f"[dim][s]{item.description}[/s][/dim]"
            elif item.status == "cancelled":
                desc = f"[dim]{item.description}[/dim]"
            else:
                desc = item.description
            # 备注
            note_str = f" [dim]// {item.note}[/dim]" if item.note else ""
            console.print(
                f"  [{mark}] [{pri}] {i:>2}. {desc}{note_str}"
            )

    # ---- 添加 ----

    def _todo_add(self, arg: str) -> None:
        """添加任务。支持 -p 优先级 -n 备注。"""
        if not arg:
            console.print("[yellow]用法: /todo add <描述> [-p high|medium|low] [-n 备注][/yellow]")
            return

        description, priority, note = self._parse_add_args(arg)
        if not description:
            console.print("[red]任务描述不能为空[/red]")
            return

        try:
            item = self.todo_mgr.add(description, priority=priority, note=note)
        except ValueError as e:
            console.print(f"[red]{e}[/red]")
            return

        console.print(f"[green]v 已添加[/green] [dim]({item.id})[/dim]")
        pri_label = _PRIORITY_MARK.get(item.priority, item.priority)
        console.print(f"  [{pri_label}] {item.description}")
        if item.note:
            console.print(f"  [dim]// {item.note}[/dim]")
        console.print()

    @staticmethod
    def _parse_add_args(arg: str) -> tuple[str, str, str]:
        """解析 add 参数：描述 -p 优先级 -n 备注。"""
        priority = "medium"
        note = ""
        description_parts: list[str] = []
        i = 0
        tokens = arg.split()
        while i < len(tokens):
            tok = tokens[i]
            if tok in ("-p", "--priority") and i + 1 < len(tokens):
                p = tokens[i + 1].lower()
                if p in VALID_PRIORITIES:
                    priority = p
                i += 2
                continue
            if tok in ("-n", "--note") and i + 1 < len(tokens):
                # 备注取 -n 后的所有剩余内容
                note = " ".join(tokens[i + 1:])
                i = len(tokens)
                continue
            description_parts.append(tok)
            i += 1
        description = " ".join(description_parts).strip()
        return description, priority, note

    # ---- 状态变更 ----

    def _todo_set_status(self, arg: str, status: str) -> None:
        """标记任务状态。"""
        if not arg:
            labels = {"done": "完成", "cancelled": "取消", "pending": "重开"}
            console.print(f"[yellow]用法: /todo {status} <序号|id>[/yellow]")
            console.print(f"[dim]序号参考 /todo 列表中的编号[/dim]")
            return

        try:
            item = self.todo_mgr.update_status(arg, status)
        except ValueError as e:
            console.print(f"[red]{e}[/red]")
            return

        if item is None:
            console.print(f"[red]未找到任务: {arg}[/red]")
            console.print("[dim]用 /todo 查看今日列表的序号[/dim]")
            return

        labels = {"done": "已完成", "cancelled": "已取消", "pending": "已重开"}
        console.print(f"[green]v {labels.get(status, status)}[/green] [dim]({item.id})[/dim]")
        console.print(f"  {item.description}")
        console.print()

    # ---- 删除 ----

    def _todo_delete(self, arg: str) -> None:
        """彻底删除任务，支持批量: /todo del 1 2 3 或 /todo del todo_xxx todo_yyy。"""
        if not arg:
            console.print("[yellow]用法: /todo del <序号|id> [<序号|id> ...][/yellow]")
            console.print("[dim]支持一次删除多条，用空格分隔[/dim]")
            return

        refs = arg.split()
        # 批量删除时，先收集所有序号对应的 id（避免删除后序号位移）
        if len(refs) > 1:
            items = self.todo_mgr.list_day()
            resolved_ids: list[tuple[str, str, bool]] = []  # (原始输入, id 或空, 是否找到)
            for ref in refs:
                if ref.isdigit():
                    idx = int(ref) - 1
                    if 0 <= idx < len(items):
                        resolved_ids.append((ref, items[idx].id, True))
                    else:
                        resolved_ids.append((ref, "", False))
                else:
                    # id 前缀，直接用
                    resolved_ids.append((ref, ref, True))
            ok_count = 0
            fail_count = 0
            for orig, task_id, found in resolved_ids:
                if not found:
                    console.print(f"[red]未找到任务: {orig}[/red]")
                    fail_count += 1
                    continue
                if self.todo_mgr.delete(task_id):
                    console.print(f"[green]v 已删除[/green] [dim]({orig})[/dim]")
                    ok_count += 1
                else:
                    console.print(f"[red]未找到任务: {orig}[/red]")
                    fail_count += 1
            if ok_count:
                console.print(f"[dim]共删除 {ok_count} 条" +
                              (f"，{fail_count} 条未找到" if fail_count else "") + "[/dim]\n")
            else:
                console.print()
            return

        # 单条删除
        ref = refs[0]
        if self.todo_mgr.delete(ref):
            console.print(f"[green]v 已删除[/green] [dim]({ref})[/dim]\n")
        else:
            console.print(f"[red]未找到任务: {ref}[/red]\n")

    # ---- 编辑 ----

    def _todo_edit(self, arg: str) -> None:
        """编辑任务描述。"""
        if not arg:
            console.print("[yellow]用法: /todo edit <序号|id> <新描述>[/yellow]")
            return
        parts = arg.split(maxsplit=1)
        if len(parts) < 2:
            console.print("[yellow]需要提供新描述[/yellow]")
            console.print("[dim]用法: /todo edit <序号|id> <新描述>[/dim]")
            return
        ref, new_desc = parts[0], parts[1].strip()
        if not new_desc:
            console.print("[red]新描述不能为空[/red]")
            return

        item = self.todo_mgr.edit(ref, new_desc)
        if item is None:
            console.print(f"[red]未找到任务: {ref}[/red]")
            return
        console.print(f"[green]v 已更新[/green] [dim]({item.id})[/dim]")
        console.print(f"  {item.description}\n")

    # ---- 优先级 ----

    def _todo_set_priority(self, arg: str) -> None:
        """修改优先级。"""
        if not arg:
            console.print("[yellow]用法: /todo pri <序号|id> <high|medium|low>[/yellow]")
            return
        parts = arg.split(maxsplit=1)
        if len(parts) < 2:
            console.print("[yellow]需要提供优先级[/yellow]")
            console.print("[dim]用法: /todo pri <序号|id> <high|medium|low>[/dim]")
            return
        ref, pri = parts[0], parts[1].strip().lower()
        if pri not in VALID_PRIORITIES:
            console.print(f"[red]无效优先级: {pri}[/red]  允许: high / medium / low")
            return

        try:
            item = self.todo_mgr.set_priority(ref, pri)
        except ValueError as e:
            console.print(f"[red]{e}[/red]")
            return

        if item is None:
            console.print(f"[red]未找到任务: {ref}[/red]")
            return
        console.print(f"[green]v 优先级已更新[/green] [dim]({item.id})[/dim]")
        pri_label = _PRIORITY_MARK.get(item.priority, item.priority)
        console.print(f"  [{pri_label}] {item.description}\n")

    # ---- 历史 ----

    def _todo_history(self, arg: str) -> None:
        """查看历史记录。"""
        if not arg:
            # 默认最近 7 天
            self._render_history(7)
            return

        # 数字 → 最近 N 天
        if arg.isdigit():
            n = int(arg)
            if n <= 0 or n > 90:
                console.print("[yellow]天数范围: 1-90[/yellow]")
                return
            self._render_history(n)
            return

        # 日期字符串 → 指定日期
        date_str = arg.strip()
        items = self.todo_mgr.get_day(date_str)
        stats = self.todo_mgr.stats_day(date_str)
        if not items:
            console.print(f"\n[bold]{date_str}[/bold] [dim]无任务记录[/dim]\n")
            return
        console.print(
            f"\n[bold]{date_str}[/bold] "
            f"[dim]({stats['done']}/{stats['total']} 完成)[/dim]\n"
        )
        self._render_todo_list(items)
        console.print()

    def _render_history(self, days: int) -> None:
        """渲染最近 N 天历史。"""
        history = self.todo_mgr.list_history(days=days)
        if not history:
            console.print(f"\n[bold]最近 {days} 天历史[/bold] [dim]无记录[/dim]\n")
            return

        console.print(f"\n[bold]最近 {days} 天历史[/bold]\n")

        # 汇总表
        table = Table(show_lines=False, border_style="dim", title=None)
        table.add_column("日期", style="cyan", width=12)
        table.add_column("总数", justify="right", width=6)
        table.add_column("完成", justify="right", width=6, style="green")
        table.add_column("未完", justify="right", width=6, style="yellow")
        table.add_column("取消", justify="right", width=6, style="dim")
        table.add_column("完成率", justify="right", width=8)

        for date_str, items in history:
            stats = self.todo_mgr.stats_day(date_str)
            rate = f"{stats['completion_rate'] * 100:.0f}%"
            table.add_row(
                date_str,
                str(stats["total"]),
                str(stats["done"]),
                str(stats["pending"]),
                str(stats["cancelled"]),
                rate,
            )
        console.print(table)
        console.print(f"\n[dim]查看指定日期: /todo history 2026-07-10[/dim]\n")

    # ---- 清空 ----

    def _todo_clear(self) -> None:
        """清空今日任务。"""
        items = self.todo_mgr.list_day()
        if not items:
            console.print("[dim]今日无任务[/dim]")
            return
        confirm = Prompt.ask(
            f"确定清空今日所有任务（共 {len(items)} 条）？",
            choices=["y", "n"], default="n",
        )
        if confirm != "y":
            console.print("[dim]已取消[/dim]")
            return
        count = self.todo_mgr.clear_day()
        console.print(f"[green]v 已清空 {count} 条任务[/green]\n")

    # ---- 跨天处理 ----

    def _todo_carry_prompt(self) -> None:
        """手动触发跨天提示。"""
        self._check_carry_over(force=True)

    def _check_carry_over(self, force: bool = False) -> None:
        """检查并提示昨日未完成任务。

        Args:
            force: True 表示强制提示（忽略 carry_notice 标记）
        """
        if not force and not self.todo_mgr.should_ask_carry():
            return

        pending = self.todo_mgr.get_yesterday_pending()
        if not pending:
            # 没有未完成任务也要标记已询问，避免重复检查
            if not force:
                self.todo_mgr.mark_carry_asked()
            return

        yesterday = pending[0].date
        console.print(
            f"\n[bold yellow]昨日 ({yesterday}) 有 {len(pending)} 个未完成任务[/bold yellow]\n"
        )
        # 显示昨日未完成任务
        for i, item in enumerate(pending, 1):
            pri = _PRIORITY_TAG.get(item.priority, "med")
            console.print(f"  [ ] [{pri}] {i}. {item.description}")
        console.print()

        # 询问处理方式
        console.print("[bold]如何处理？[/bold]")
        console.print("  [cyan]1[/cyan] 全部顺延到今日")
        console.print("  [cyan]2[/cyan] 全部归档（保留为已取消）")
        console.print("  [cyan]3[/cyan] 逐个询问")
        console.print("  [cyan]4[/cyan] 暂不处理（下次再问）")

        choice = Prompt.ask("\n选择", choices=["1", "2", "3", "4"], default="1")

        if choice == "1":
            moved = self.todo_mgr.carry_over(pending)
            console.print(f"[green]v 已顺延 {moved} 个任务到今日[/green]\n")
        elif choice == "2":
            count = self.todo_mgr.archive_pending(yesterday)
            console.print(f"[green]v 已归档 {count} 个任务[/green]\n")
        elif choice == "3":
            self._carry_over_one_by_one(pending, yesterday)
        # choice == "4" 暂不处理

        # 标记今天已询问
        if not force:
            self.todo_mgr.mark_carry_asked()

    def _carry_over_one_by_one(self, items: list[TodoItem], yesterday: str) -> None:
        """逐个询问任务处理方式。"""
        carry_items: list[TodoItem] = []
        for item in items:
            pri = _PRIORITY_TAG.get(item.priority, "med")
            console.print(f"\n  [ ] [{pri}] {item.description}")
            console.print(f"  [dim]  {item.id}[/dim]")
            choice = Prompt.ask(
                "处理方式",
                choices=["1", "2", "3", "4", "5"],
                default="1",
            )
            if choice == "1":
                carry_items.append(item)
            elif choice == "2":
                self.todo_mgr.update_status(item.id, "done", date_str=yesterday)
                console.print("[green]v 已标记完成[/green]")
            elif choice == "3":
                self.todo_mgr.update_status(item.id, "cancelled", date_str=yesterday)
                console.print("[green]v 已取消[/green]")
            elif choice == "4":
                self.todo_mgr.delete(item.id, date_str=yesterday)
                console.print("[green]v 已删除[/green]")
            # choice == "5" 跳过（保留未处理）

        if carry_items:
            moved = self.todo_mgr.carry_over(carry_items)
            console.print(f"\n[green]v 已顺延 {moved} 个任务到今日[/green]")
        console.print()

    # ---- 帮助 ----

    def _todo_help(self) -> None:
        """显示 /todo 帮助。"""
        console.print("[bold]每日任务[/bold] [dim](/todo 子命令)[/dim]\n")
        console.print("  [cyan]/todo[/cyan]                    显示今日任务")
        console.print("  [cyan]/todo add[/cyan] <描述> [-p 优先级] [-n 备注]  添加任务")
        console.print("  [cyan]/todo done[/cyan] <序号|id>      标记完成")
        console.print("  [cyan]/todo cancel[/cyan] <序号|id>    取消任务")
        console.print("  [cyan]/todo reopen[/cyan] <序号|id>    重开任务")
        console.print("  [cyan]/todo edit[/cyan] <序号|id> <新>  编辑描述")
        console.print("  [cyan]/todo pri[/cyan] <序号|id> <h|m|l>  修改优先级")
        console.print("  [cyan]/todo del[/cyan] <序号|id> [...]  彻底删除（支持批量）")
        console.print("  [cyan]/todo history[/cyan] [N|日期]    历史记录")
        console.print("  [cyan]/todo clear[/cyan]               清空今日")
        console.print("  [cyan]/todo carry[/cyan]               手动触发跨天处理")
        console.print()
        console.print("[dim]优先级: high(高) / medium(中, 默认) / low(低)[/dim]")
        console.print("[dim]引用方式: 序号(今日列表编号) 或 id 前缀[/dim]\n")

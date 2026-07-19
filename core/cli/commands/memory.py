"""记忆管理与主题 Mixin。

从 repl.py 第 3003-3483 行迁移，包含：
- ``_cmd_theme`` 切换主题（claude/mimo/minimal）
- ``_cmd_memory`` 记忆管理子命令入口
- ``_memory_set_format`` 设置格式偏好
- ``_memory_set_style`` 设置风格偏好
- ``_memory_manage_topic`` 主题管理
- ``_memory_manage_region`` 地区管理
- ``_memory_manage_task`` 任务状态管理
- ``_memory_manage_workflow`` 工作流管理
- ``_memory_show`` 显示记忆概览
- ``_memory_clear`` 清空所有记忆
- ``_memory_add_task`` 添加任务
- ``_memory_show_tasks`` 列出未完成任务
- ``_cmd_clear`` 清空对话历史

注意：``_cmd_theme`` 会重赋值 ``constants._INPUT_STYLE``，
跨模块访问须通过 ``constants._INPUT_STYLE`` 属性读取/写入。
"""
from __future__ import annotations

from rich.prompt import Prompt
from rich.table import Table
from prompt_toolkit.styles import Style as PtStyle

from core.memory.profile import ProfileManager
from core.memory.tasks import TaskManager
from core.ui.theme import get_theme, set_theme, list_themes
from core.cli import constants
from core.cli.constants import console
from core.cli.welcome import _render_welcome_panel


class MemoryMixin:
    """记忆管理与主题切换相关命令。"""

    def _cmd_theme(self, arg: str) -> None:
        """切换主题：/theme [claude|mimo|minimal]"""
        themes = list_themes()
        if not arg:
            # 无参数：列出所有主题
            cur = get_theme()
            console.print(f"\n[bold]可用主题[/bold] [dim]（当前: {cur.label}）[/dim]\n")
            for name, t in themes.items():
                marker = "[green]✓[/green]" if name == cur.name else " "
                console.print(
                    f"  {marker} [cyan]{name:10s}[/cyan] "
                    f"[bold]{t.label}[/bold]  [dim]{t.desc}[/dim]"
                )
            console.print("\n[dim]用法: /theme claude  或  /theme mimo  或  /theme minimal[/dim]\n")
            return

        name = arg.strip().lower()
        try:
            new_t = set_theme(name)
        except ValueError as e:
            console.print(f"[red]{e}[/red]")
            return
        # 更新输入框样式（写入 constants 模块级变量，跨模块可见）
        # 主题色映射到 ANSI 颜色名
        _color_to_ansi = {
            "yellow": "ansiyellow", "cyan": "ansicyan", "white": "ansiwhite",
            "blue": "ansiblue", "dim": "ansibrightblack", "magenta": "ansimagenta",
        }
        primary = _color_to_ansi.get(new_t.colors.get("primary",""), "ansiyellow")
        secondary = _color_to_ansi.get(new_t.colors.get("secondary",""), "ansicyan")
        constants._INPUT_STYLE = PtStyle.from_dict({
            "prompt": new_t.colors["prompt"],
            "completion-menu.completion": "bg:ansiblack fg:ansiwhite",
            "completion-menu.completion.current": f"bg:{primary} fg:ansiblack bold",
            "completion-menu.meta.completion": f"bg:{secondary} fg:ansiwhite",
            "completion-menu.meta.completion.current": f"bg:{primary} fg:ansiblack bold",
            "completion-menu.progress-button": f"bg:{secondary}",
            "completion-menu.progress-bar": f"bg:{secondary}",
        })
        console.print(f"[green]✓ 已切换主题[/green] [bold]{new_t.label}[/bold]")
        console.print(f"[dim]{new_t.desc}[/dim]\n")
        # 重新渲染欢迎面板（传入当前会话名，避免丢失"上次会话"标签）
        stats = self.storage.stats()
        _render_welcome_panel(
            stats, self.llm_available, pet=self.pet,
            session_name=getattr(self, "active_session_name", None),
        )

    # ---- 记忆管理 ----

    def _cmd_memory(self, arg: str) -> None:
        """记忆管理子命令：/memory [show|clear|add|tasks|format|style|topic|region|task|workflow]。

        - /memory                    显示记忆概览
        - /memory show               同上，显示完整 profile
        - /memory clear              清空所有记忆（profile + tasks + workflow）
        - /memory add <描述>          添加一条任务到记忆
        - /memory tasks              列出所有未完成任务
        - /memory format <值>        设置格式偏好（table/list/prose/auto 或留空清除）
        - /memory style <值>         设置风格偏好（auto/scholar/warrior/artisan）
        - /memory topic add <主题>    手动添加关注主题
        - /memory topic remove <主题> 删除指定主题
        - /memory topic clear        清空所有主题
        - /memory region add <地区>    手动添加关注地区
        - /memory region remove <地区> 删除指定地区
        - /memory region clear        清空所有地区
        - /memory task done <id>      标记任务为已完成
        - /memory task cancel <id>    取消任务
        - /memory task reopen <id>    重开任务（pending）
        - /memory task start <id>     标记任务为进行中
        - /memory task delete <id>    彻底删除任务
        - /memory workflow clear      清空工作流模式记录
        - /memory workflow suggest on|off  启用/关闭下一步推荐
        """
        if self.memory_store is None:
            console.print("[yellow]记忆模块未初始化（需要先领养宠物）[/yellow]")
            return

        parts = arg.split(maxsplit=1) if arg else []
        sub = parts[0].lower() if parts else ""
        sub_arg = parts[1].strip() if len(parts) > 1 else ""

        # 子命令缩写（支持 /m c = /memory clear, /m f table = /memory format table）
        SUB_ALIASES = {
            "c": "clear", "cl": "clear",
            "f": "format", "fmt": "format",
            "s": "style", "sty": "style",
            "t": "tasks", "ts": "tasks",
            "top": "topic", "tp": "topic",
            "reg": "region", "r": "region",
            "ta": "task", "tk": "task",
            "w": "workflow", "wf": "workflow",
            "a": "add", "sh": "show",
        }
        sub = SUB_ALIASES.get(sub, sub)

        if sub in ("", "show"):
            self._memory_show()
        elif sub == "clear":
            self._memory_clear()
        elif sub == "add":
            if not sub_arg:
                console.print("[yellow]用法: /memory add <任务描述>[/yellow]")
                return
            self._memory_add_task(sub_arg)
        elif sub == "tasks":
            self._memory_show_tasks()
        elif sub == "format":
            self._memory_set_format(sub_arg)
        elif sub == "style":
            self._memory_set_style(sub_arg)
        elif sub == "topic":
            self._memory_manage_topic(sub_arg)
        elif sub == "region":
            self._memory_manage_region(sub_arg)
        elif sub == "task":
            self._memory_manage_task(sub_arg)
        elif sub == "workflow":
            self._memory_manage_workflow(sub_arg)
        else:
            console.print("[bold]记忆管理[/bold] [dim](/memory 子命令)[/dim]\n")
            console.print("  [cyan]/memory[/cyan]                    显示记忆概览")
            console.print("  [cyan]/memory show[/cyan]               显示完整 profile")
            console.print("  [cyan]/memory clear[/cyan]              清空所有记忆")
            console.print("  [cyan]/memory add <描述>[/cyan]         添加一条任务")
            console.print("  [cyan]/memory tasks[/cyan]              列出未完成任务")
            console.print("  [cyan]/memory format <值>[/cyan]        设置格式 (table/list/prose/auto)")
            console.print("  [cyan]/memory style <值>[/cyan]         设置风格 (auto/scholar/warrior/artisan)")
            console.print("  [cyan]/memory topic add <主题>[/cyan]    添加关注主题")
            console.print("  [cyan]/memory topic remove <主题>[/cyan] 删除主题")
            console.print("  [cyan]/memory topic clear[/cyan]        清空所有主题")
            console.print("  [cyan]/memory region add <地区>[/cyan]    添加关注地区")
            console.print("  [cyan]/memory region remove <地区>[/cyan] 删除地区")
            console.print("  [cyan]/memory region clear[/cyan]        清空所有地区")
            console.print("  [cyan]/memory task done <id>[/cyan]      标记任务完成")
            console.print("  [cyan]/memory task cancel <id>[/cyan]    取消任务")
            console.print("  [cyan]/memory task reopen <id>[/cyan]    重开任务")
            console.print("  [cyan]/memory task delete <id>[/cyan]    彻底删除任务")
            console.print("  [cyan]/memory workflow clear[/cyan]      清空工作流模式")
            console.print("  [cyan]/memory workflow suggest on|off[/cyan]  开关推荐")
            console.print("  [cyan]/memory workflow analyze[/cyan]    分析低效操作链")

    def _memory_set_format(self, value: str) -> None:
        """设置格式偏好。"""
        from core.memory.profile import VALID_FORMATS
        mgr = ProfileManager(self.memory_store)
        value = value.strip().lower()
        # 允许 "none"/"clear"/"默认" 表示清除
        if value in ("none", "clear", "默认", "auto"):
            value = "auto" if value == "auto" else ""
        if value not in VALID_FORMATS:
            console.print(
                f"[red]无效的格式: '{value}'[/red]  "
                f"允许: [cyan]table / list / prose / auto[/cyan] 或留空清除"
            )
            return
        try:
            mgr.update_format_preference(value)
            label = value if value else "（已清除）"
            console.print(f"[green]✓ 格式偏好已设置: [cyan]{label}[/cyan][/green]")
        except ValueError as e:
            console.print(f"[red]{e}[/red]")

    def _memory_set_style(self, value: str) -> None:
        """设置风格偏好。"""
        from core.memory.profile import VALID_STYLES
        mgr = ProfileManager(self.memory_store)
        value = value.strip().lower()
        if value not in VALID_STYLES:
            console.print(
                f"[red]无效的风格: '{value}'[/red]  "
                f"允许: [cyan]auto / scholar / warrior / artisan[/cyan]"
            )
            return
        try:
            mgr.update_style_preference(value)
            labels = {"auto": "自动", "scholar": "学者", "warrior": "战士", "artisan": "工匠"}
            console.print(f"[green]✓ 风格偏好已设置: [cyan]{labels[value]}[/cyan][/green]")
        except ValueError as e:
            console.print(f"[red]{e}[/red]")

    def _memory_manage_topic(self, arg: str) -> None:
        """主题管理：/memory topic [add|remove|clear] [主题]"""
        parts = arg.split(maxsplit=1) if arg else []
        action = parts[0].lower() if parts else ""
        topic = parts[1].strip() if len(parts) > 1 else ""

        if action == "":
            console.print("[yellow]用法: /memory topic <add|remove|clear> [主题][/yellow]")
            console.print("  [cyan]/memory topic add <主题>[/cyan]    添加关注主题")
            console.print("  [cyan]/memory topic remove <主题>[/cyan] 删除指定主题")
            console.print("  [cyan]/memory topic clear[/cyan]        清空所有主题")
            return

        mgr = ProfileManager(self.memory_store)

        if action == "add":
            if not topic:
                console.print("[yellow]用法: /memory topic add <主题>[/yellow]")
                return
            try:
                added = mgr.add_topic(topic)
                if added:
                    console.print(f"[green]✓ 已添加主题: [magenta]{topic}[/magenta][/green]")
                else:
                    console.print(f"[yellow]主题已存在（或被包含）: {topic}[/yellow]")
            except ValueError as e:
                console.print(f"[red]{e}[/red]")

        elif action == "remove":
            if not topic:
                console.print("[yellow]用法: /memory topic remove <主题>[/yellow]")
                return
            removed = mgr.remove_topic(topic)
            if removed:
                console.print(f"[green]✓ 已删除主题: [magenta]{topic}[/magenta][/green]")
            else:
                console.print(f"[yellow]未找到主题: {topic}[/yellow]")

        elif action == "clear":
            count = mgr.clear_topics()
            console.print(f"[green]✓ 已清空 {count} 个主题[/green]")

        else:
            console.print(f"[red]未知操作: '{action}'[/red]  允许: add / remove / clear")

    def _memory_manage_region(self, arg: str) -> None:
        """地区管理：/memory region [add|remove|clear] [地区]"""
        parts = arg.split(maxsplit=1) if arg else []
        action = parts[0].lower() if parts else ""
        region = parts[1].strip() if len(parts) > 1 else ""

        if action == "":
            console.print("[yellow]用法: /memory region <add|remove|clear> [地区][/yellow]")
            console.print("  [cyan]/memory region add <地区>[/cyan]    添加关注地区")
            console.print("  [cyan]/memory region remove <地区>[/cyan] 删除指定地区")
            console.print("  [cyan]/memory region clear[/cyan]        清空所有地区")
            return

        mgr = ProfileManager(self.memory_store)

        if action == "add":
            if not region:
                console.print("[yellow]用法: /memory region add <地区>[/yellow]")
                return
            try:
                added = mgr.add_region(region)
                if added:
                    console.print(f"[green]✓ 已添加地区: [magenta]{region}[/magenta][/green]")
                else:
                    console.print(f"[yellow]地区已存在: {region}[/yellow]")
            except ValueError as e:
                console.print(f"[red]{e}[/red]")

        elif action == "remove":
            if not region:
                console.print("[yellow]用法: /memory region remove <地区>[/yellow]")
                return
            removed = mgr.remove_region(region)
            if removed:
                console.print(f"[green]✓ 已删除地区: [magenta]{region}[/magenta][/green]")
            else:
                console.print(f"[yellow]未找到地区: {region}[/yellow]")

        elif action == "clear":
            count = mgr.clear_regions()
            console.print(f"[green]✓ 已清空 {count} 个地区[/green]")

        else:
            console.print(f"[red]未知操作: '{action}'[/red]  允许: add / remove / clear")

    def _memory_manage_task(self, arg: str) -> None:
        """任务状态管理：/memory task [done|cancel|reopen|start|delete] <id>"""
        parts = arg.split(maxsplit=1) if arg else []
        action = parts[0].lower() if parts else ""
        task_id = parts[1].strip() if len(parts) > 1 else ""

        if action == "":
            console.print("[yellow]用法: /memory task <done|cancel|reopen|start|delete> <id>[/yellow]")
            console.print("  [cyan]/memory task done <id>[/cyan]      标记为已完成")
            console.print("  [cyan]/memory task cancel <id>[/cyan]    取消任务")
            console.print("  [cyan]/memory task reopen <id>[/cyan]    重开任务（pending）")
            console.print("  [cyan]/memory task start <id>[/cyan]     标记为进行中")
            console.print("  [cyan]/memory task delete <id>[/cyan]    彻底删除任务")
            return

        if not task_id:
            console.print(f"[yellow]用法: /memory task {action} <id>[/yellow]")
            return

        mgr = TaskManager(self.memory_store)

        # 允许 task_id 简写（前缀匹配）
        all_tasks = mgr.get_all_tasks()
        matched = [t for t in all_tasks if t.id.startswith(task_id) or task_id in t.id]
        if not matched:
            console.print(f"[red]未找到任务: {task_id}[/red]")
            console.print("[dim]用 /memory tasks 查看任务列表[/dim]")
            return
        if len(matched) > 1:
            console.print(f"[yellow]ID 前缀匹配多个任务，请提供更完整的 ID[/yellow]")
            for t in matched[:5]:
                console.print(f"  [dim]{t.id}[/dim]  {t.description}")
            return
        full_id = matched[0].id

        status_map = {
            "done": "completed",
            "cancel": "cancelled",
            "reopen": "pending",
            "start": "in_progress",
        }

        if action in status_map:
            new_status = status_map[action]
            ok = mgr.update_task(full_id, new_status)
            if ok:
                labels = {
                    "completed": "已完成",
                    "cancelled": "已取消",
                    "pending": "已重开",
                    "in_progress": "进行中",
                }
                console.print(f"[green]✓ 任务状态: [cyan]{labels[new_status]}[/cyan][/green]")
                console.print(f"  [dim]{full_id}[/dim]")
            else:
                console.print(f"[red]更新失败（状态无效或任务不存在）[/red]")
        elif action == "delete":
            ok = mgr.delete_task(full_id)
            if ok:
                console.print(f"[green]✓ 已删除任务[/green] [dim]({full_id})[/dim]")
            else:
                console.print(f"[red]删除失败：未找到任务[/red]")
        else:
            console.print(f"[red]未知操作: '{action}'[/red]")
            console.print("[dim]允许: done / cancel / reopen / start / delete[/dim]")

    def _memory_manage_workflow(self, arg: str) -> None:
        """工作流管理：/memory workflow [clear|suggest|analyze]"""
        parts = arg.split(maxsplit=1) if arg else []
        action = parts[0].lower() if parts else ""

        if action == "":
            console.print("[yellow]用法: /memory workflow <clear|suggest|analyze>[/yellow]")
            console.print("  [cyan]/memory workflow clear[/cyan]            清空所有模式记录")
            console.print("  [cyan]/memory workflow suggest on|off[/cyan]    启用/关闭下一步推荐")
            console.print("  [cyan]/memory workflow analyze[/cyan]          分析低效操作链")
            return

        from core.memory.workflow import WorkflowTracker
        tracker = WorkflowTracker(self.memory_store)

        if action == "clear":
            count = tracker.clear_patterns()
            console.print(f"[green]✓ 已清空 {count} 个工作流模式[/green]")
        elif action == "suggest":
            val = parts[1].strip().lower() if len(parts) > 1 else ""
            if val in ("on", "true", "1", "开", "启用"):
                tracker.set_suggestions_enabled(True)
                console.print("[green]✓ 已启用下一步推荐[/green]")
            elif val in ("off", "false", "0", "关", "关闭"):
                tracker.set_suggestions_enabled(False)
                console.print("[green]✓ 已关闭下一步推荐[/green]")
            elif val == "":
                # 无参数：显示当前状态
                data = self.memory_store.get_data() if self.memory_store else {}
                enabled = data.get("workflow", {}).get("suggestions_enabled", True)
                state = "[green]已启用[/green]" if enabled else "[red]已关闭[/red]"
                console.print(f"  工作流推荐: {state}")
                console.print("[dim]  用法: /memory workflow suggest on|off[/dim]")
            else:
                console.print(f"[red]无效值: '{val}'[/red]  允许: on / off")
        elif action == "analyze":
            self._workflow_analyze(tracker)
        else:
            console.print(f"[red]未知操作: '{action}'[/red]  允许: clear / suggest / analyze")

    def _workflow_analyze(self, tracker) -> None:
        """显示工作流低效操作分析报告。"""
        inefficiencies = tracker.detect_inefficiencies()

        console.print("\n[bold cyan]工作流分析报告[/bold cyan]\n")

        if not inefficiencies:
            console.print("  [green]未发现低效操作模式[/green]")
            # 仍展示 Top 模式供参考
            data = self.memory_store.get_data() if self.memory_store else {}
            patterns = data.get("workflow", {}).get("patterns", [])
            if patterns:
                top = sorted(patterns, key=lambda p: p.get("count", 0), reverse=True)[:5]
                console.print("\n  [dim]高频操作模式（供参考）:[/dim]")
                for p in top:
                    seq = p.get("sequence", [])
                    console.print(f"    [dim]{' → '.join(seq)} ×{p.get('count', 0)}[/dim]")
            console.print()
            return

        # 用表格展示低效项
        table = Table(show_lines=True, border_style="yellow", title="检测到的低效操作")
        table.add_column("类型", style="yellow", width=10)
        table.add_column("模式", style="cyan", width=36)
        table.add_column("次数", style="bold red", justify="right", width=6)
        table.add_column("改进建议", style="white")

        type_labels = {
            "repeat": "重复操作",
            "pingpong": "来回切换",
            "batchable": "可批量",
        }
        for ineff in inefficiencies:
            table.add_row(
                type_labels.get(ineff.type, ineff.type),
                ineff.pattern,
                str(ineff.count),
                ineff.suggestion,
            )
        console.print(table)

        console.print(f"\n  [dim]共检测到 {len(inefficiencies)} 项可优化操作[/dim]")
        console.print(f"  [dim]执行 /memory workflow clear 可清空模式记录重新统计[/dim]\n")

    def _memory_show(self) -> None:
        """显示记忆概览。"""
        data = self.memory_store.get_data()
        profile = data.get("profile", {})
        tasks = data.get("tasks", [])
        workflow = data.get("workflow", {})

        console.print("\n[bold cyan]🧠 记忆概览[/bold cyan]\n")

        # Profile 区块
        preferred_style = profile.get("preferred_style", "auto")
        style_label = {"scholar": "学者", "warrior": "战士", "artisan": "工匠", "auto": "自动"}.get(
            preferred_style, preferred_style)
        preferred_format = profile.get("preferred_format", "")
        format_label = {
            "table": "表格", "list": "列表", "prose": "散文", "auto": "自动", "": "（未设置）"
        }.get(preferred_format, preferred_format)
        console.print(f"  [bold]用户偏好[/bold]")
        console.print(f"    风格: [cyan]{style_label}[/cyan]")
        console.print(f"    格式: [cyan]{format_label}[/cyan]  [dim](/memory format 设置)[/dim]")
        topics = profile.get("focus_topics", [])
        if topics:
            console.print(f"    关注主题: [magenta]{'、'.join(topics[:5])}[/magenta]"
                          + (f" [dim]等 {len(topics)} 个[/dim]" if len(topics) > 5 else ""))
        regions = profile.get("focus_regions", [])
        if regions:
            console.print(f"    关注地区: [magenta]{'、'.join(regions[:5])}[/magenta]"
                          + (f" [dim]等 {len(regions)} 个[/dim]" if len(regions) > 5 else ""))
        console.print(f"    互动次数: [cyan]{profile.get('interaction_count', 0)}[/cyan]")
        console.print(f"    最后活跃: [dim]{profile.get('last_active', '（无）')}[/dim]")

        # Tasks 区块
        active = [t for t in tasks if t.get("status") != "completed"]
        console.print(f"\n  [bold]任务[/bold] [dim]（{len(active)} 个未完成 / 共 {len(tasks)} 个）[/dim]")
        if active:
            for t in active[:5]:
                console.print(f"    - [cyan]{t['id'][:12]}[/cyan] {t['description']} "
                              f"[dim]({t.get('status', 'pending')})[/dim]")

        # Workflow 区块
        patterns = workflow.get("patterns", [])
        console.print(f"\n  [bold]工作流[/bold]")
        console.print(f"    模式数: [cyan]{len(patterns)}[/cyan]")
        console.print(f"    推荐启用: [cyan]{workflow.get('suggestions_enabled', True)}[/cyan]")
        if patterns:
            top = sorted(patterns, key=lambda p: p.get("count", 0), reverse=True)[:3]
            for p in top:
                seq = p.get("sequence", [])
                console.print(f"    [dim]{' → '.join(seq)} ×{p.get('count', 0)}[/dim]")
        console.print()

    def _memory_clear(self) -> None:
        """清空所有记忆。"""
        confirm = Prompt.ask(
            "确定清空所有记忆（profile + tasks + workflow）？",
            choices=["y", "n"], default="n",
        )
        if confirm != "y":
            console.print("[dim]已取消[/dim]")
            return
        self.memory_store.clear()
        console.print("[green]✓ 已清空所有记忆[/green]")

    def _memory_add_task(self, description: str) -> None:
        """添加一条任务到记忆。"""
        try:
            mgr = TaskManager(self.memory_store)
            task_id = mgr.add_task(description)
            console.print(f"[green]✓ 已添加任务[/green] [dim]({task_id})[/dim]")
            console.print(f"  [cyan]{description}[/cyan]")
        except Exception as e:
            err_msg = str(e).replace("[", "\\[")
            console.print(f"[red]添加任务失败: {err_msg}[/red]")

    def _memory_show_tasks(self) -> None:
        """列出所有未完成任务。"""
        try:
            mgr = TaskManager(self.memory_store)
            tasks = mgr.get_active_tasks()
        except Exception as e:
            err_msg = str(e).replace("[", "\\[")
            console.print(f"[red]读取任务失败: {err_msg}[/red]")
            return
        if not tasks:
            console.print("[yellow]暂无未完成任务[/yellow]  [dim]用 /memory add <描述> 添加[/dim]")
            return
        console.print(f"\n[bold]未完成任务[/bold] [dim]（共 {len(tasks)} 个）[/dim]\n")
        table = Table(show_lines=False, border_style="cyan")
        table.add_column("ID", style="cyan", width=14)
        table.add_column("描述", style="white")
        table.add_column("状态", style="yellow")
        table.add_column("创建时间", style="dim")
        for t in tasks:
            table.add_row(t.id[:12], t.description, t.status, t.created_at[:19])
        console.print(table)
        console.print()

    def _cmd_clear(self, arg: str = "") -> None:
        """清空对话历史。"""
        n = len(self.history)
        self.history.clear()
        # 同时清除早期对话摘要
        self.conversation_summary = None
        # 同时清掉数据分析追问 + 阅读模式状态
        cleared = []
        if self.current_analysis is not None:
            self.current_analysis = None
            cleared.append("数据分析")
        if self.reader is not None:
            self.reader.close()
            self.reader = None
            cleared.append("阅读模式")
        if cleared:
            console.print(
                f"[green]✓ 已清空对话历史[/green] [dim]({n} 条记录 + {'/'.join(cleared)})[/dim]"
            )
        else:
            console.print(f"[green]✓ 已清空对话历史[/green] [dim]({n} 条记录)[/dim]")

    # ---- 跨会话记忆 ----

    def _cmd_cross(self, arg: str) -> None:
        """跨会话记忆管理：/cross [list|add|remove|clear]。

        - /cross                         显示跨会话记忆
        - /cross list                    同上
        - /cross add preference 键:值    添加用户偏好
        - /cross add topic 主题           添加关注主题
        - /cross add question 问题        记录未解决问题
        - /cross add fact 事实            记录关键事实
        - /cross remove topic 主题        移除主题
        - /cross clear                   清空所有跨会话记忆
        """
        from core.memory.cross_session import CrossSessionMemory

        # 复用 REPL 实例的 cross_session_memory（会话级路径），
        # 没有则降级到全局默认路径
        cm = getattr(self, 'cross_session_memory', None)
        if cm is None:
            cm = CrossSessionMemory()
        parts = arg.split(maxsplit=2) if arg else []
        sub = parts[0].lower() if parts else ""

        # 缩写别名
        SUB_ALIASES = {"l": "list", "ls": "list", "a": "add", "r": "remove", "rm": "remove", "c": "clear", "cl": "clear"}
        sub = SUB_ALIASES.get(sub, sub)

        if sub in ("", "list"):
            context = cm.get_context()
            if context:
                console.print(f"\n[bold]跨会话记忆[/bold]\n")
                console.print(context)
                console.print()
            else:
                console.print("[yellow]暂无跨会话记忆[/yellow]")
                console.print("[dim]用法: /cross add topic 殡葬政策[/dim]")
                console.print("[dim]     /cross add preference 格式:表格[/dim]")
                console.print("[dim]     /cross add question 什么是知识库？[/dim]")
                console.print("[dim]     /cross add fact 用户关注殡葬领域[/dim]\n")
            return

        if sub == "add":
            if len(parts) < 3:
                console.print("[yellow]用法: /cross add <类别> <内容>[/yellow]")
                console.print("[dim]类别: preference / topic / question / fact[/dim]")
                return
            category = parts[1].lower()
            content = parts[2].strip()
            if not content:
                console.print("[yellow]内容不能为空[/yellow]")
                return

            if category == "preference":
                if ":" in content:
                    key, value = content.split(":", 1)
                    cm.save_preference(key.strip(), value.strip())
                    console.print(f"[green]✓ 偏好已保存: {key.strip()} = {value.strip()}[/green]")
                else:
                    console.print("[yellow]格式: /cross add preference 键:值[/yellow]")
            elif category == "topic":
                cm.add_topic(content)
                console.print(f"[green]✓ 主题已添加: {content}[/green]")
            elif category == "question":
                cm.add_unresolved_question(content)
                console.print(f"[green]✓ 问题已记录: {content}[/green]")
            elif category == "fact":
                cm.add_key_fact(content)
                # 同步到 SQLite key_facts 表（JSON 仍保留全量记忆）
                if getattr(self, 'storage', None) is not None:
                    try:
                        session_name = getattr(self, 'active_session_name', '') or ''
                        self.storage.add_key_fact(
                            fact=content,
                            session=session_name,
                            source="/cross add",
                        )
                    except Exception:
                        pass
                console.print(f"[green]✓ 事实已记录: {content}[/green]")
            else:
                console.print(f"[red]未知类别: {category}[/red]  允许: preference / topic / question / fact")

        elif sub == "remove":
            if len(parts) < 3:
                console.print("[yellow]用法: /cross remove <类别> <内容>[/yellow]")
                return
            category = parts[1].lower()
            content = parts[2].strip()
            if category == "topic":
                cm.remove_topic(content)
                console.print(f"[green]✓ 主题已移除: {content}[/green]")
            else:
                console.print(f"[yellow]仅支持移除 topic: /cross remove topic {content}[/yellow]")

        elif sub == "clear":
            cm.clear_all()
            # 同步清空 SQLite 中当前会话的关键事实
            if getattr(self, 'storage', None) is not None:
                try:
                    session_name = getattr(self, 'active_session_name', '') or ''
                    count = self.storage.clear_key_facts(session=session_name)
                    if count:
                        console.print(f"[dim]  已同步清理 {count} 条关键事实记录[/dim]")
                except Exception:
                    pass
            console.print("[green]✓ 跨会话记忆已清空[/green]")

        else:
            console.print("[yellow]用法: /cross [list|add|remove|clear][/yellow]")
            console.print("[dim]  /cross list                       显示记忆[/dim]")
            console.print("[dim]  /cross add topic 主题               添加主题[/dim]")
            console.print("[dim]  /cross add preference 键:值         添加偏好[/dim]")
            console.print("[dim]  /cross add question 问题            记录问题[/dim]")
            console.print("[dim]  /cross add fact 事实                记录事实[/dim]")
            console.print("[dim]  /cross remove topic 主题            移除主题[/dim]")
            console.print("[dim]  /cross clear                      清空所有[/dim]")

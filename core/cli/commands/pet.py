"""虚拟宠物 Mixin。

从 repl.py 第 4118-4469 行迁移，包含：
- ``_cmd_pet`` 宠物子命令入口
- ``_pet_show_status`` 显示宠物状态面板
- ``_pet_adopt`` 领养宠物
- ``_pet_interact`` 互动（喂食/玩耍/训练/洗澡/睡觉）
- ``_pet_rename`` 改名
- ``_pet_show_tasks`` 每日任务
- ``_pet_show_shop`` 商店
- ``_pet_buy`` 购买道具
- ``_pet_use`` 使用道具
- ``_pet_style`` 切换人格风格
- ``_pet_reset`` 重置行为统计/限时效果
- ``_pet_show_bag`` 查看道具栏
- ``_pet_gain_exp`` 宠物获取经验（埋点辅助）
- ``_resolve_doc_id`` 根据前缀匹配完整 doc_id
"""
from __future__ import annotations

from typing import Optional

from rich.console import Group
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from core.memory.profile import ProfileManager
from core.pet.interact import InteractError
from core.pet.shop import ShopError
from core.cli.constants import console
from core.cli.welcome import _render_bar


class PetMixin:
    """虚拟宠物相关命令。"""

    def _cmd_pet(self, arg: str) -> None:
        """虚拟宠物子命令。"""
        parts = arg.split(maxsplit=1)
        sub = parts[0].lower() if parts else ""
        sub_arg = parts[1].strip() if len(parts) > 1 else ""

        if sub in ("", "status"):
            self._pet_show_status()
        elif sub == "adopt":
            self._pet_adopt(sub_arg)
        elif sub == "feed":
            self._pet_interact("feed")
        elif sub == "play":
            self._pet_interact("play")
        elif sub == "train":
            self._pet_interact("train")
        elif sub == "wash":
            self._pet_interact("wash")
        elif sub == "sleep":
            self._pet_interact("sleep")
        elif sub == "name":
            self._pet_rename(sub_arg)
        elif sub == "tasks":
            self._pet_show_tasks()
        elif sub == "shop":
            self._pet_show_shop()
        elif sub == "buy":
            self._pet_buy(sub_arg)
        elif sub == "use":
            self._pet_use(sub_arg)
        elif sub == "style":
            self._pet_style(sub_arg)
        elif sub == "reset":
            self._pet_reset(sub_arg)
        elif sub in ("bag", "inventory", "inv"):
            self._pet_show_bag()
        else:
            console.print("[bold]虚拟宠物[/bold] [dim](/pet 子命令)[/dim]\n")
            console.print("  [cyan]/pet[/cyan]                查看宠物状态")
            console.print("  [cyan]/pet adopt <名字>[/cyan]    领养宠物")
            console.print("  [cyan]/pet feed[/cyan]            喂食")
            console.print("  [cyan]/pet play[/cyan]            玩耍")
            console.print("  [cyan]/pet train[/cyan]           训练")
            console.print("  [cyan]/pet wash[/cyan]            清洁")
            console.print("  [cyan]/pet sleep[/cyan]           睡觉（恢复能量）")
            console.print("  [cyan]/pet name <新名>[/cyan]     改名")
            console.print("  [cyan]/pet style <风格>[/cyan]    切换人格风格（scholar/warrior/artisan/auto）")
            console.print("  [cyan]/pet tasks[/cyan]           每日任务")
            console.print("  [cyan]/pet shop[/cyan]            道具商店")
            console.print("  [cyan]/pet buy <id>[/cyan]        购买道具")
            console.print("  [cyan]/pet use <id>[/cyan]        使用道具")
            console.print("  [cyan]/pet bag[/cyan]             查看道具栏")
            console.print("  [cyan]/pet reset <stats|effects>[/cyan]  重置行为统计/清空限时效果")

    def _pet_show_status(self) -> None:
        """显示宠物详情面板。"""
        if self.pet is None:
            console.print("[yellow]还没有宠物，输入 /pet adopt <名字> 领养[/yellow]")
            return
        p = self.pet
        branch_label = {"scholar": "学者", "warrior": "战士", "artisan": "工匠"}.get(p.branch, "未分系")
        art = self.art_lib.get(p.branch, p.level)
        color = {"scholar": "cyan", "warrior": "red", "artisan": "yellow"}.get(p.branch, "white")

        art_text = Text(art, style=color)
        info = Group(
            art_text,
            Text(""),
            Text.from_markup(f"  [bold magenta]{p.name}[/bold magenta]  Lv{p.level} {branch_label}"),
            Text(""),
            Text.from_markup(f"  饱食   {_render_bar(p.hunger)}  [dim]{p.hunger}/100[/dim]"),
            Text.from_markup(f"  心情   {_render_bar(p.mood)}  [dim]{p.mood}/100[/dim]"),
            Text.from_markup(f"  能量   {_render_bar(p.energy)}  [dim]{p.energy}/100[/dim]"),
            Text.from_markup(f"  清洁   {_render_bar(p.cleanliness)}  [dim]{p.cleanliness}/100[/dim]"),
            Text(""),
            Text.from_markup(f"  经验   {_render_bar(round(p.exp / p.exp_needed() * 100))}  [dim]{p.exp}/{p.exp_needed()}[/dim]" + (
                f"  →Lv{p.level+1} 还需 {p.exp_remaining()}" if p.level < 10 else "  [dim](最高级)[/dim]"
            )),
        )
        console.print(Panel(info, border_style="magenta", title=f"[bold magenta]{p.name}[/bold magenta]", padding=(1, 2)))

    def _pet_adopt(self, name: str) -> None:
        """领养宠物。"""
        if self.pet is not None:
            console.print(f"[yellow]已经领养过 {self.pet.name} 了[/yellow]")
            return
        if not name:
            console.print("[yellow]用法: /pet adopt <名字>[/yellow]")
            return
        self.pet = self.pet_storage.create(name)
        # 领养后同步初始化记忆模块（__init__ 时 self.pet 为 None 会跳过）
        if self.memory_store is None:
            try:
                from core.memory.store import MemoryStore
                from core.memory.workflow import WorkflowTracker
                self.memory_store = MemoryStore()
                self.workflow_tracker = WorkflowTracker(self.memory_store)
            except Exception as e:
                console.print(f"[dim]记忆系统初始化失败: {e}[/dim]")
        console.print(f"[bold green]✓ 领养成功！[/bold green] 你的宠物叫 [magenta]{name}[/magenta]")
        self._pet_show_status()

    def _pet_interact(self, action: str) -> None:
        """执行互动。"""
        if self.pet is None:
            console.print("[yellow]还没有宠物，/pet adopt 领养[/yellow]")
            return
        try:
            method = getattr(self.pet_interactor, action)
            result = method(self.pet)
            self.pet_storage.save(self.pet)
            console.print(f"[green]{result['message']}[/green]")
        except InteractError as e:
            console.print(f"[yellow]{e}[/yellow]")

    def _pet_restore_energy(self) -> None:
        """智能恢复能量（被 _handle_chat 意图识别调用）。

        路由策略：
        1. 优先用背包里的 energy_drink（无冷却，立即 +50）
        2. 否则尝试 sleep（+50，但 1h 冷却）
        3. sleep 冷却中 → 提示用户去商店购买能量饮料
        """
        if self.pet is None:
            console.print("[yellow]还没有宠物，/pet adopt 领养[/yellow]")
            return
        pet = self.pet

        # 能量已满无需恢复
        if pet.energy >= 100:
            console.print(f"[green]{pet.name} 能量已满（{pet.energy}/100），无需恢复[/green]")
            return

        # 策略 1：检查背包是否有 energy_drink
        has_drink = any(
            slot.get("item_id") == "energy_drink" and slot.get("count", 0) > 0
            for slot in pet.inventory
        )
        if has_drink:
            try:
                result = self.shop.use(pet, "energy_drink")
                self.pet_storage.save(pet)
                console.print(f"[green]{result['message']}（用了能量饮料）[/green]")
                console.print(f"[dim]当前能量 {pet.energy}/100[/dim]")
                return
            except Exception as e:
                # 道具使用失败，降级到 sleep
                console.print(f"[dim]能量饮料使用失败：{e}，尝试睡觉...[/dim]")

        # 策略 2：尝试 sleep
        try:
            result = self.pet_interactor.sleep(pet)
            self.pet_storage.save(pet)
            console.print(f"[green]{result['message']}[/green]")
            console.print(f"[dim]当前能量 {pet.energy}/100[/dim]")
        except InteractError as e:
            # 策略 3：sleep 冷却中，提示去商店
            console.print(f"[yellow]{e}[/yellow]")
            console.print(
                f"[dim]提示：可用 /pet buy energy_drink 购买能量饮料（100 经验），"
                f"无冷却立即恢复 50 能量[/dim]"
            )

    def _pet_answer_query(self) -> None:
        """以对话形式回答宠物状态查询（被 _handle_chat 意图识别调用）。

        与 _pet_show_status 不同：本方法用自然语言回答而非面板，
        让用户在直接对话中感觉"宠物在回答自己的状态"。
        """
        if self.pet is None:
            console.print("[yellow]还没有宠物，/pet adopt 领养[/yellow]")
            return
        p = self.pet
        branch_label = {"scholar": "学者", "warrior": "战士", "artisan": "工匠"}.get(
            p.branch or "", "未分系"
        )
        # 头像标识行（与 _handle_chat 流式输出一致）
        avatar = {"scholar": "✻", "warrior": "✦", "artisan": "✼"}.get(p.branch, "✺")
        color = {"scholar": "cyan", "warrior": "red", "artisan": "yellow"}.get(p.branch, "white")
        console.print(f"[{color}]{avatar}[/{color}] [bold magenta]{p.name}[/bold magenta]")
        console.print()

        # 用自然语言描述状态，让回答更有温度
        lines = [
            f"我是 {p.name}（Lv{p.level} {branch_label}），当前状态：",
            f"- 饱食 {p.hunger}/100",
            f"- 心情 {p.mood}/100",
            f"- 能量 {p.energy}/100",
            f"- 清洁 {p.cleanliness}/100",
            f"- 经验 {p.exp}/{p.exp_needed()}" + (
                f"（距离 Lv{p.level + 1} 还需 {p.exp_remaining()}）"
                if p.level < 10 else "（已达最高级）"
            ),
        ]
        # 道具栏
        if p.inventory:
            inv_desc = "、".join(
                f"{slot.get('item_id', '?')}×{slot.get('count', 0)}"
                for slot in p.inventory
            )
            lines.append(f"- 道具栏：{inv_desc}")
        else:
            lines.append("- 道具栏：空")

        console.print("\n".join(lines))
        console.print()

    def _pet_rename(self, new_name: str) -> None:
        """改名。"""
        if self.pet is None:
            console.print("[yellow]还没有宠物[/yellow]")
            return
        if not new_name:
            console.print("[yellow]用法: /pet name <新名字>[/yellow]")
            return
        old = self.pet.name
        self.pet.name = new_name
        self.pet_storage.save(self.pet)
        console.print(f"[green]✓ {old} 改名为 {new_name}[/green]")

    def _pet_show_tasks(self) -> None:
        """显示每日任务。"""
        if self.pet is None:
            console.print("[yellow]还没有宠物[/yellow]")
            return
        # 检查是否需要刷新
        if self.task_manager._should_refresh(self.pet):
            self.task_manager.refresh(self.pet)
            self.pet_storage.save(self.pet)
        tasks = self.task_manager.list_tasks(self.pet)
        if not tasks:
            console.print("[yellow]今日任务已刷新，请稍后再试[/yellow]")
            return
        t = Table(title="今日任务", border_style="magenta")
        t.add_column("任务", style="white")
        t.add_column("进度", style="cyan")
        t.add_column("奖励", style="yellow")
        t.add_column("状态", style="green")
        for task in tasks:
            status = "✓ 完成" if task["completed"] else "进行中"
            t.add_row(
                task["description"],
                f"{task['progress']}/{task['target']}",
                f"+{task['reward']}",
                status,
            )
        console.print(t)

    def _pet_show_shop(self) -> None:
        """显示商店。"""
        t = Table(title="🛒 道具商店", border_style="yellow")
        t.add_column("ID", style="cyan")
        t.add_column("名称", style="white")
        t.add_column("价格", style="yellow")
        t.add_column("效果", style="dim")
        for item in self.shop.list_items():
            effect_str = str(item["effect"])
            t.add_row(item["id"], item["name"], f"{item['price']} 经验", effect_str)
        console.print(t)
        console.print("[dim]用 /pet buy <id> 购买，/pet use <id> 使用[/dim]")

    def _pet_buy(self, item_id: str) -> None:
        """购买道具。"""
        if self.pet is None:
            console.print("[yellow]还没有宠物[/yellow]")
            return
        if not item_id:
            console.print("[yellow]用法: /pet buy <id>[/yellow]")
            return
        try:
            result = self.shop.buy(self.pet, item_id)
            self.pet_storage.save(self.pet)
            console.print(f"[green]{result['message']}[/green]")
        except ShopError as e:
            console.print(f"[red]{e}[/red]")

    def _pet_use(self, item_id: str) -> None:
        """使用道具。支持序号（/pet use 1）或道具 ID（/pet use energy_drink）。"""
        if self.pet is None:
            console.print("[yellow]还没有宠物[/yellow]")
            return
        if not item_id:
            console.print("[yellow]用法: /pet use <序号|id>[/yellow]")
            return
        inv = self.pet.inventory
        if not inv:
            console.print("[yellow]道具栏是空的[/yellow]")
            return
        # 如果输入是数字序号，转换为 item_id
        try:
            idx = int(item_id) - 1  # 1-based → 0-based
            if 0 <= idx < len(inv):
                item_id = inv[idx]["item_id"]
            else:
                console.print(f"[red]无效序号: {item_id}（共 {len(inv)} 种道具）[/red]")
                return
        except ValueError:
            pass  # 不是数字，当作 item_id 直接使用
        try:
            result = self.shop.use(self.pet, item_id)
            self.pet_storage.save(self.pet)
            console.print(f"[green]{result['message']}[/green]")
        except ShopError as e:
            console.print(f"[red]{e}[/red]")

    def _pet_style(self, style: str) -> None:
        """切换人格风格：/pet style <scholar|warrior|artisan|auto>。"""
        if self.pet is None:
            console.print("[yellow]还没有宠物，/pet adopt 领养[/yellow]")
            return
        valid = {"scholar", "warrior", "artisan", "auto"}
        if not style:
            # 显示当前风格
            if self.memory_store is not None:
                try:
                    mgr = ProfileManager(self.memory_store)
                    cur = mgr.get_profile().preferred_style
                    console.print(f"[dim]当前人格风格: [cyan]{cur}[/cyan][/dim]")
                except Exception:
                    pass
            console.print("[dim]用法: /pet style <scholar|warrior|artisan|auto>[/dim]")
            return
        s = style.strip().lower()
        if s not in valid:
            console.print(f"[red]未知风格: {s}[/red]  [dim]可选: scholar / warrior / artisan / auto[/dim]")
            return
        if self.memory_store is None:
            console.print("[yellow]记忆模块未初始化，无法保存风格偏好[/yellow]")
            return
        try:
            mgr = ProfileManager(self.memory_store)
            mgr.update_style_preference(s)
            label = {"scholar": "学者", "warrior": "战士", "artisan": "工匠", "auto": "自动"}.get(s, s)
            console.print(f"[green]✓ 人格风格已切换为[/green] [bold cyan]{label}[/bold cyan]")
            if s == "auto":
                console.print("[dim]（auto = 跟随宠物分系）[/dim]")
        except Exception as e:
            err_msg = str(e).replace("[", "\\[")
            console.print(f"[red]切换失败: {err_msg}[/red]")

    def _pet_reset(self, target: str) -> None:
        """重置宠物数据：/pet reset <stats|effects>。

        - stats:   清空行为统计（用于重新分系判定）
        - effects: 清空所有限时效果（active_effects）
        """
        if self.pet is None:
            console.print("[yellow]还没有宠物，/pet adopt 领养[/yellow]")
            return
        target = (target or "").strip().lower()
        if target not in ("stats", "effects"):
            console.print("[yellow]用法: /pet reset <stats|effects>[/yellow]")
            console.print("  [cyan]/pet reset stats[/cyan]    清空行为统计（重新分系判定）")
            console.print("  [cyan]/pet reset effects[/cyan]  清空所有限时效果")
            return
        if target == "stats":
            from core.cli.terminal_helpers import repl_confirm
            if not repl_confirm(f"确定清空 {self.pet.name} 的行为统计？这会影响分系判定。"):
                console.print("[dim]已取消[/dim]")
                return
            self.pet.reset_stats()
            self.pet_storage.save(self.pet)
            console.print(f"[green]✓ 已清空行为统计[/green] [dim]（等级/经验/属性保留）[/dim]")
        elif target == "effects":
            count = self.pet.clear_active_effects()
            self.pet_storage.save(self.pet)
            console.print(f"[green]✓ 已清空 {count} 个限时效果[/green]")

    def _pet_show_bag(self) -> None:
        """查看道具栏：/pet bag"""
        if self.pet is None:
            console.print("[yellow]还没有宠物，/pet adopt 领养[/yellow]")
            return
        inv = self.pet.inventory
        if not inv:
            console.print(f"[yellow]{self.pet.name} 的道具栏是空的[/yellow]")
            console.print("[dim]用 /pet shop 查看商店，/pet buy <id> 购买道具[/dim]")
            return
        console.print(f"\n[bold]🎒 {self.pet.name} 的道具栏[/bold] [dim]（共 {len(inv)} 种）[/dim]\n")
        table = Table(show_lines=False, border_style="magenta")
        table.add_column("#", style="dim", width=4)
        table.add_column("名称", style="white")
        table.add_column("数量", style="cyan", width=6)
        table.add_column("效果", style="yellow")

        # 从商店获取道具定义（name + effect）
        shop_items = self.shop.list_items()
        item_map = {si["id"]: si for si in shop_items}

        for i, slot in enumerate(inv):
            item_data = item_map.get(slot.get("item_id", ""), {})
            name = item_data.get("name", "?")
            count = slot.get("count", 0)
            effect = item_data.get("effect", {})
            # 效果描述
            effect_desc = ""
            if isinstance(effect, dict) and effect:
                parts = []
                for k, v in effect.items():
                    if k == "hunger":
                        parts.append(f"饱食+{v}")
                    elif k == "mood":
                        parts.append(f"心情+{v}")
                    elif k == "energy":
                        parts.append(f"能量+{v}")
                    elif k == "cleanliness":
                        parts.append(f"清洁+{v}")
                    elif k == "exp_multi":
                        dur = effect.get("duration_sec", 0) // 3600
                        parts.append(f"经验×{v}({dur}h)")
                    elif k == "auto_revive":
                        parts.append("凤凰之羽")
                    elif k == "reset_stats":
                        parts.append("重置属性")
                    else:
                        parts.append(f"{k}+{v}")
                effect_desc = "、".join(parts)
            table.add_row(str(i + 1), name, str(count), effect_desc)
        console.print(table)
        console.print("\n[dim]用 /pet use <序号> 使用道具[/dim]\n")

    def _pet_gain_exp(self, amount: int, action_type: str) -> None:
        """宠物获取经验（埋点辅助方法）。"""
        if self.pet is None:
            return
        events = self.pet.gain_exp(amount, action_type)
        # 检查每日任务进度
        completed = self.task_manager.check_progress(self.pet, action_type)
        # 发放任务奖励
        for task in completed:
            self.pet.gain_exp(task["reward"], "task_reward")
            console.print(f"[green]✓ 每日任务完成: {task['description']} (+{task['reward']} 经验)[/green]")
        # 升级提示
        if events.get("leveled_up"):
            console.print(f"[bold magenta]{self.pet.name} 升到 Lv{events['new_level']}！[/bold magenta]")
        # 分系提示
        if events.get("branched"):
            branch_label = {"scholar": "学者", "warrior": "战士", "artisan": "工匠"}.get(events["branch"], "")
            console.print(f"[bold magenta]{self.pet.name} 进化为 {branch_label}系！[/bold magenta]")
        self.pet_storage.save(self.pet)

    # ---- 辅助 ----

    def _resolve_doc_id(self, short_id: str) -> Optional[str]:
        """根据前缀匹配完整 doc_id。"""
        if len(short_id) >= 32:
            return short_id
        docs = self.storage.list_documents(limit=1000)
        matched = [d for d in docs if d.id.startswith(short_id)]
        return matched[0].id if matched else None

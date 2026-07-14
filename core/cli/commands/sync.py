"""同步与维护 Mixin。

从 repl.py 第 2241-2525 行迁移：
- ``_cmd_sync`` 增量同步目录
- ``_cmd_health`` 数据质量报告
- ``_cmd_dedup`` 扫描近似重复
- ``_cmd_draw`` 基于文档生成配图
- ``_cmd_daily`` 生成每日知识卡片
- ``_cmd_pic`` 直接文生图
"""
from __future__ import annotations

from pathlib import Path

from rich.table import Table
from rich.prompt import Prompt

from config import settings
from core.cli.constants import console
from core.cli.welcome import _record_activity


class SyncMixin:
    """同步与维护相关命令。"""

    def _cmd_sync(self, arg: str) -> None:
        """增量同步目录：/sync <目录> 或 /sync reset"""
        if not arg:
            console.print("[yellow]用法:[/yellow]")
            console.print("  [cyan]/sync <目录路径>[/cyan]  增量同步目录")
            console.print("  [cyan]/sync reset[/cyan]      清空文件追踪记录（下次全量重建）")
            return
        # 子命令: reset
        if arg.strip().lower() == "reset":
            from core.sync.tracker import FileTracker
            tracker = FileTracker(storage_path=settings.storage_path)
            confirm = Prompt.ask(
                "确定清空所有文件追踪记录？下次同步将全量重建。",
                choices=["y", "n"], default="n",
            )
            if confirm != "y":
                console.print("[dim]已取消[/dim]")
                return
            count = tracker.reset()
            console.print(f"[green]✓ 已清空 {count} 条追踪记录[/green]")
            return
        from core.sync.tracker import FileTracker
        tracker = FileTracker(storage_path=settings.storage_path)

        def on_progress(action: str, fp: str) -> None:
            if action == "added":
                console.print(f"  [green]✓ 新增[/green]: {Path(fp).name}")
            elif action == "updated":
                console.print(f"  [yellow]↻ 更新[/yellow]: {Path(fp).name}")
            elif action == "deleted":
                console.print(f"  [red]✗ 删除[/red]: {Path(fp).name}")

        with console.status("[bold yellow]扫描同步...[/bold yellow]", spinner="dots"):
            result = tracker.sync_directory(arg, self.storage, on_progress=on_progress)

        console.print(
            f"\n[bold]同步完成[/bold]  新增 {len(result.added)} / "
            f"更新 {len(result.updated)} / 删除 {len(result.deleted)} / "
            f"跳过 {len(result.skipped)}"
        )
        if result.errors:
            console.print(f"[red]错误 {len(result.errors)} 个[/red]")

    def _cmd_health(self, arg: str) -> None:
        """数据质量报告：/health [list]"""
        from core.sync.checker import QualityChecker
        checker = QualityChecker()

        with console.status("[bold yellow]检查质量...[/bold yellow]", spinner="dots"):
            docs = self.storage.list_documents(limit=1000)
            all_results = []
            for doc in docs:
                chunks = self.storage.get_chunks(doc.id)
                all_results.extend(checker.check_document(chunks))
            report = checker.generate_report(all_results)

        console.print(f"\n[bold]知识库健康报告[/bold]\n")
        console.print(f"  文档: {len(docs)}  Chunk: {report.total_chunks}")
        console.print(f"  ✓ 正常: {report.normal} ({report.normal_pct}%)")
        console.print(f"  ! 低质量: {report.low_quality}")
        if report.ocr_poor:
            console.print(f"  ! OCR 乱码: {report.ocr_poor}")
        console.print(f"  [bold]健康分: {report.health_score}/100[/bold]")

        # 子命令: list - 列出低质量 chunk
        if arg.strip().lower() in ("list", "detail", "low"):
            low_quality = [r for r in all_results if r.score < 0.6]
            if not low_quality:
                console.print("\n[green]无低质量 chunk[/green]")
                return
            console.print(f"\n[bold]低质量 Chunk（共 {len(low_quality)} 个）[/bold]\n")
            table = Table(show_lines=False, border_style="yellow")
            table.add_column("Chunk ID", style="cyan", width=14)
            table.add_column("文档", style="white")
            table.add_column("评分", style="yellow", width=6)
            table.add_column("问题", style="red")
            for r in low_quality[:20]:
                issues = "、".join(r.issues) if r.issues else ""
                table.add_row(r.chunk_id[:12], r.doc_id[:8], f"{r.score:.2f}", issues)
            console.print(table)
            if len(low_quality) > 20:
                console.print(f"[dim]... 还有 {len(low_quality) - 20} 个[/dim]")
            console.print("\n[dim]用 /dedup delete <chunk_id> 删除问题 chunk[/dim]")

    def _cmd_dedup(self, arg: str) -> None:
        """扫描近似重复：/dedup [delete <chunk_id>]"""
        # 子命令: delete
        parts = arg.split(maxsplit=1) if arg else []
        if parts and parts[0].lower() in ("delete", "del", "rm"):
            if len(parts) < 2 or not parts[1].strip():
                console.print("[yellow]用法: /dedup delete <chunk_id>[/yellow]")
                return
            chunk_id = parts[1].strip()
            # 支持简写前缀匹配
            if len(chunk_id) < 32:
                # 搜索匹配的 chunk
                docs = self.storage.list_documents(limit=1000)
                matched = []
                for doc in docs:
                    chunks = self.storage.get_chunks(doc.id)
                    for c in chunks:
                        if c.id.startswith(chunk_id):
                            matched.append(c.id)
                if not matched:
                    console.print(f"[red]未找到 chunk: {chunk_id}[/red]")
                    return
                if len(matched) > 1:
                    console.print(f"[yellow]ID 前缀匹配多个 chunk，请提供更完整的 ID[/yellow]")
                    for cid in matched[:5]:
                        console.print(f"  [dim]{cid}[/dim]")
                    return
                chunk_id = matched[0]
            confirm = Prompt.ask(
                f"确定删除 chunk [cyan]{chunk_id[:12]}[/cyan]？",
                choices=["y", "n"], default="n",
            )
            if confirm != "y":
                console.print("[dim]已取消[/dim]")
                return
            ok = self.storage.delete_chunk(chunk_id)
            if ok:
                # 同步删除向量索引
                if hasattr(self.storage, '_vector_index') and self.storage._vector_index is not None:
                    try:
                        self.storage._vector_index.delete_chunk(chunk_id)
                    except Exception:
                        pass
                console.print(f"[green]✓ 已删除 chunk[/green] [dim]({chunk_id[:12]})[/dim]")
                console.print("[dim]建议运行 /rebuild 重建 BM25 索引[/dim]")
            else:
                console.print(f"[red]删除失败（chunk 不存在）[/red]")
            return

        from core.sync.dedup import DedupScanner
        scanner = DedupScanner(threshold=0.85)

        with console.status("[bold yellow]扫描重复...[/bold yellow]", spinner="dots"):
            docs = self.storage.list_documents(limit=1000)
            for doc in docs:
                chunks = self.storage.get_chunks(doc.id)
                for c in chunks:
                    scanner.add_chunk(c.id, c.doc_id, c.content)
            results = scanner.scan()

        duplicates = [r for r in results if r.is_duplicate]
        if not duplicates:
            console.print("[green]✓ 未发现近似重复[/green]")
            return

        console.print(f"发现 {len(duplicates)} 个近似重复:")
        for d in duplicates:
            console.print(
                f"  {d.chunk_id[:8]} ← 重复于 {d.duplicate_of[:8]}  "
                f"相似度 {d.similarity:.1%}"
            )
        console.print(f"\n[dim]用 /dedup delete <chunk_id> 删除重复 chunk[/dim]")


    # ---- 图像生成 ----

    def _cmd_draw(self, arg: str) -> None:
        """基于文档内容生成配图：/draw <文档ID前8位> [--style 风格]"""
        from core.image import ImageGenerator, ImageError

        if not arg:
            console.print("[yellow]用法: /draw <文档ID前8位> [--style 水墨/赛博/绘本/简洁信息图][/yellow]")
            console.print("[dim]示例: /draw 862e0973 --style 水墨[/dim]")
            return

        # 解析参数
        doc_id_prefix = arg.split("--")[0].strip()
        style = "简洁信息图"
        if "--style" in arg:
            parts = arg.split("--style")
            if len(parts) > 1:
                style = parts[1].lstrip(" ").split("--")[0].strip() or "简洁信息图"

        try:
            gen = ImageGenerator()
        except ImageError as e:
            console.print(f"[red]图像生成未配置:[/red] {e}")
            console.print("[dim]请在 .env 中设置 AGNES_API_KEY（与 LLM 共用）[/dim]")
            return

        # 获取文档
        doc = self.storage.get_document(doc_id_prefix)
        if not doc:
            console.print(f"[red]文档不存在:[/red] {doc_id_prefix}")
            return

        # 获取文档前几段内容
        try:
            chunks = self.storage.get_chunks_by_doc(doc.id, limit=3)
            content = "\n".join(c.content for c in chunks)[:500]
        except Exception:
            content = doc.title

        # 生成图片
        console.print(f"[dim]开始为「{doc.title}」生成配图 (风格: {style})[/dim]")
        try:
            with console.status("[bold yellow]正在生成配图...[/bold yellow]", spinner="dots"):
                url = gen.doc_to_image(doc.title, content, style=style)
            console.print(f"\n[green]✓ 配图已生成[/green] [dim]({url})[/dim]")
            console.print("[dim]在浏览器中打开图片 URL 查看[/dim]")
            _record_activity("draw", doc.title[:40], getattr(self, 'active_session_name', None))
            # 尝试打开浏览器
            import webbrowser
            webbrowser.open(url)
        except ImageError as e:
            console.print(f"[red]✗ 生图失败:[/red] {e}")
            console.print("[dim]检查 AGNES_API_KEY 是否正确配置[/dim]")

    def _cmd_daily(self, arg: str) -> None:
        """生成每日知识卡片：/daily [--date YYYY-MM-DD] [--topics 主题1,主题2]"""
        from datetime import datetime
        from core.image import ImageGenerator, ImageError

        try:
            gen = ImageGenerator()
        except ImageError as e:
            console.print(f"[red]图像生成未配置:[/red] {e}")
            return

        # 解析参数
        date_str = datetime.now().strftime("%Y-%m-%d")
        topics = []

        if "--date" in arg:
            parts = arg.split("--date")
            if len(parts) > 1:
                date_str = parts[1].split("--")[0].strip() or date_str

        if "--topics" in arg:
            parts = arg.split("--topics")
            if len(parts) > 1:
                topic_str = parts[1].split("--")[0].strip()
                topics = [t.strip() for t in topic_str.split(",") if t.strip()]

        # 如果没有手动指定主题，从记忆中提取
        if not topics and self.memory_store:
            try:
                profile = self.memory_store.get_profile()
                if profile.focus_topics:
                    topics = profile.focus_topics[:5]
            except Exception:
                pass

        # 如果还是没有主题，生成一个默认的
        if not topics:
            topics = [f"2026年7月知识回顾"]

        console.print(f"[dim]开始生成每日知识卡片 ({date_str})[/dim]")
        try:
            with console.status("[bold yellow]正在生成每日知识卡片...[/bold yellow]", spinner="dots"):
                url = gen.daily_card(topics, date_str)
            console.print(f"\n[green]✓ 知识卡片已生成[/green] [dim]({url})[/dim]")
            _record_activity("daily", date_str, getattr(self, 'active_session_name', None))
            import webbrowser
            webbrowser.open(url)
        except ImageError as e:
            console.print(f"[red]✗ 生图失败:[/red] {e}")

    def _cmd_pic(self, arg: str) -> None:
        """直接文生图：/pic <描述>"""
        from core.image import ImageGenerator, ImageError

        if not arg.strip():
            console.print("[yellow]用法: /pic <图像描述>[/yellow]")
            console.print("[dim]示例: /pic 一只在竹林中散步的猫[/dim]")
            return

        try:
            gen = ImageGenerator()
        except ImageError as e:
            console.print(f"[red]图像生成未配置:[/red] {e}")
            return

        try:
            with console.status("[bold yellow]正在生成图像...[/bold yellow]", spinner="dots"):
                url = gen.text_to_image(arg.strip())
            console.print(f"\n[green]✓ 图像已生成[/green] [dim]({url})[/dim]")
            console.print("[dim]正在打开浏览器...[/dim]")
            _record_activity("pic", arg.strip()[:40], getattr(self, 'active_session_name', None))
            import webbrowser
            webbrowser.open(url)
        except ImageError as e:
            console.print(f"[red]✗ 生图失败:[/red] {e}")

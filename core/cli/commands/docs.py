"""文档管理 Mixin。

从 repl.py 第 1369-2237 行迁移，包含：
- ``_cmd_search`` BM25 搜索
- ``_cmd_ingest`` 入库文件/目录
- ``_cmd_note`` 文本直入库
- ``_cmd_clip`` 剪贴板入库
- ``_cmd_url`` 网页入库
- ``_ingest_one`` 入库单个文件
- ``_cmd_analyze`` 数据表智能分析
- ``_cmd_list`` 列出文档
- ``_cmd_show`` 查看文档详情
- ``_cmd_tags`` 列出所有标签
- ``_cmd_tag`` 标签管理
- ``_cmd_tag_rename`` 重命名标签
- ``_cmd_tag_merge`` 合并标签
- ``_cmd_delete`` 删除文档
- ``_cmd_reparse`` 重新解析文档
- ``_cmd_edit`` 编辑文档属性
- ``_cmd_stats`` 统计
- ``_cmd_rebuild`` 重建索引
- ``_cmd_retag`` 重新生成标签
- ``_cmd_watch`` 监控文件夹
- ``_cmd_web`` 启动 Web 后台
"""
from __future__ import annotations

import threading
from pathlib import Path
from typing import Optional

from rich.table import Table
from rich.prompt import Prompt
from rich.live import Live
from rich.spinner import Spinner

from config import settings
from core.ingestion.parser import parse, is_supported, SUPPORTED_EXTENSIONS, ParseError
from core.ingestion.chunker import chunk_document
from core.llm.client import LLMError
from core.cli.constants import console
from core.cli.welcome import _record_activity


class DocsMixin:
    """文档管理相关命令。"""

    def _cmd_search(self, query: str) -> None:
        """BM25 搜索：/search <关键词> [--tag 标签] [--limit N]"""
        if not query:
            console.print("[yellow]用法: /search <关键词> [--tag 标签] [--limit N][/yellow]")
            console.print("[dim]示例: /search 骨灰 --tag 政策 --limit 5[/dim]")
            return

        # 解析可选参数 --tag / --limit
        import shlex
        try:
            tokens = shlex.split(query)
        except ValueError:
            tokens = query.split()

        tag_filter: Optional[str] = None
        limit = 10
        keyword_parts: list[str] = []
        i = 0
        while i < len(tokens):
            tok = tokens[i]
            if tok in ("--tag", "-t") and i + 1 < len(tokens):
                tag_filter = tokens[i + 1]
                i += 2
            elif tok in ("--limit", "-n") and i + 1 < len(tokens):
                try:
                    limit = int(tokens[i + 1])
                except ValueError:
                    console.print(f"[yellow]无效的 --limit 值: {tokens[i + 1]}[/yellow]")
                    return
                i += 2
            else:
                keyword_parts.append(tok)
                i += 1

        keyword = " ".join(keyword_parts)
        if not keyword:
            console.print("[yellow]请提供搜索关键词[/yellow]")
            return

        # 如有 tag 筛选，扩大候选数后过滤
        fetch_k = limit * 3
        results = self.storage.bm25_search(keyword, top_k=fetch_k)

        if tag_filter:
            tagged_docs = self.storage.list_documents_by_tag(tag_filter)
            allowed_ids = {d.id for d in tagged_docs}
            results = [r for r in results if r.doc_id in allowed_ids]
            if not results:
                console.print(
                    f"[yellow]未找到与 '{keyword}' 相关且带标签 '{tag_filter}' 的内容[/yellow]"
                )
                console.print(f"[dim]带此标签的文档共 {len(tagged_docs)} 个[/dim]")
                return
            total_found = len(results)
            results = results[:limit]
        else:
            if not results:
                console.print(f"[yellow]未找到与 '{keyword}' 相关的内容[/yellow]")
                return
            total_found = len(results)
            results = results[:limit]

        tag_hint = f" [dim]· 标签筛选: {tag_filter}[/dim]" if tag_filter else ""
        console.print(f"\n[bold]找到 {len(results)} 条相关结果[/bold] [dim](BM25)[/dim]{tag_hint}\n")
        _record_activity("search", keyword[:40])
        import re as _re
        for i, r in enumerate(results, 1):
            preview = r.content[:200].replace("\n", " ")
            # 先转义 Rich markup 字符，避免原文本中的 [ 干扰渲染
            preview = preview.replace("[", "\\[").replace("[/]", "")
            # 高亮关键词
            try:
                pattern = _re.escape(keyword)
                preview = _re.sub(
                    f"({pattern})",
                    r"[bold yellow on black]\1[/]",
                    preview,
                )
            except Exception:
                pass
            console.print(
                f"[cyan]{i}.[/cyan] [green]({r.score:.2f})[/green] "
                f"[dim][{r.doc_title}][/dim]"
            )
            console.print(f"   {preview}{'...' if len(r.content) > 200 else ''}\n")

        # 分页提示
        if total_found > limit:
            console.print(f"[dim]还有 {total_found - limit} 条,用 --limit {total_found} 查看更多[/dim]\n")

    def _cmd_ingest(self, path_str: str) -> None:
        """入库文件或目录。"""
        if not path_str:
            console.print("[yellow]用法: /ingest <文件或目录路径>[/yellow]")
            return
        # 支持 ~ 展开
        path = Path(path_str).expanduser().resolve()
        if not path.exists():
            console.print(f"[red]路径不存在:[/red] {path}")
            return

        files: list[Path] = []
        if path.is_file():
            files = [path]
        elif path.is_dir():
            for ext in SUPPORTED_EXTENSIONS:
                files.extend(path.rglob(f"*{ext}"))
            files = sorted(set(files))

        if not files:
            console.print("[yellow]未找到支持的文件[/yellow]")
            return

        console.print(f"\n[bold]入库 {len(files)} 个文件...[/bold]\n")
        success = 0
        for f in files:
            if self._ingest_one(f):
                success += 1
                # 宠物经验埋点：ingest 行为
                self._pet_gain_exp(30, "ingest")
        console.print(f"\n[bold]完成[/bold] · 成功 {success} / 共 {len(files)}\n")
        if success > 0:
            _record_activity("ingest", f"{success}个文件")

    def _cmd_note(self, arg: str) -> None:
        """文本直入库：/note 一段文字。"""
        if not arg.strip():
            console.print("[yellow]用法: /note <文本内容>[/yellow]")
            console.print("[dim]示例: /note 骨灰安置费用标准：基本服务费800元[/dim]")
            return
        from core.ingestion.quick import save_text
        try:
            file_path = save_text(arg.strip())
            console.print(f"[dim]已保存临时文件: {file_path.name}[/dim]")
            if self._ingest_one(file_path):
                self._pet_gain_exp(10, "ingest")
                console.print("[green]✓ 文本已入库[/green]")
        except Exception as e:
            console.print(f"[red]入库失败: {e}[/red]")

    def _cmd_clip(self, arg: str = "") -> None:
        """剪贴板入库：自动识别截图/文字/URL。"""
        from core.ingestion.quick import save_clipboard
        with console.status("[bold yellow]读取剪贴板...[/bold yellow]", spinner="dots"):
            file_path, content_type = save_clipboard()

        if file_path is None:
            console.print(f"[yellow]剪贴板内容无效: {content_type}[/yellow]")
            console.print("[dim]支持：截图（Cmd+Shift+4）、复制文字、复制 URL[/dim]")
            return

        type_label = {"image": "截图", "text": "文本", "url": "网页"}.get(content_type, "内容")
        console.print(f"[dim]检测到: {type_label}[/dim]")
        if self._ingest_one(file_path):
            self._pet_gain_exp(10, "ingest")
            console.print(f"[green]✓ {type_label}已入库[/green]")

    def _cmd_url(self, arg: str) -> None:
        """网页入库：/url https://...。"""
        if not arg.strip():
            console.print("[yellow]用法: /url <网页地址>[/yellow]")
            console.print("[dim]示例: /url https://www.example.com/policy[/dim]")
            return
        url = arg.strip()
        if not (url.startswith("http://") or url.startswith("https://")):
            url = "https://" + url

        from core.ingestion.quick import save_url
        with console.status(f"[bold yellow]抓取网页...[/bold yellow] {url}", spinner="dots"):
            try:
                file_path = save_url(url)
            except Exception as e:
                console.print(f"[red]抓取失败: {e}[/red]")
                return

        console.print(f"[dim]已提取网页正文: {file_path.name}[/dim]")
        if self._ingest_one(file_path):
            self._pet_gain_exp(15, "ingest")
            console.print("[green]✓ 网页已入库[/green]")

    def _ingest_one(self, file_path: Path) -> bool:
        """入库单个文件。"""
        if not is_supported(file_path):
            return False
        try:
            parsed = parse(file_path)
            if not parsed.text.strip():
                if parsed.meta.get("ocr_unavailable"):
                    console.print(
                        f"  [yellow]跳过图片[/yellow]（OCR 未安装）: {file_path.name}  "
                        f"[dim]用 brew install tesseract tesseract-lang 启用[/dim]"
                    )
                else:
                    console.print(f"  [yellow]跳过空内容[/yellow]: {file_path.name}")
                return False
            chunks = chunk_document(
                parsed,
                chunk_size=settings.chunk_size,
                chunk_overlap=settings.chunk_overlap,
            )
            # 去重检查
            import hashlib
            content_hash = hashlib.sha256(parsed.text.encode("utf-8")).hexdigest()
            doc_id = content_hash[:32]
            if self.storage.get_document(doc_id) is not None:
                console.print(f"  [cyan]已存在（跳过）[/cyan]: {file_path.name}")
                return False

            # 自动打标签
            tags: list[str] = []
            if self.llm_available:
                try:
                    from core.classify.tagger import Tagger
                    tagger = Tagger()
                    tags = tagger.generate_tags_for_document(parsed)
                except Exception as e:
                    console.print(f"  [dim]标签生成失败: {type(e).__name__}[/dim]")

            record = self.storage.save_document(parsed, chunks, copy_file=True, tags=tags)
            tag_str = f"  [dim]标签: {', '.join(tags)}[/dim]" if tags else ""
            console.print(
                f"  [green]✓[/green] {file_path.name}  "
                f"[dim]分块 {record.chunk_count} / {record.total_tokens} tokens[/dim]{tag_str}"
            )
            return True
        except ParseError as e:
            console.print(f"  [red]解析失败[/red]: {file_path.name} - {e}")
            return False
        except Exception as e:
            console.print(f"  [red]入库失败[/red]: {file_path.name} - {type(e).__name__}: {e}")
            return False

    # ---- 数据表分析 ----

    def _cmd_analyze(self, arg: str) -> None:
        """数据表智能分析：/analyze <文件路径> [--sheet 名称 | --sheets]"""
        if not arg:
            console.print("[yellow]用法:[/yellow]")
            console.print("  [cyan]/analyze <文件路径>[/cyan]              一键分析")
            console.print("  [cyan]/analyze <文件路径> --sheet 名称[/cyan]  指定 Excel sheet")
            console.print("  [cyan]/analyze <文件路径> --sheets[/cyan]     列出所有 sheet")
            console.print("[dim]支持格式: xlsx / xls / csv / tsv / json[/dim]")
            return

        if not self.llm_available:
            console.print("[red]LLM 未配置，数据分析需要 AGNES_API_KEY[/red]")
            return

        # 解析参数
        tokens = arg.split()
        file_path_str = tokens[0] if tokens else ""
        list_sheets_only = "--sheets" in arg
        sheet_name = None
        if "--sheet" in tokens:
            idx = tokens.index("--sheet")
            if idx + 1 < len(tokens):
                sheet_name = tokens[idx + 1]

        if not file_path_str:
            console.print("[red]请提供文件路径[/red]")
            return

        path = Path(file_path_str).expanduser().resolve()
        if not path.exists():
            console.print(f"[red]文件不存在:[/red] {path}")
            return

        # 仅列出 sheet
        if list_sheets_only:
            try:
                from core.analyze.analyzer import DataAnalyzer
                az = DataAnalyzer()
                sheets = az.list_sheets(path)
                if not sheets:
                    console.print("[yellow]该文件不是 Excel，无 sheet[/yellow]")
                else:
                    console.print(f"[bold]Excel「{path.name}」的 sheets:[/bold]")
                    for i, s in enumerate(sheets, 1):
                        console.print(f"  [cyan]{i}.[/cyan] {s}")
            except Exception as e:
                console.print(f"[red]读取 sheet 失败:[/red] {e}")
            return

        # 执行分析
        from rich.spinner import Spinner
        from rich.live import Live

        try:
            from core.analyze.analyzer import DataAnalyzer
            console.print(f"\n[bold]分析中[/bold] [dim]{path.name}[/dim]...")
            with Live(Spinner("dots", text="[cyan]读取数据 + 统计 + AI 解读...[/cyan]"), console=console, transient=True):
                az = DataAnalyzer()
                result = az.analyze(path, sheet_name=sheet_name)
            # 渲染结果
            az.render(result)
            # 保存到当前分析状态（供追问用）
            self.current_analysis = (az, result)
            _record_activity("analyze", path.name[:40])
            console.print(
                "[dim]提示：现在可以直接追问，如「按月份汇总」「哪个最多」「缺失值情况」[/dim]\n"
            )
            # 宠物经验埋点：analyze 行为
            self._pet_gain_exp(15, "analyze")
        except FileNotFoundError as e:
            console.print(f"[red]{e}[/red]")
        except ValueError as e:
            console.print(f"[red]格式不支持:[/red] {e}")
        except Exception as e:
            err_msg = str(e).replace("[", "\\[")
            console.print(f"[red]分析失败:[/red] {type(e).__name__}: {err_msg}")

    def _cmd_list(self, arg: str = "") -> None:
        """列出文档。"""
        docs = self.storage.list_documents(limit=100)
        if not docs:
            console.print("[yellow]知识库为空[/yellow]")
            return
        table = Table(title=f"知识库文档（共 {len(docs)} 条）")
        table.add_column("ID", style="cyan", width=10)
        table.add_column("标题", style="white")
        table.add_column("类型", style="yellow")
        table.add_column("标签", style="magenta")
        table.add_column("分块", justify="right")
        table.add_column("Tokens", justify="right")
        table.add_column("入库时间", style="dim")
        for d in docs:
            table.add_row(
                d.id[:8], d.title, d.file_type,
                "、".join(d.tags) if d.tags else "[dim]-[/dim]",
                str(d.chunk_count), str(d.total_tokens),
                d.created_at[:19],
            )
        console.print(table)

    def _cmd_show(self, id_str: str) -> None:
        """查看文档详情。"""
        if not id_str:
            console.print("[yellow]用法: /show <id 前 8 位>[/yellow]")
            return
        # 简写匹配
        doc_id = self._resolve_doc_id(id_str)
        if not doc_id:
            console.print(f"[red]未找到文档:[/red] {id_str}")
            return
        doc = self.storage.get_document(doc_id)
        if not doc:
            console.print(f"[red]未找到文档[/red]")
            return
        console.print(f"\n[bold cyan]{doc.title}[/bold cyan]")
        console.print(f"  ID:       {doc.id}")
        console.print(f"  文件名:   {doc.file_name}")
        console.print(f"  类型:     {doc.file_type}")
        console.print(f"  大小:     {doc.file_size} bytes")
        console.print(f"  语言:     {doc.language}")
        console.print(f"  分块:     {doc.chunk_count}")
        console.print(f"  Tokens:   {doc.total_tokens}")
        console.print(f"  入库时间: {doc.created_at}")
        console.print(f"  原路径:   {doc.file_path}")
        if doc.meta:
            # 显示关键 meta 字段（saved_path/ocr_used/ocr_failed_pages 等）
            meta_parts = [f"{k}={v}" for k, v in doc.meta.items() if v]
            console.print(f"  元信息:   [dim]{', '.join(meta_parts[:5])}[/dim]")
        if doc.tags:
            console.print(f"  标签:     [magenta]{'、'.join(doc.tags)}[/magenta]")
        else:
            console.print(f"  标签:     [dim]（无）[/dim]")
        console.print()
        chunks = self.storage.get_chunks(doc_id)
        for c in chunks[:3]:
            console.print(f"[dim]--- Chunk #{c.index} ---[/dim]")
            console.print(c.content[:400] + ("..." if len(c.content) > 400 else ""))
            console.print()
        if len(chunks) > 3:
            console.print(f"[dim]... 还有 {len(chunks) - 3} 块[/dim]\n")

    def _cmd_tags(self) -> None:
        """列出所有标签。"""
        tags = self.storage.list_all_tags()
        if not tags:
            console.print("[yellow]还没有标签[/yellow]")
            console.print("[dim]提示: 在终端运行 ima retag 给文档批量打标签[/dim]")
            return
        console.print(f"\n[bold]所有标签[/bold] [dim]（共 {len(tags)} 个）[/dim]\n")
        for tag, cnt in tags.items():
            console.print(f"  [magenta]{tag}[/magenta] [dim]×{cnt}[/dim]")
        console.print()

    def _cmd_tag(self, arg: str) -> None:
        """标签管理：/tag [rename|merge|<名称>]

        - /tag 不带参数 → 显示所有标签
        - /tag rename <old> <new> → 重命名标签
        - /tag merge <src> <dst> → 合并标签
        - /tag <名称> → 按标签筛选
        """
        if arg:
            parts = arg.split(maxsplit=1)
            if parts[0].lower() == "rename" and len(parts) > 1:
                self._cmd_tag_rename(parts[1])
            elif parts[0].lower() == "merge" and len(parts) > 1:
                self._cmd_tag_merge(parts[1])
            else:
                # 按标签筛选
                name = arg
                docs = self.storage.list_documents_by_tag(name)
                if not docs:
                    console.print(f"[yellow]没有带标签 '{name}' 的文档[/yellow]")
                    console.print("[dim]提示: 输入 /tags 查看所有可用标签[/dim]")
                    return
                console.print(f"\n[bold]带标签 '{name}' 的文档[/bold] [dim]（共 {len(docs)} 个）[/dim]\n")
                table = Table(show_lines=False)
                table.add_column("ID", style="cyan", width=10)
                table.add_column("标题", style="white")
                table.add_column("类型", style="yellow")
                table.add_column("标签", style="magenta")
                for d in docs:
                    table.add_row(
                        d.id[:8], d.title, d.file_type,
                        "、".join(d.tags),
                    )
                console.print(table)
                console.print()
        else:
            self._cmd_tags()

    def _cmd_tag_rename(self, arg: str) -> None:
        """重命名标签：/tag rename <旧名> <新名>"""
        parts = arg.split(maxsplit=1)
        if len(parts) < 2:
            console.print("[yellow]用法: /tag rename <旧标签> <新标签>[/yellow]")
            return
        old_tag, new_tag = parts[0].strip(), parts[1].strip()
        if not new_tag:
            console.print("[yellow]新标签名不能为空[/yellow]")
            return
        affected = self.storage.rename_tag(old_tag, new_tag)
        if affected > 0:
            console.print(f"[green]✓ 已重命名标签[/green] [dim]{old_tag} → [/dim][magenta]{new_tag}[/magenta]")
            console.print(f"  [dim]影响 {affected} 个文档[/dim]")
        else:
            console.print(f"[yellow]未找到标签: {old_tag}[/yellow]")

    def _cmd_tag_merge(self, arg: str) -> None:
        """合并标签：/tag merge <源标签> <目标标签>"""
        parts = arg.split(maxsplit=1)
        if len(parts) < 2:
            console.print("[yellow]用法: /tag merge <源标签> <目标标签>[/yellow]")
            console.print("[dim]源标签将被删除，其文档改用目标标签[/dim]")
            return
        source_tag, target_tag = parts[0].strip(), parts[1].strip()
        if not target_tag:
            console.print("[yellow]目标标签名不能为空[/yellow]")
            return
        affected = self.storage.merge_tag(source_tag, target_tag)
        if affected > 0:
            console.print(f"[green]✓ 已合并标签[/green] [dim]{source_tag} → [/dim][magenta]{target_tag}[/magenta]")
            console.print(f"  [dim]影响 {affected} 个文档[/dim]")
        else:
            console.print(f"[yellow]未找到源标签: {source_tag}[/yellow]")

    def _cmd_delete(self, id_str: str) -> None:
        """删除文档。"""
        if not id_str:
            console.print("[yellow]用法: /delete <id 前 8 位>[/yellow]")
            return
        doc_id = self._resolve_doc_id(id_str)
        if not doc_id:
            console.print(f"[red]未找到文档:[/red] {id_str}")
            return
        doc = self.storage.get_document(doc_id)
        if not doc:
            console.print("[red]文档不存在[/red]")
            return
        # 确认
        confirm = Prompt.ask(
            f"确定删除 [cyan]{doc.title}[/cyan]？",
            choices=["y", "n"], default="n"
        )
        if confirm != "y":
            console.print("[dim]已取消[/dim]")
            return
        if self.storage.delete_document(doc_id):
            console.print(f"[green]✓ 已删除[/green]")
        else:
            console.print(f"[red]删除失败[/red]")

    def _cmd_reparse(self, id_str: str) -> None:
        """重新解析文档：/reparse <id 前 8 位 | 文件路径>

        适用场景：
        - OCR 失败的文档（安装 tesseract 后重新解析）
        - 文件内容更新后重新入库
        - 解析器升级后重试

        流程：删除旧文档 → 重置 OCR 缓存 → 重新解析原文件 → 入库
        """
        if not id_str:
            console.print("[yellow]用法: /reparse <id 前 8 位 | 文件路径>[/yellow]")
            console.print("[dim]用于重新解析 OCR 失败或内容更新的文档[/dim]")
            return

        # 判断输入是 doc_id 还是文件路径
        from pathlib import Path as _Path
        maybe_path = _Path(id_str)
        if maybe_path.exists() and maybe_path.is_file():
            # 直接按文件路径处理
            file_path = maybe_path
            # 尝试找到对应的旧 doc_id 以便删除
            doc_id = None
        else:
            # 按 doc_id 前缀匹配
            doc_id = self._resolve_doc_id(id_str)
            if not doc_id:
                console.print(f"[red]未找到文档:[/red] {id_str}")
                return
            doc = self.storage.get_document(doc_id)
            if not doc:
                console.print("[red]文档不存在[/red]")
                return
            file_path = _Path(doc.file_path)
            if not file_path.exists():
                console.print(f"[red]原文件不存在:[/red] {file_path}")
                console.print("[dim]文档记录中的原文件路径已失效[/dim]")
                return

        # 确认
        console.print(f"[dim]将重新解析: {file_path.name}[/dim]")
        confirm = Prompt.ask(
            "确定重新解析？（会先删除旧文档记录）",
            choices=["y", "n"], default="n",
        )
        if confirm != "y":
            console.print("[dim]已取消[/dim]")
            return

        # 1. 删除旧文档（如果存在 doc_id）
        if doc_id:
            self.storage.delete_document(doc_id)
            console.print(f"[dim]已删除旧记录[/dim]")

        # 2. 重置 OCR 缓存（用户可能刚安装了 tesseract）
        from core.ingestion.parser import reset_ocr_cache
        reset_ocr_cache()

        # 3. 重新解析并入库
        console.print(f"[bold]重新解析...[/bold] [dim]{file_path.name}[/dim]")
        if self._ingest_one(file_path):
            self._pet_gain_exp(15, "ingest")
            console.print("[green]✓ 重新解析完成[/green]")
            # 如果原文件被追踪，更新追踪记录
            try:
                from core.sync.tracker import FileTracker
                tracker = FileTracker(storage_path=settings.storage_path)
                tracker.scan_directory(str(file_path.parent))
            except Exception:
                pass  # 追踪更新失败不影响主流程
        else:
            console.print(f"[red]重新解析失败[/red]")

    def _cmd_edit(self, arg: str) -> None:
        """编辑文档属性：/edit <id> <field> <value>

        支持的字段：
            title <新标题>   修改文档标题
            tags  <标签列表>  修改标签（逗号分隔）
        """
        if not arg:
            console.print("[yellow]用法: /edit <id> <field> <value>[/yellow]")
            console.print("  [cyan]/edit <id> title <新标题>[/cyan]    修改标题")
            console.print("  [cyan]/edit <id> tags <标签,标签>[/cyan]   修改标签")
            return
        parts = arg.split(maxsplit=2)
        if len(parts) < 2:
            console.print("[yellow]用法: /edit <id> <field> <value>[/yellow]")
            return
        id_str, field = parts[0], parts[1].lower()
        value = parts[2].strip() if len(parts) > 2 else ""
        doc_id = self._resolve_doc_id(id_str)
        if not doc_id:
            console.print(f"[red]未找到文档:[/red] {id_str}")
            return
        doc = self.storage.get_document(doc_id)
        if not doc:
            console.print(f"[red]文档不存在[/red]")
            return

        if field == "title":
            if not value:
                console.print("[yellow]新标题不能为空[/yellow]")
                return
            ok = self.storage.update_document_title(doc_id, value)
            if ok:
                console.print(f"[green]✓ 标题已更新[/green]")
                console.print(f"  [dim]{doc.title} → [/dim][cyan]{value}[/cyan]")
            else:
                console.print(f"[red]更新失败[/red]")
        elif field == "tags":
            if not value:
                # 空值表示清除所有标签
                tags = []
            else:
                tags = [t.strip() for t in value.replace("、", ",").split(",") if t.strip()]
            ok = self.storage.update_document_tags(doc_id, tags)
            if ok:
                if tags:
                    console.print(f"[green]✓ 标签已更新: [magenta]{'、'.join(tags)}[/magenta][/green]")
                else:
                    console.print(f"[green]✓ 已清除所有标签[/green]")
            else:
                console.print(f"[red]更新失败[/red]")
        else:
            console.print(f"[red]未知字段: '{field}'[/red]  允许: title / tags")

    def _cmd_stats(self, arg: str = "") -> None:
        """统计。"""
        s = self.storage.stats()
        bm25_info = self.storage.bm25.info()
        console.print("\n[bold]知识库统计[/bold]\n")
        console.print(f"  文档总数:    [cyan]{s['documents']}[/cyan]")
        console.print(f"  分块总数:    [cyan]{s['chunks']}[/cyan]")
        console.print(f"  总 Tokens:   [cyan]{s['total_tokens']:,}[/cyan]")
        console.print(f"  原文件大小:  [cyan]{s['total_size_mb']} MB[/cyan]")
        console.print(f"  BM25 词汇量: [cyan]{bm25_info['vocabulary']}[/cyan]")
        if s["by_type"]:
            console.print("\n  [bold]按类型分布:[/bold]")
            for ftype, cnt in s["by_type"].items():
                console.print(f"    {ftype:12s} {cnt}")
        # 标签统计
        tags = self.storage.list_all_tags()
        if tags:
            console.print(f"\n  [bold]标签统计[/bold] [dim]（共 {len(tags)} 个）[/dim]")
            for tag, cnt in list(tags.items())[:10]:
                console.print(f"    [magenta]{tag}[/magenta] [dim]×{cnt}[/dim]")
            if len(tags) > 10:
                console.print(f"    [dim]... 还有 {len(tags) - 10} 个标签[/dim]")
        console.print()

    def _cmd_rebuild(self, arg: str = "") -> None:
        """重建索引：/rebuild [--vector]

        --vector / -v: 同时重建向量索引并热更新到当前会话的检索链路
        """
        vector_flag = "--vector" in arg or "-v" in arg
        console.print("[bold]重建 BM25 索引...[/bold]")
        count = self.storage.rebuild_bm25_index()
        info = self.storage.bm25.info()
        console.print(f"[green]✓ BM25 完成[/green] · 索引 {info['chunks']} 块 / 词汇 {info['vocabulary']}")

        if vector_flag:
            try:
                from core.retrieval.vector import VectorIndex
                vector_index = VectorIndex()
                if vector_index.is_available():
                    console.print("[bold]重建向量索引...[/bold]")
                    v_count = self.storage.rebuild_vector_index(vector_index)
                    console.print(f"[green]✓ 向量索引完成[/green] · {v_count} 块")
                    # 热更新：让当前会话的检索链路立即用上新索引
                    self.storage.attach_vector_index(vector_index)
                    if self.administrator is not None:
                        self.administrator.hybrid.vector = vector_index
                    console.print("[dim]已热更新到当前会话（无需重启）[/dim]")
                else:
                    console.print("[yellow]! 向量索引不可用（依赖未安装）[/yellow]")
                    console.print("[dim]用 'bash install.sh --vector' 安装[/dim]")
            except ImportError:
                console.print("[yellow]! 向量依赖未安装[/yellow]")
            except Exception as e:
                console.print(f"[red]向量索引重建失败: {e}[/red]")
                console.print("[dim]BM25 索引已重建，向量索引仍可用旧实例[/dim]")

    def _cmd_retag(self, arg: str) -> None:
        """重新生成/补全文档标签。"""
        from core.classify.tagger import Tagger
        from core.llm.client import LLMError

        if not settings.has_llm():
            console.print("[red]未配置 AGNES_API_KEY，无法调用 LLM 打标签[/red]")
            return

        # 解析参数: /retag [-f] [-d ID] [-n N]
        force = "-f" in arg or "--force" in arg
        doc_id = ""
        limit = 0
        parts = arg.split()
        for i, p in enumerate(parts):
            if p in ("-d", "--doc-id") and i + 1 < len(parts):
                doc_id = parts[i + 1]
            elif p in ("-n", "--limit") and i + 1 < len(parts):
                try:
                    limit = int(parts[i + 1])
                except ValueError:
                    pass

        # 选目标文档
        if doc_id:
            if len(doc_id) < 32:
                all_docs = self.storage.list_documents(limit=10000)
                target_docs = [d for d in all_docs if d.id.startswith(doc_id)]
            else:
                d = self.storage.get_document(doc_id)
                target_docs = [d] if d else []
            if not target_docs:
                console.print(f"[red]未找到文档: {doc_id}[/red]")
                return
        else:
            all_docs = self.storage.list_documents(limit=10000)
            if force:
                target_docs = all_docs
            else:
                target_docs = [d for d in all_docs if not d.tags]
            if limit:
                target_docs = target_docs[:limit]

        if not target_docs:
            console.print("[yellow]没有需要打标签的文档[/yellow]")
            if not force and not doc_id:
                console.print("[dim]提示: /retag -f 重新生成所有标签[/dim]")
            return

        console.print(f"\n[bold]开始打标签[/bold] · 共 {len(target_docs)} 个文档\n")

        try:
            tagger = Tagger()
        except LLMError as e:
            console.print(f"[red]LLM 初始化失败:[/red] {e}")
            return

        success, fail = 0, 0
        for i, doc in enumerate(target_docs, 1):
            chunks = self.storage.get_chunks(doc.id)
            content_preview = "\n".join(c.content for c in chunks)
            console.print(f"[{i}/{len(target_docs)}] [cyan]{doc.title[:50]}[/cyan]")
            try:
                tags = tagger.generate_tags(
                    title=doc.title, file_type=doc.file_type, content=content_preview,
                )
                if tags:
                    self.storage.update_document_tags(doc.id, tags)
                    console.print(f"  [green]✓[/green] [dim]{', '.join(tags)}[/dim]")
                    success += 1
                else:
                    console.print("  [yellow]未生成标签[/yellow]")
                    fail += 1
            except Exception as e:
                console.print(f"  [red]失败: {e}[/red]")
                fail += 1

        console.print(f"\n[bold]完成[/bold] · 成功 {success} / 失败 {fail}\n")

    def _cmd_watch(self, arg: str) -> None:
        """监控文件夹变化自动入库。"""
        if not arg.strip():
            console.print("[yellow]用法: /watch <目录路径> [-i 间隔秒] [--once][/yellow]")
            console.print("[dim]示例: /watch ~/Documents/政策文件[/dim]")
            return

        parts = arg.split()
        dir_path = parts[0]
        interval = 10
        once = "--once" in arg

        for i, p in enumerate(parts):
            if p in ("-i", "--interval") and i + 1 < len(parts):
                try:
                    interval = int(parts[i + 1])
                except ValueError:
                    pass

        path = Path(dir_path).expanduser().resolve()
        if not path.is_dir():
            console.print(f"[red]路径不是文件夹: {path}[/red]")
            return

        console.print(f"[bold green]📡 文件监控启动[/bold green]")
        console.print(f"  目录: [cyan]{path}[/cyan]")
        console.print(f"  间隔: {interval}秒" + ("（单次模式）" if once else "（持续模式，Ctrl+C 退出）"))
        console.print(f"  支持格式: {', '.join(sorted(SUPPORTED_EXTENSIONS))}\n")

        import time
        seen = set()

        def scan_once() -> int:
            files = []
            for ext in SUPPORTED_EXTENSIONS:
                files.extend(path.rglob(f"*{ext}"))
            files = sorted(set(files))
            new_files = [f for f in files if str(f) not in seen]
            if not new_files:
                return 0
            console.print(f"[dim]{time.strftime('%H:%M:%S')} 发现 {len(new_files)} 个新文件[/dim]")
            success = 0
            for f in new_files:
                seen.add(str(f))
                if self._ingest_one(f):
                    success += 1
                    self._pet_gain_exp(30, "ingest")
            if success:
                console.print(f"[green]✓ 本次入库 {success} 个文件[/green]\n")
            return success

        try:
            scan_once()
            if once:
                return
            while True:
                time.sleep(interval)
                scan_once()
        except KeyboardInterrupt:
            console.print(f"\n[yellow]监控已停止[/yellow]")

    def _cmd_web(self, arg: str) -> None:
        """启动/停止 FastAPI Web 后台。
        用法:
          /web                  启动 Web（默认 127.0.0.1:8501）
          /web --host 0.0.0.0 --port 8080  自定义地址和端口
          /web stop             停止 Web 后台服务
        """
        try:
            import uvicorn
        except ImportError:
            console.print("[red]缺少 Web 依赖，请运行: pip install uvicorn fastapi[/red]")
            return

        parts = arg.strip().split()

        # ---- 停止子命令 ----
        if parts and parts[0] == "stop":
            if self._web_server is None:
                console.print("[yellow]Web 服务未在运行[/yellow]")
                return
            console.print("[yellow]正在停止 Web 服务...[/yellow]")
            self._web_server.should_exit = True
            if self._web_thread is not None:
                self._web_thread.join(timeout=5)
            self._web_server = None
            self._web_thread = None
            console.print("[green]✓ Web 服务已停止[/green]")
            return

        # ---- 已运行时给出提示 ----
        if self._web_server is not None:
            console.print("[yellow]Web 服务已在运行中，请先执行 /web stop 停止[/yellow]")
            return

        host = "127.0.0.1"
        port = 8501
        for i, p in enumerate(parts):
            if p in ("--host", "-h") and i + 1 < len(parts):
                host = parts[i + 1]
            elif p in ("-p", "--port") and i + 1 < len(parts):
                port = int(parts[i + 1])

        from web.app import create_app
        app = create_app()
        config = uvicorn.Config(app, host=host, port=port, log_level="warning")
        self._web_server = uvicorn.Server(config)

        def _run_server():
            try:
                self._web_server.run()
            except Exception:
                pass

        self._web_thread = threading.Thread(target=_run_server, daemon=True)
        self._web_thread.start()

        console.print(f"\n[bold green]IMA Web 后台启动[/bold green]\n")
        console.print(f"  地址: [cyan]http://{host}:{port}[/cyan]")
        console.print(f"  停止: [dim]/web stop[/dim]\n")

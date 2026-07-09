"""知识库 CLI 入口。

用法：
    python run.py chat                     # 交互式对话模式（终端 REPL）
    python run.py web                      # 启动 Web 后台
    python run.py ingest <文件或目录>      # 入库（自动打标签）
    python run.py list                     # 列出所有文档
    python run.py search <关键词> [--tag T] # BM25 智能搜索（可按标签筛选）
    python run.py ask "<问题>"             # RAG 问答（单次）
    python run.py analyze <文件> [-s sheet] # 数据表智能分析（Excel/CSV/TSV/JSON）
    python run.py show <doc_id>            # 查看文档详情
    python run.py stats                    # 知识库统计（含标签统计）
    python run.py retag [--force] [-d ID]  # 重新生成/补全文档标签
    python run.py graph build [--force]    # 构建知识图谱（LLM 抽取实体关系）
    python run.py graph stats              # 图谱统计
    python run.py graph export             # 导出 HTML 可视化
    python run.py delete <doc_id>          # 删除文档
    python run.py rebuild                  # 重建 BM25 索引
    python run.py watch <文件夹>           # 监控文件夹变化自动入库
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Optional

import click
from rich.console import Console
from rich.table import Table

from config import settings
from core.ingestion.parser import parse, is_supported, SUPPORTED_EXTENSIONS, ParseError
from core.ingestion.chunker import chunk_document
from core.storage import Storage

console = Console()


def _ensure_dirs() -> None:
    """确保存储目录存在。"""
    settings.ensure_dirs()


def _ingest_one(storage: Storage, file_path: Path, verbose: bool = False, auto_tag: bool = True) -> bool:
    """入库单个文件。

    Args:
        storage: 存储实例
        file_path: 文件路径
        verbose: 详细输出
        auto_tag: 是否调用 LLM 自动打标签

    Returns:
        True 成功 / False 失败
    """
    if not is_supported(file_path):
        console.print(f"  [yellow]跳过不支持的格式[/yellow]: {file_path.name}")
        return False

    try:
        # 1. 解析
        parsed = parse(file_path)
        if not parsed.text.strip():
            # 检查是否是 OCR 不可用导致的
            if parsed.meta.get("ocr_unavailable"):
                console.print(
                    f"  [yellow]跳过图片[/yellow]（OCR 未安装）: {file_path.name}  "
                    f"[dim]用 brew install tesseract tesseract-lang 启用[/dim]"
                )
            else:
                console.print(f"  [yellow]跳过空内容[/yellow]: {file_path.name}")
            return False

        # 2. 分块
        chunks = chunk_document(
            parsed,
            chunk_size=settings.chunk_size,
            chunk_overlap=settings.chunk_overlap,
        )

        # 3. 存储去重检查
        import hashlib
        content_hash = hashlib.sha256(parsed.text.encode("utf-8")).hexdigest()
        doc_id = content_hash[:32]
        if storage.get_document(doc_id) is not None:
            console.print(f"  [cyan]已存在（跳过）[/cyan]: {file_path.name}")
            return False

        # 4. 自动打标签（可选）
        tags: list[str] = []
        if auto_tag and settings.has_llm():
            try:
                from core.classify.tagger import Tagger
                tagger = Tagger()
                tags = tagger.generate_tags_for_document(parsed)
            except Exception as e:
                if verbose:
                    console.print(f"     [yellow]标签生成失败[/yellow]: {type(e).__name__}: {e}")

        # 5. 保存
        record = storage.save_document(parsed, chunks, copy_file=True, tags=tags)

        tag_str = f"  [dim]标签: {', '.join(tags)}[/dim]" if tags else ""
        console.print(
            f"  [green]✓[/green] {file_path.name}  "
            f"[dim]分块 {record.chunk_count} 块 / {record.total_tokens} tokens[/dim]{tag_str}"
        )
        if verbose and chunks:
            console.print(f"     [dim]预览首块: {chunks[0].content[:80]}...[/dim]")
        return True

    except ParseError as e:
        console.print(f"  [red]解析失败[/red]: {file_path.name} - {e}")
        return False
    except Exception as e:
        console.print(f"  [red]入库失败[/red]: {file_path.name} - {type(e).__name__}: {e}")
        return False


# ============================================================
# CLI 命令
# ============================================================

@click.group(help="个人知识库 CLI · 输入 --help 查看所有命令", invoke_without_command=True)
@click.pass_context
def cli(ctx) -> None:
    """主命令组。不带子命令时默认进入 REPL 交互模式。"""
    _ensure_dirs()
    # 屏蔽 macOS LibreSSL 警告（urllib3 v2 兼容性）
    import warnings
    warnings.filterwarnings("ignore", message="urllib3 v2 only supports OpenSSL")
    # 不带子命令时默认进入 REPL
    if ctx.invoked_subcommand is None:
        from repl import main as repl_main
        repl_main()


@cli.command(name="web", help="启动 Web 后台（内网访问：ima web --host 0.0.0.0）")
@click.option("--host", "-h", default="127.0.0.1", help="绑定地址（默认 127.0.0.1）")
@click.option("--port", "-p", default=8501, type=int, help="端口（默认 8501）")
def cli_web(host: str, port: int) -> None:
    """启动 Web 后台服务。

    \b
    示例：
      ima web                       # 本地访问 http://127.0.0.1:8501
      ima web --host 0.0.0.0        # 内网其他设备可访问
      ima web -p 8080               # 指定端口
    """
    try:
        import uvicorn
    except ImportError:
        console.print("[red]缺少 Web 依赖[/red]")
        console.print("[dim]运行: pip install fastapi uvicorn python-multipart[/dim]")
        return

    _ensure_dirs()

    console.print(f"\n[bold green]🚀 IMA Web 后台启动[/bold green]\n")
    console.print(f"  地址: [cyan]http://{host}:{port}[/cyan]")
    console.print(f"  内网: [cyan]http://0.0.0.0:{port}[/cyan]" if host == "0.0.0.0" else "")
    console.print(f"  退出: [dim]Ctrl+C[/dim]\n")

    from web.app import create_app
    app = create_app()
    uvicorn.run(app, host=host, port=port, log_level="warning")


@cli.command(help="交互式对话模式（终端常驻 REPL，推荐）")
def chat() -> None:
    """进入交互式 REPL 模式。"""
    from repl import main as repl_main
    _ensure_dirs()
    repl_main()


@cli.command(help="入库文件或目录")
@click.argument("path", type=click.Path(exists=True))
@click.option("--verbose", "-v", is_flag=True, help="显示详细输出")
def ingest(path: str, verbose: bool) -> None:
    """入库文件或目录（递归）。"""
    target = Path(path).resolve()
    storage = Storage()

    files: list[Path] = []
    if target.is_file():
        files = [target]
    elif target.is_dir():
        # 递归扫描所有支持的文件
        for ext in SUPPORTED_EXTENSIONS:
            files.extend(target.rglob(f"*{ext}"))
        files = sorted(set(files))
    else:
        console.print(f"[red]无效路径: {target}[/red]")
        sys.exit(1)

    if not files:
        console.print("[yellow]未找到支持的文件[/yellow]")
        return

    console.print(f"\n[bold]开始入库[/bold] · 共 {len(files)} 个文件\n")

    success, fail, skip = 0, 0, 0
    for f in files:
        result = _ingest_one(storage, f, verbose=verbose)
        if result is True:
            success += 1
        else:
            skip += 1

    console.print(
        f"\n[bold]完成[/bold] · 成功 {success} / 跳过 {skip} / 共 {len(files)}\n"
    )


@cli.command(name="note", help="文本直入库（无需先存文件）")
@click.argument("text")
def cli_note(text: str) -> None:
    """将一段文本直接入库。"""
    from core.ingestion.quick import save_text
    from core.ingestion.parser import parse
    from core.ingestion.chunker import chunk_document

    storage = Storage()
    file_path = save_text(text)
    console.print(f"[dim]临时文件: {file_path.name}[/dim]")

    parsed = parse(file_path)
    chunks = chunk_document(parsed, chunk_size=settings.chunk_size, chunk_overlap=settings.chunk_overlap)
    record = storage.save_document(parsed, chunks, copy_file=False)
    console.print(f"[green]✓ 已入库[/green]  ID: {record.id[:8]}  标题: {record.title}")


@cli.command(name="clip", help="剪贴板入库（截图/文字/URL 自动识别）")
def cli_clip() -> None:
    """从剪贴板入库。"""
    from core.ingestion.quick import save_clipboard
    from core.ingestion.parser import parse
    from core.ingestion.chunker import chunk_document

    storage = Storage()
    file_path, content_type = save_clipboard()
    if file_path is None:
        console.print(f"[yellow]剪贴板内容无效: {content_type}[/yellow]")
        console.print("[dim]支持：截图（Cmd+Shift+4）、复制文字、复制 URL[/dim]")
        sys.exit(1)

    type_label = {"image": "📷 截图", "text": "📝 文本", "url": "🔗 网页"}.get(content_type, "内容")
    console.print(f"[dim]检测到: {type_label}[/dim]")

    parsed = parse(file_path)
    if not parsed.text.strip():
        console.print("[yellow]剪贴板内容为空[/yellow]")
        sys.exit(1)
    chunks = chunk_document(parsed, chunk_size=settings.chunk_size, chunk_overlap=settings.chunk_overlap)
    record = storage.save_document(parsed, chunks, copy_file=False)
    console.print(f"[green]✓ {type_label}已入库[/green]  ID: {record.id[:8]}")


@cli.command(name="url", help="网页入库（自动提取正文）")
@click.argument("url")
def cli_url(url: str) -> None:
    """抓取网页正文并入库。"""
    from core.ingestion.quick import save_url
    from core.ingestion.parser import parse
    from core.ingestion.chunker import chunk_document

    storage = Storage()
    if not (url.startswith("http://") or url.startswith("https://")):
        url = "https://" + url

    console.print(f"[dim]抓取: {url}[/dim]")
    file_path = save_url(url)
    console.print(f"[dim]已提取正文: {file_path.name}[/dim]")

    parsed = parse(file_path)
    chunks = chunk_document(parsed, chunk_size=settings.chunk_size, chunk_overlap=settings.chunk_overlap)
    record = storage.save_document(parsed, chunks, copy_file=False)
    console.print(f"[green]✓ 网页已入库[/green]  ID: {record.id[:8]}  标题: {record.title}")


@cli.command(name="list", help="列出所有文档")
@click.option("--limit", "-n", default=20, help="显示条数")
def list_docs(limit: int) -> None:
    """列出所有文档。"""
    storage = Storage()
    docs = storage.list_documents(limit=limit)
    if not docs:
        console.print("[yellow]知识库为空[/yellow]")
        return

    table = Table(title=f"知识库文档（共 {len(docs)} 条）", show_lines=False)
    table.add_column("ID", style="cyan", no_wrap=True, width=10)
    table.add_column("标题", style="white")
    table.add_column("类型", style="yellow")
    table.add_column("标签", style="magenta")
    table.add_column("分块", justify="right")
    table.add_column("Tokens", justify="right")
    table.add_column("入库时间", style="dim")

    for d in docs:
        table.add_row(
            d.id[:8],
            d.title,
            d.file_type,
            "、".join(d.tags) if d.tags else "[dim]-[/dim]",
            str(d.chunk_count),
            str(d.total_tokens),
            d.created_at[:19],
        )
    console.print(table)


@cli.command(help="BM25 智能搜索（中文分词 + 词频权重，可管道输出）")
@click.argument("query")
@click.option("--limit", "-n", default=10, help="返回条数")
@click.option("--tag", "-t", default=None, help="按标签筛选候选文档（精确匹配）")
@click.option("--raw", is_flag=True, help="使用旧版 LIKE 模糊匹配（不推荐）")
@click.option("--plain", is_flag=True, help="纯文本输出（便于管道传递给 ima ask）")
def search(query: str, limit: int, tag: Optional[str], raw: bool, plain: bool) -> None:
    """BM25 智能搜索。

    \b
    支持管道：
      ima search "骨灰" --plain | ima ask "这些内容的共同点"
    """
    storage = Storage()

    if raw:
        # 旧版 LIKE 搜索（保留兼容）
        chunks = storage.search_chunks(query, limit=limit)
        if not chunks:
            if not plain:
                console.print(f"[yellow]未找到包含 '{query}' 的内容[/yellow]")
            return
        if plain:
            # 纯文本输出（管道友好）
            for c in chunks:
                print(f"[{c.doc_id[:8]}] {c.content}")
            return
        console.print(f"\n[bold]找到 {len(chunks)} 条匹配（LIKE 模糊）[/bold]\n")
        for i, c in enumerate(chunks, 1):
            preview = c.content[:200].replace("\n", " ")
            console.print(
                f"[cyan]{i}.[/cyan] [dim][{c.doc_id[:8]} #{c.index}][/dim] "
                f"{preview}{'...' if len(c.content) > 200 else ''}"
            )
        console.print()
        return

    # BM25 检索（如有 tag 筛选，扩大候选数后过滤）
    fetch_k = limit * 5 if tag else limit
    results = storage.bm25_search(query, top_k=fetch_k)

    if tag:
        tagged_docs = storage.list_documents_by_tag(tag)
        allowed_ids = {d.id for d in tagged_docs}
        results = [r for r in results if r.doc_id in allowed_ids]
        if not results:
            if not plain:
                console.print(f"[yellow]未找到与 '{query}' 相关且带标签 '{tag}' 的内容[/yellow]")
                console.print(f"[dim]带此标签的文档共 {len(tagged_docs)} 个[/dim]")
            return
        results = results[:limit]
    else:
        if not results:
            if not plain:
                console.print(f"[yellow]未找到与 '{query}' 相关的内容[/yellow]")
            return
        results = results[:limit]

    if plain:
        # 纯文本输出（管道友好）
        for r in results:
            print(f"[{r.doc_title}] (相关度 {r.score:.2f})")
            print(r.content)
            print("---")
        return

    tag_hint = f" [dim]· 标签筛选: {tag}[/dim]" if tag else ""
    console.print(f"\n[bold]找到 {len(results)} 条相关结果[/bold] [dim](BM25 检索)[/dim]{tag_hint}\n")
    for i, r in enumerate(results, 1):
        preview = r.content[:200].replace("\n", " ")
        console.print(
            f"[cyan]{i}.[/cyan] "
            f"[green]({r.score:.2f})[/green] "
            f"[dim][{r.doc_title}][/dim]\n"
            f"   {preview}{'...' if len(r.content) > 200 else ''}\n"
        )


@cli.command(name="ask", help="CLI 一次性问答（基于宠物管理员 + 记忆 + 混合检索）")
@click.argument("question")
def cli_ask(question: str) -> None:
    """CLI 一次性问答（不进 REPL）。

    使用 PetAdministrator 编排：混合检索 + LLM 重排 + 记忆 + 人格。
    """
    from core.pet.administrator import PetAdministrator
    from core.memory.store import MemoryStore
    from core.retrieval.hybrid import HybridRetriever
    from core.retrieval.vector import VectorIndex
    from core.retrieval.rerank import Reranker
    from core.pet.storage import PetStorage
    from core.llm.client import get_llm

    storage = Storage()
    pet_storage = PetStorage()
    pet = pet_storage.load()
    if not pet:
        click.echo("请先运行 'ima' 并使用 /pet adopt 领养宠物")
        return

    memory = MemoryStore()
    vector_index = VectorIndex()
    hybrid = HybridRetriever(bm25_index=storage.bm25, vector_index=vector_index)
    llm = get_llm()
    reranker = Reranker(llm)

    admin = PetAdministrator(
        pet=pet, storage=storage, memory_store=memory,
        hybrid_retriever=hybrid, reranker=reranker, llm=llm,
    )
    result = admin.ask(question)
    click.echo(result.text)
    if result.citations:
        click.echo("\n引用溯源:")
        for c in result.citations:
            click.echo(f"  {c.marker} {c.title} §{c.paragraph_num}")


@cli.command(name="rebuild", help="重建索引（BM25 + 可选向量）")
@click.option("--vector", is_flag=True, help="同时重建向量索引")
def cli_rebuild(vector: bool) -> None:
    """重建索引。"""
    storage = Storage()
    # 重建 BM25
    console.print("[bold]重建 BM25 索引...[/bold]")
    count = storage.rebuild_bm25_index()
    info = storage.bm25.info()
    console.print(f"[green]✓ BM25 索引已重建[/green]")
    console.print(f"  索引分块: {info['chunks']}")
    console.print(f"  词汇量:   {info['vocabulary']}")
    console.print(f"  总 Token: {info['total_tokens']}")

    if vector:
        try:
            from core.retrieval.vector import VectorIndex
            vector_index = VectorIndex()
            if vector_index.is_available():
                console.print("[bold]构建向量索引...[/bold]")
                v_count = storage.rebuild_vector_index(vector_index)
                console.print(f"[green]✓ 向量索引已重建[/green]  [dim]({v_count} 块)[/dim]")
            else:
                console.print("[yellow]⚠ 向量索引不可用（依赖未安装或模型加载失败）[/yellow]")
                console.print("[dim]用 'bash install.sh --vector' 安装向量依赖[/dim]")
        except ImportError:
            console.print("[yellow]⚠ 向量依赖未安装，请用 'bash install.sh --vector' 安装[/yellow]")


@cli.command(name="memory", help="查看或管理记忆（格式/风格/主题/地区/任务）")
@click.argument("args", nargs=-1)
def cli_memory(args: tuple) -> None:
    """查看或管理记忆。

    \b
    用法：
      ima memory                      查看记忆概览
      ima memory clear                清空所有记忆
      ima memory format <值>          设置格式偏好（table/list/prose/auto/none）
      ima memory style <值>           设置风格偏好（auto/scholar/warrior/artisan）
      ima memory topic add <主题>     添加关注主题
      ima memory topic remove <主题>  移除关注主题
      ima memory topic clear          清空所有主题
      ima memory region add <地区>    添加关注地区
      ima memory region remove <地区> 移除关注地区
      ima memory region clear         清空所有地区
      ima memory task add <描述>      添加任务
      ima memory task done <id>       标记任务完成（id 可简写）
      ima memory task cancel <id>     取消任务
      ima memory tasks                列出所有任务
    """
    from core.memory.store import MemoryStore
    from core.memory.profile import ProfileManager
    from core.memory.tasks import TaskManager

    memory = MemoryStore()

    # 无参数 → 显示概览
    if not args:
        data = memory.load()
        profile = data.get("profile", {})
        tasks = data.get("tasks", [])
        click.echo("=== 记忆概览 ===")
        click.echo(f"偏好格式: {profile.get('preferred_format', '未设置')}")
        click.echo(f"偏好风格: {profile.get('preferred_style', 'auto')}")
        click.echo(f"关注主题: {', '.join(profile.get('focus_topics', [])) or '（无）'}")
        click.echo(f"关注地区: {', '.join(profile.get('focus_regions', [])) or '（无）'}")
        click.echo(f"交互次数: {profile.get('interaction_count', 0)}")
        active = [t for t in tasks if t.get("status") != "completed"]
        click.echo(f"活跃任务: {len(active)} 个")
        return

    sub = args[0].lower()

    # clear - 清空所有记忆
    if sub == "clear":
        memory.clear()
        click.echo("✓ 记忆已清空")
        return

    # format <值> - 设置格式偏好
    if sub == "format":
        if len(args) < 2:
            click.echo("用法: ima memory format <table|list|prose|auto|none>")
            return
        value = args[1].lower()
        # none/clear 表示清除偏好（设为空字符串）
        if value in ("none", "clear"):
            value = ""
        valid = {"", "table", "list", "prose", "auto"}
        if value not in valid:
            click.echo(f"无效的格式: {value}，可选: table / list / prose / auto / none")
            return
        pm = ProfileManager(memory)
        try:
            pm.update_format_preference(value)
            display = value if value else "（已清除）"
            click.echo(f"✓ 格式偏好已设置为: {display}")
        except ValueError as e:
            click.echo(f"✗ {e}")
        return

    # style <值> - 设置风格偏好
    if sub == "style":
        if len(args) < 2:
            click.echo("用法: ima memory style <auto|scholar|warrior|artisan>")
            return
        value = args[1].lower()
        valid = {"auto", "scholar", "warrior", "artisan"}
        if value not in valid:
            click.echo(f"无效的风格: {value}，可选: {', '.join(sorted(valid))}")
            return
        pm = ProfileManager(memory)
        try:
            pm.update_style_preference(value)
            click.echo(f"✓ 风格偏好已设置为: {value}")
        except ValueError as e:
            click.echo(f"✗ {e}")
        return

    # topic add/remove/clear <主题>
    if sub == "topic":
        if len(args) < 2:
            click.echo("用法: ima memory topic <add|remove|clear> [主题]")
            return
        action = args[1].lower()
        pm = ProfileManager(memory)
        if action == "clear":
            count = pm.clear_topics()
            click.echo(f"✓ 已清空 {count} 个主题")
        elif action in ("add", "remove") and len(args) >= 3:
            topic = " ".join(args[2:])
            if action == "add":
                try:
                    pm.add_topic(topic)
                    click.echo(f"✓ 已添加主题: {topic}")
                except ValueError as e:
                    click.echo(f"✗ {e}")
            else:
                if pm.remove_topic(topic):
                    click.echo(f"✓ 已移除主题: {topic}")
                else:
                    click.echo(f"✗ 未找到主题: {topic}")
        else:
            click.echo(f"用法: ima memory topic <add|remove|clear> [主题]")
        return

    # region add/remove/clear <地区>
    if sub == "region":
        if len(args) < 2:
            click.echo("用法: ima memory region <add|remove|clear> [地区]")
            return
        action = args[1].lower()
        pm = ProfileManager(memory)
        if action == "clear":
            count = pm.clear_regions()
            click.echo(f"✓ 已清空 {count} 个地区")
        elif action in ("add", "remove") and len(args) >= 3:
            region = " ".join(args[2:])
            if action == "add":
                try:
                    pm.add_region(region)
                    click.echo(f"✓ 已添加地区: {region}")
                except ValueError as e:
                    click.echo(f"✗ {e}")
            else:
                if pm.remove_region(region):
                    click.echo(f"✓ 已移除地区: {region}")
                else:
                    click.echo(f"✗ 未找到地区: {region}")
        else:
            click.echo(f"用法: ima memory region <add|remove|clear> [地区]")
        return

    # task add/done/cancel <id> / tasks
    if sub == "task" or sub == "tasks":
        tm = TaskManager(memory)
        if sub == "tasks" or (len(args) >= 2 and args[1].lower() == "list"):
            tasks = tm.get_all_tasks()
            if not tasks:
                click.echo("（无任务）")
                return
            click.echo(f"=== 任务列表（{len(tasks)} 个）===")
            for t in tasks:
                status_icon = {"pending": "○", "in_progress": "◐", "completed": "●", "cancelled": "✗"}
                icon = status_icon.get(t.status, "?")
                click.echo(f"  {icon} [{t.status}] {t.id[:12]}  {t.description}")
            return
        if len(args) < 2:
            click.echo("用法: ima memory task <add|done|cancel> [描述|id]")
            return
        action = args[1].lower()
        if action == "add" and len(args) >= 3:
            desc = " ".join(args[2:])
            task_id = tm.add_task(desc)
            click.echo(f"✓ 已添加任务: {desc} (id: {task_id[:12]})")
        elif action in ("done", "cancel") and len(args) >= 3:
            task_id_prefix = args[2]
            # 前缀匹配
            all_tasks = tm.get_all_tasks()
            matched = [t for t in all_tasks if t.id.startswith(task_id_prefix)]
            if not matched:
                click.echo(f"✗ 未找到任务: {task_id_prefix}")
                return
            if len(matched) > 1:
                click.echo(f"✗ ID 前缀匹配多个任务，请提供更完整的 ID")
                return
            status = "completed" if action == "done" else "cancelled"
            if tm.update_task(matched[0].id, status):
                click.echo(f"✓ 任务已标记为: {status}")
            else:
                click.echo(f"✗ 任务状态更新失败")
        else:
            click.echo(f"用法: ima memory task <add|done|cancel> [描述|id]")
        return

    click.echo(f"未知子命令: {sub}")
    click.echo("可用: clear / format / style / topic / region / task / tasks")


@cli.command(help="监控文件夹变化自动入库（适合同步盘场景）")
@click.argument("path", type=click.Path(exists=True))
@click.option("--interval", "-i", default=10, type=int, help="扫描间隔（秒，默认 10）")
@click.option("--once", is_flag=True, help="只扫描一次，不持续监控")
def watch(path: str, interval: int, once: bool) -> None:
    """监控文件夹，新文件自动入库。

    \b
    示例：
      ima watch ~/Documents/政策文件          # 每 10 秒扫描一次
      ima watch ~/Documents/政策文件 -i 30    # 30 秒扫描一次
      ima watch ~/Documents/政策文件 --once   # 只扫描一次
    """
    import time
    target = Path(path).resolve()
    if not target.is_dir():
        console.print(f"[red]路径不是文件夹: {target}[/red]")
        return

    console.print(f"[bold green]📡 文件监控启动[/bold green]")
    console.print(f"  目录: [cyan]{target}[/cyan]")
    console.print(f"  间隔: {interval}秒" + ("（单次模式）" if once else "（持续模式，Ctrl+C 退出）"))
    console.print(f"  支持格式: {', '.join(SUPPORTED_EXTENSIONS)}\n")

    storage = Storage()
    seen = set()  # 已处理文件路径

    def scan_once():
        """扫描一次目录。"""
        files = []
        for ext in SUPPORTED_EXTENSIONS:
            files.extend(target.rglob(f"*{ext}"))
        files = sorted(set(files))

        new_files = [f for f in files if str(f) not in seen]
        if not new_files:
            return 0

        console.print(f"[dim]{time.strftime('%H:%M:%S')} 发现 {len(new_files)} 个新文件[/dim]")
        success = 0
        for f in new_files:
            seen.add(str(f))
            if _ingest_one(storage, f, verbose=False):
                success += 1
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
        console.print(f"\n[yellow]停止监控[/yellow]  [dim]已处理 {len(seen)} 个文件[/dim]")


@cli.command(help="生成文档分析报告（Markdown）")
@click.argument("doc_id")
@click.option("--output", "-o", default=None, help="输出路径（默认 storage/reports/<标题>.md）")
def report(doc_id: str, output: Optional[str]) -> None:
    """基于文档内容 + LLM 生成结构化分析报告。

    \b
    示例：
      ima report 24ea6ac3                # 生成报告
      ima report 24ea6ac3 -o ~/报告.md   # 指定输出路径
    """
    from core.llm.client import LLMError
    try:
        from core.report.generator import ReportGenerator
    except ImportError as e:
        console.print(f"[red]模块加载失败: {e}[/red]")
        return

    try:
        rg = ReportGenerator()
    except LLMError as e:
        console.print(f"[red]LLM 未配置: {e}[/red]")
        return

    from pathlib import Path as _Path
    out_path = _Path(output) if output else None

    console.print(f"\n[bold]📋 生成报告...[/bold] [dim]ID: {doc_id}[/dim]")
    try:
        path = rg.generate(doc_id, output_path=out_path)
        console.print(f"\n[green]✓ 报告已生成[/green] → [cyan]{path}[/cyan]")
        console.print(f"  [dim]打开: open '{path}'[/dim]\n")
    except FileNotFoundError as e:
        console.print(f"[red]{e}[/red]")
    except Exception as e:
        err_msg = str(e).replace("[", "\\[")
        console.print(f"[red]生成失败:[/red] {type(e).__name__}: {err_msg}")


@cli.command(help="数据表智能分析（Excel/CSV/TSV/JSON）")
@click.argument("path", type=click.Path(exists=True))
@click.option("--sheet", "-s", default=None, help="Excel sheet 名（默认第一个）")
@click.option("--sheets", "list_sheets", is_flag=True, help="仅列出 Excel 的所有 sheet")
def analyze(path: str, sheet: Optional[str], list_sheets: bool) -> None:
    """数据表智能分析：统计 + 字符图 + AI 洞察。

    \b
    示例：
      ima analyze data.xlsx              # 一键分析
      ima analyze data.xlsx --sheets     # 列出所有 sheet
      ima analyze data.xlsx -s 月度数据  # 指定 sheet
      ima analyze data.csv               # 分析 CSV
    """
    from core.llm.client import LLMError
    try:
        from core.analyze.analyzer import DataAnalyzer
    except ImportError as e:
        console.print(f"[red]模块加载失败: {e}[/red]")
        console.print("[dim]请确认 pandas 已安装: pip install pandas openpyxl[/dim]")
        return

    target = Path(path).resolve()

    # 仅列出 sheet
    if list_sheets:
        try:
            az = DataAnalyzer()
        except LLMError as e:
            console.print(f"[red]{e}[/red]")
            return
        sheets = az.list_sheets(target)
        if not sheets:
            console.print("[yellow]该文件不是 Excel，无 sheet[/yellow]")
            return
        console.print(f"[bold]Excel「{target.name}」的 sheets:[/bold]")
        for i, s in enumerate(sheets, 1):
            console.print(f"  [cyan]{i}.[/cyan] {s}")
        return

    # 执行分析
    try:
        az = DataAnalyzer()
    except LLMError as e:
        console.print(f"[red]LLM 未配置: {e}[/red]")
        console.print("[dim]请在 .env 中设置 AGNES_API_KEY[/dim]")
        return

    console.print(f"\n[bold]📊 分析中[/bold] [dim]{target.name}[/dim]...")
    try:
        result = az.analyze(target, sheet_name=sheet)
        az.render(result)
        console.print(
            "\n[dim]提示：进 REPL 用 /analyze 还可以继续追问（如「按月份汇总」）[/dim]\n"
        )
    except FileNotFoundError as e:
        console.print(f"[red]{e}[/red]")
    except ValueError as e:
        console.print(f"[red]格式不支持:[/red] {e}")
    except Exception as e:
        err_msg = str(e).replace("[", "\\[")
        console.print(f"[red]分析失败:[/red] {type(e).__name__}: {err_msg}")


@cli.command(help="查看文档详情")
@click.argument("doc_id")
def show(doc_id: str) -> None:
    """查看文档详情和分块。"""
    storage = Storage()
    # 支持简写 ID
    if len(doc_id) < 32:
        docs = storage.list_documents(limit=1000)
        matched = [d for d in docs if d.id.startswith(doc_id)]
        if not matched:
            console.print(f"[red]未找到文档: {doc_id}[/red]")
            return
        doc_id = matched[0].id

    doc = storage.get_document(doc_id)
    if not doc:
        console.print(f"[red]未找到文档: {doc_id}[/red]")
        return

    console.print(f"\n[bold cyan]{doc.title}[/bold cyan]")
    console.print(f"  ID:       {doc.id}")
    console.print(f"  文件:     {doc.file_name}")
    console.print(f"  类型:     {doc.file_type}")
    console.print(f"  大小:     {doc.file_size} bytes")
    console.print(f"  语言:     {doc.language}")
    console.print(f"  分块:     {doc.chunk_count}")
    console.print(f"  Tokens:   {doc.total_tokens}")
    console.print(f"  入库时间: {doc.created_at}")
    console.print(f"  原路径:   {doc.file_path}")
    if doc.tags:
        console.print(f"  标签:     [magenta]{'、'.join(doc.tags)}[/magenta]")
    else:
        console.print(f"  标签:     [dim]（无，可用 ima retag -d {doc.id[:8]} 生成）[/dim]")
    if doc.meta:
        console.print(f"  元信息:   {doc.meta}")
    console.print()

    chunks = storage.get_chunks(doc_id)
    for c in chunks[:5]:  # 只显示前 5 块
        console.print(f"[dim]--- Chunk #{c.index} ({c.token_count} tokens) ---[/dim]")
        console.print(c.content[:300] + ("..." if len(c.content) > 300 else ""))
        console.print()
    if len(chunks) > 5:
        console.print(f"[dim]... 还有 {len(chunks) - 5} 块未显示[/dim]\n")


@cli.command(help="知识库统计")
def stats() -> None:
    """显示知识库统计信息。"""
    storage = Storage()
    s = storage.stats()

    console.print("\n[bold]📊 知识库统计[/bold]\n")
    console.print(f"  文档总数:   [cyan]{s['documents']}[/cyan]")
    console.print(f"  分块总数:   [cyan]{s['chunks']}[/cyan]")
    console.print(f"  总 Tokens:  [cyan]{s['total_tokens']:,}[/cyan]")
    console.print(f"  原文件大小: [cyan]{s['total_size_mb']} MB[/cyan]")

    if s["by_type"]:
        console.print("\n  [bold]按类型分布:[/bold]")
        for ftype, cnt in s["by_type"].items():
            console.print(f"    {ftype or '(无)':12s} {cnt}")

    # 标签统计
    tags = storage.list_all_tags()
    if tags:
        console.print(f"\n  [bold]标签统计[/bold] [dim]（共 {len(tags)} 个标签）[/dim]")
        # 显示前 10 个最常用标签
        for tag, cnt in list(tags.items())[:10]:
            console.print(f"    [magenta]{tag}[/magenta] [dim]×{cnt}[/dim]")
        if len(tags) > 10:
            console.print(f"    [dim]... 还有 {len(tags) - 10} 个标签[/dim]")
    console.print()


@cli.command(help="重新生成/补全文档标签（调用 LLM）")
@click.option("--doc-id", "-d", default=None, help="只给指定文档打标签（支持 ID 前缀）")
@click.option("--force", "-f", is_flag=True, help="强制重新生成所有标签（包括已有标签的）")
@click.option("--limit", "-n", default=None, type=int, help="最多处理多少个文档")
def retag(doc_id: Optional[str], force: bool, limit: Optional[int]) -> None:
    """给已入库文档批量补标签。"""
    from core.classify.tagger import Tagger
    from core.llm.client import LLMError

    if not settings.has_llm():
        console.print("[red]未配置 AGNES_API_KEY，无法调用 LLM 打标签[/red]")
        console.print("[dim]请在 .env 中设置 AGNES_API_KEY[/dim]")
        return

    storage = Storage()

    # 选目标文档
    if doc_id:
        # 支持 ID 前缀
        if len(doc_id) < 32:
            all_docs = storage.list_documents(limit=10000)
            target_docs = [d for d in all_docs if d.id.startswith(doc_id)]
        else:
            d = storage.get_document(doc_id)
            target_docs = [d] if d else []
        if not target_docs:
            console.print(f"[red]未找到文档: {doc_id}[/red]")
            return
    else:
        all_docs = storage.list_documents(limit=10000)
        if force:
            target_docs = all_docs
        else:
            # 只处理没有标签的
            target_docs = [d for d in all_docs if not d.tags]
        if limit:
            target_docs = target_docs[:limit]

    if not target_docs:
        console.print("[yellow]没有需要打标签的文档[/yellow]")
        if not force and not doc_id:
            console.print("[dim]提示: 用 --force 重新生成所有标签[/dim]")
        return

    console.print(f"\n[bold]开始打标签[/bold] · 共 {len(target_docs)} 个文档\n")

    try:
        tagger = Tagger()
    except LLMError as e:
        console.print(f"[red]LLM 初始化失败:[/red] {e}")
        return

    success, fail = 0, 0
    for i, doc in enumerate(target_docs, 1):
        # 从 chunks 拼出内容预览（按顺序）
        chunks = storage.get_chunks(doc.id)
        content_preview = "\n".join(c.content for c in chunks)

        console.print(f"[{i}/{len(target_docs)}] [cyan]{doc.title[:50]}[/cyan]")

        try:
            tags = tagger.generate_tags(
                title=doc.title,
                file_type=doc.file_type,
                content=content_preview,
            )
            if tags:
                storage.update_document_tags(doc.id, tags)
                console.print(f"  [green]✓[/green] [dim]{', '.join(tags)}[/dim]")
                success += 1
            else:
                console.print("  [yellow]未生成标签（LLM 返回空）[/yellow]")
                fail += 1
        except Exception as e:
            console.print(f"  [red]失败: {type(e).__name__}: {e}[/red]")
            fail += 1

    console.print(f"\n[bold]完成[/bold] · 成功 {success} / 失败 {fail}\n")


# ============================================================
# 知识图谱命令组
# ============================================================

@cli.group(help="知识图谱管理（构建/查看/导出）")
def graph() -> None:
    """知识图谱子命令组。"""
    pass


@graph.command(help="从已入库文档构建知识图谱（调用 LLM 抽取实体关系）")
@click.option("--doc-id", "-d", default=None, help="只处理指定文档（支持 ID 前缀）")
@click.option("--force", "-f", is_flag=True, help="强制重建（清空已有图谱）")
@click.option("--limit", "-n", default=None, type=int, help="最多处理多少个文档")
def build(doc_id: Optional[str], force: bool, limit: Optional[int]) -> None:
    """构建知识图谱。"""
    from core.graph.extractor import GraphExtractor
    from core.graph.store import GraphStore
    from core.llm.client import LLMError

    if not settings.has_llm():
        console.print("[red]未配置 AGNES_API_KEY，无法调用 LLM 抽取[/red]")
        return

    storage = Storage()
    graph_store = GraphStore()

    if force:
        graph_store.clear()
        console.print("[yellow]已清空旧图谱[/yellow]")

    # 选目标文档
    all_docs = storage.list_documents(limit=10000)
    if doc_id:
        target_docs = [d for d in all_docs if d.id.startswith(doc_id)]
        if not target_docs:
            console.print(f"[red]未找到文档: {doc_id}[/red]")
            return
    else:
        # 跳过已抽取的（除非 --force）
        existing_doc_ids = set()
        for n, d in graph_store.graph.nodes(data=True):
            existing_doc_ids.update(d.get("doc_ids", []))
        target_docs = [d for d in all_docs if d.id not in existing_doc_ids]
        if limit:
            target_docs = target_docs[:limit]

    if not target_docs:
        console.print("[yellow]没有需要抽取的文档[/yellow]")
        console.print("[dim]提示: 用 --force 重建整个图谱[/dim]")
        return

    console.print(f"\n[bold]开始构建知识图谱[/bold] · 共 {len(target_docs)} 个文档\n")

    try:
        extractor = GraphExtractor()
    except LLMError as e:
        console.print(f"[red]LLM 初始化失败:[/red] {e}")
        return

    success, fail = 0, 0
    for i, doc in enumerate(target_docs, 1):
        # 从 chunks 拼出内容
        chunks = storage.get_chunks(doc.id)
        content = "\n".join(c.content for c in chunks)

        console.print(f"[{i}/{len(target_docs)}] [cyan]{doc.title[:50]}[/cyan]")

        try:
            result = extractor.extract_from_document(
                doc_id=doc.id,
                doc_title=doc.title,
                content=content,
            )
            if result.entities:
                graph_store.add_extraction(result)
                graph_store.save()
                console.print(
                    f"  [green]✓[/green] "
                    f"{len(result.entities)} 实体 · {len(result.relations)} 关系"
                )
                success += 1
            else:
                console.print("  [yellow]未抽取到实体[/yellow]")
                fail += 1
        except Exception as e:
            console.print(f"  [red]失败: {type(e).__name__}: {e}[/red]")
            fail += 1

    s = graph_store.stats()
    console.print(
        f"\n[bold]完成[/bold] · 抽取 {success}/{len(target_docs)} 文档 · "
        f"图谱: {s['nodes']} 节点 / {s['edges']} 边\n"
    )


@graph.command(help="查看图谱统计和节点列表")
@click.option("--type", "-t", default=None, help="按节点类型筛选（document/region/agency/topic）")
@click.option("--limit", "-n", default=20, help="显示条数")
def stats(type: Optional[str], limit: int) -> None:
    """查看图谱统计。"""
    from core.graph.store import GraphStore

    gs = GraphStore()
    s = gs.stats()

    if s["nodes"] == 0:
        console.print("[yellow]图谱为空[/yellow]")
        console.print("[dim]提示: 运行 ima graph build 构建图谱[/dim]")
        return

    console.print("\n[bold]📊 知识图谱统计[/bold]\n")
    console.print(f"  节点总数:  [cyan]{s['nodes']}[/cyan]")
    console.print(f"  边总数:    [cyan]{s['edges']}[/cyan]")

    if s["nodes_by_type"]:
        console.print("\n  [bold]按节点类型:[/bold]")
        type_names = {"document": "政策文档", "region": "地区", "agency": "机构", "topic": "主题"}
        for ntype, cnt in sorted(s["nodes_by_type"].items(), key=lambda x: -x[1]):
            name = type_names.get(ntype, ntype)
            console.print(f"    {name:8s} {cnt}")

    if s["edges_by_relation"]:
        console.print("\n  [bold]按关系类型:[/bold]")
        rel_names = {"published_in": "发布于", "published_by": "发布机构", "covers_topic": "涉及主题"}
        for rel, cnt in sorted(s["edges_by_relation"].items(), key=lambda x: -x[1]):
            name = rel_names.get(rel, rel)
            console.print(f"    {name:8s} {cnt}")

    # 节点列表
    nodes = gs.list_nodes(node_type=type)
    if nodes:
        console.print(f"\n  [bold]节点列表[/bold] [dim]（前 {min(limit, len(nodes))} 个，按连接数排序）[/dim]")
        table = Table(show_lines=False)
        table.add_column("名称", style="white")
        table.add_column("类型", style="cyan")
        table.add_column("连接数", justify="right", style="yellow")
        table.add_column("关联文档", justify="right", style="magenta")
        type_names = {"document": "文档", "region": "地区", "agency": "机构", "topic": "主题"}
        for n in nodes[:limit]:
            table.add_row(
                n["label"],
                type_names.get(n["type"], n["type"]),
                str(n["degree"]),
                str(n["doc_count"]),
            )
        console.print(table)
    console.print()


@graph.command(help="查询节点的邻居关系")
@click.argument("name")
def neighbors(name: str) -> None:
    """查询某节点的邻居。"""
    from core.graph.store import GraphStore

    gs = GraphStore()
    if name not in gs.graph:
        # 模糊匹配
        matches = gs.search_nodes(name)
        if not matches:
            console.print(f"[red]未找到节点: {name}[/red]")
            return
        console.print(f"[yellow]找到 {len(matches)} 个匹配节点:[/yellow]")
        for m in matches[:5]:
            console.print(f"  [cyan]{m['label']}[/cyan] [dim]({m['type']}, 连接 {m['degree']})[/dim]")
        console.print(f"\n[dim]用确切名称重试: ima graph neighbors \"{matches[0]['label']}\"[/dim]")
        return

    neighbors = gs.neighbors(name)
    node_data = gs.graph.nodes[name]
    type_names = {"document": "政策文档", "region": "地区", "agency": "机构", "topic": "主题"}

    console.print(f"\n[bold cyan]{name}[/bold cyan] [dim]({type_names.get(node_data.get('type', ''), '')})[/dim]")
    console.print(f"  关联文档: {node_data.get('doc_count', 0)} · 连接数: {len(neighbors)}\n")

    if neighbors:
        table = Table(show_lines=False)
        table.add_column("邻居节点", style="white")
        table.add_column("类型", style="cyan")
        table.add_column("关系", style="yellow")
        for nb in neighbors:
            table.add_row(
                nb["node"],
                type_names.get(nb["type"], nb["type"]),
                nb["relation_label"],
            )
        console.print(table)
    console.print()


@graph.command(help="导出交互式 HTML 可视化（浏览器打开）")
@click.option("--output", "-o", default=None, help="输出路径（默认 storage/graph.html）")
def export(output: Optional[str]) -> None:
    """导出 HTML 可视化。"""
    import webbrowser
    from core.graph.store import GraphStore
    from core.graph.visualizer import generate_html

    gs = GraphStore()
    if gs.graph.number_of_nodes() == 0:
        console.print("[yellow]图谱为空[/yellow]")
        console.print("[dim]提示: 运行 ima graph build 构建图谱[/dim]")
        return

    output_path = Path(output) if output else None
    html_path = generate_html(gs, output_path=output_path)
    s = gs.stats()
    console.print(f"\n[green]✓ 已导出知识图谱[/green]")
    console.print(f"  文件: {html_path}")
    console.print(f"  节点: {s['nodes']} · 边: {s['edges']}")

    # 自动打开浏览器
    file_url = html_path.as_uri()
    webbrowser.open(file_url)
    console.print(f"  [green]✓ 已在浏览器中打开[/green]\n")


@graph.command(help="清空图谱")
@click.confirmation_option(prompt="确定清空知识图谱？")
def clear() -> None:
    """清空图谱。"""
    from core.graph.store import GraphStore
    gs = GraphStore()
    gs.clear()
    console.print("[green]✓ 已清空知识图谱[/green]")


@cli.command(help="删除文档")
@click.argument("doc_id")
@click.confirmation_option(prompt="确定删除？")
def delete(doc_id: str) -> None:
    """删除文档。"""
    storage = Storage()
    if len(doc_id) < 32:
        docs = storage.list_documents(limit=1000)
        matched = [d for d in docs if d.id.startswith(doc_id)]
        if not matched:
            console.print(f"[red]未找到文档: {doc_id}[/red]")
            return
        doc_id = matched[0].id

    if storage.delete_document(doc_id):
        console.print(f"[green]✓ 已删除: {doc_id}[/green]")
    else:
        console.print(f"[red]删除失败: {doc_id}[/red]")


@cli.command(name="sync")
@click.argument("dir_path")
def cli_sync(dir_path: str) -> None:
    """增量同步目录（自动检测新增/修改/删除）。"""
    from core.sync.tracker import FileTracker

    storage = Storage()
    tracker = FileTracker(storage_path=settings.storage_path)

    console.print(f"[bold]扫描目录:[/bold] {dir_path}")
    files = tracker.scan_directory(dir_path)
    console.print(f"发现 {len(files)} 个支持的文件")

    def on_progress(action: str, fp: str) -> None:
        if action == "added":
            console.print(f"  [green]✓ 新增[/green]: {Path(fp).name}")
        elif action == "updated":
            console.print(f"  [yellow]↻ 更新[/yellow]: {Path(fp).name}")
        elif action == "deleted":
            console.print(f"  [red]✗ 删除[/red]: {Path(fp).name}")

    result = tracker.sync_directory(dir_path, storage, on_progress=on_progress)

    console.print(f"\n[bold]同步完成[/bold]")
    console.print(f"  新增: {len(result.added)}")
    console.print(f"  更新: {len(result.updated)}")
    console.print(f"  删除: {len(result.deleted)}")
    console.print(f"  跳过: {len(result.skipped)}")
    if result.errors:
        console.print(f"  [red]错误: {len(result.errors)}[/red]")
        for e in result.errors:
            console.print(f"    {e}")


@cli.command(name="health")
def cli_health() -> None:
    """知识库数据质量报告。"""
    from core.sync.checker import QualityChecker

    storage = Storage()
    checker = QualityChecker()

    docs = storage.list_documents(limit=1000)
    all_results = []
    for doc in docs:
        chunks = storage.get_chunks(doc.id)
        results = checker.check_document(chunks)
        all_results.extend(results)

    report = checker.generate_report(all_results)

    console.print(f"\n[bold]📊 知识库健康报告[/bold]\n")
    console.print(f"  文档总数: {len(docs)}")
    console.print(f"  Chunk 总数: {report.total_chunks}")
    console.print(f"  ✓ 正常: {report.normal} ({report.normal_pct}%)")
    console.print(f"  ⚠ 低质量: {report.low_quality}")
    if report.ocr_poor:
        console.print(f"  ⚠ OCR 乱码: {report.ocr_poor}")
    console.print(f"\n  [bold]健康分: {report.health_score}/100[/bold]")

    if report.issues_detail:
        console.print(f"\n  问题明细:")
        for issue, count in sorted(report.issues_detail.items(), key=lambda x: -x[1]):
            console.print(f"    {issue}: {count}")


@cli.command(name="dedup")
@click.option("--dry-run", is_flag=True, help="只报告不执行")
def cli_dedup(dry_run: bool) -> None:
    """扫描近似重复 chunk。"""
    from core.sync.dedup import DedupScanner

    storage = Storage()
    scanner = DedupScanner(threshold=0.85)

    docs = storage.list_documents(limit=1000)
    for doc in docs:
        chunks = storage.get_chunks(doc.id)
        for c in chunks:
            scanner.add_chunk(c.id, c.doc_id, c.content)

    console.print(f"\n[bold]扫描近似重复...[/bold] ({len(scanner._chunks)} 个 chunk)")
    results = scanner.scan()
    duplicates = [r for r in results if r.is_duplicate]

    if not duplicates:
        console.print("  [green]✓ 未发现近似重复[/green]")
        return

    console.print(f"  发现 {len(duplicates)} 个近似重复 chunk:\n")
    for d in duplicates:
        console.print(f"    {d.chunk_id} ← 重复于 {d.duplicate_of}")
        console.print(f"      相似度: {d.similarity:.1%}  汉明距离: {d.hamming_distance}")

    if not dry_run:
        console.print(f"\n  [dim]提示: 使用 --dry-run 只查看不操作（当前版本仅报告）[/dim]")


if __name__ == "__main__":
    cli()

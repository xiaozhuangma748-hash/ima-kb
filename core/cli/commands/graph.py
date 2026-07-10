"""知识图谱 Mixin。

从 repl.py 第 3486-3786 行迁移，包含：
- ``_cmd_graph`` 图谱子命令入口
- ``_graph_stats`` 图谱统计
- ``_graph_build`` 构建图谱
- ``_graph_neighbors`` 查询节点邻居
- ``_graph_export`` 导出 HTML 可视化
- ``_graph_clear`` 清空图谱
- ``_graph_delete_node`` 删除节点
- ``_graph_rename_node`` 重命名节点
"""
from __future__ import annotations

from rich.table import Table
from rich.prompt import Prompt

from core.cli.constants import console
from core.cli.welcome import _record_activity


class GraphMixin:
    """知识图谱相关命令。"""

    def _cmd_graph(self, arg: str) -> None:
        """知识图谱子命令：/graph <build|stats|neighbors|export|clear> [参数]"""
        from core.graph.store import GraphStore

        if not arg:
            console.print("[yellow]用法:[/yellow]")
            console.print("  [cyan]/graph stats[/cyan]              图谱统计")
            console.print("  [cyan]/graph build[/cyan] [--force]    构建图谱")
            console.print("  [cyan]/graph neighbors <名称>[/cyan]   查询邻居")
            console.print("  [cyan]/graph export[/cyan]             导出 HTML")
            console.print("  [cyan]/graph clear[/cyan]              清空图谱")
            return

        # 拆出子命令和参数
        parts = arg.split(maxsplit=1)
        sub = parts[0].lower()
        sub_arg = parts[1].strip() if len(parts) > 1 else ""

        gs = GraphStore()

        if sub == "stats":
            self._graph_stats(gs)
        elif sub == "build":
            self._graph_build(gs, sub_arg)
        elif sub in ("neighbor", "neighbors", "nb"):
            if not sub_arg:
                console.print("[yellow]用法: /graph neighbors <节点名称>[/yellow]")
                return
            self._graph_neighbors(gs, sub_arg)
        elif sub == "export":
            self._graph_export(gs)
        elif sub == "clear":
            self._graph_clear(gs)
        elif sub in ("delete", "del", "rm"):
            self._graph_delete_node(gs, sub_arg)
        elif sub in ("rename", "mv"):
            self._graph_rename_node(gs, sub_arg)
        else:
            console.print(f"[red]未知子命令:[/red] {sub}")
            console.print("[dim]可用: stats / build / neighbors / export / clear / delete / rename[/dim]")

    def _graph_stats(self, gs) -> None:
        """图谱统计。"""
        s = gs.stats()
        if s["nodes"] == 0:
            console.print("[yellow]图谱为空[/yellow]  [dim]用 /graph build 构建[/dim]")
            return

        console.print("\n[bold]知识图谱统计[/bold]\n")
        console.print(f"  节点总数:  [cyan]{s['nodes']}[/cyan]")
        console.print(f"  边总数:    [cyan]{s['edges']}[/cyan]")

        type_names = {"document": "政策文档", "region": "地区", "agency": "机构", "topic": "主题"}
        if s["nodes_by_type"]:
            console.print("\n  [bold]按节点类型:[/bold]")
            for ntype, cnt in sorted(s["nodes_by_type"].items(), key=lambda x: -x[1]):
                console.print(f"    {type_names.get(ntype, ntype):8s} {cnt}")

        rel_names = {"published_in": "发布于", "published_by": "发布机构", "covers_topic": "涉及主题"}
        if s["edges_by_relation"]:
            console.print("\n  [bold]按关系类型:[/bold]")
            for rel, cnt in sorted(s["edges_by_relation"].items(), key=lambda x: -x[1]):
                console.print(f"    {rel_names.get(rel, rel):8s} {cnt}")

        # 节点列表（前 15 个）
        nodes = gs.list_nodes()
        if nodes:
            console.print(f"\n  [bold]节点列表[/bold] [dim]（前 15 个，按连接数排序）[/dim]")
            table = Table(show_lines=False)
            table.add_column("名称", style="white")
            table.add_column("类型", style="cyan", width=8)
            table.add_column("连接数", justify="right", style="yellow")
            table.add_column("关联文档", justify="right", style="magenta")
            for n in nodes[:15]:
                table.add_row(
                    n["label"],
                    type_names.get(n["type"], n["type"]),
                    str(n["degree"]),
                    str(n["doc_count"]),
                )
            console.print(table)
        console.print()

    def _graph_build(self, gs, arg: str) -> None:
        """构建图谱：/graph build [--force] [-d ID] [-n N]"""
        from core.graph.extractor import GraphExtractor
        from core.llm.client import LLMError

        if not self.llm_available:
            console.print("[red]LLM 未配置，无法抽取实体关系[/red]")
            return

        # 简单解析参数
        force = "--force" in arg or "-f" in arg
        doc_id_filter = None
        limit = None
        # 支持 -d ID / -n N
        toks = arg.split()
        i = 0
        while i < len(toks):
            if toks[i] in ("-d", "--doc-id") and i + 1 < len(toks):
                doc_id_filter = toks[i + 1]
                i += 2
            elif toks[i] in ("-n", "--limit") and i + 1 < len(toks):
                try:
                    limit = int(toks[i + 1])
                except ValueError:
                    pass
                i += 2
            else:
                i += 1

        if force:
            gs.clear()
            console.print("[yellow]已清空旧图谱[/yellow]")

        # 选目标文档
        all_docs = self.storage.list_documents(limit=10000)
        if doc_id_filter:
            target_docs = [d for d in all_docs if d.id.startswith(doc_id_filter)]
            if not target_docs:
                console.print(f"[red]未找到文档: {doc_id_filter}[/red]")
                return
        else:
            # 跳过已抽取的
            existing_doc_ids = set()
            for n, d in gs.graph.nodes(data=True):
                existing_doc_ids.update(d.get("doc_ids", []))
            target_docs = [d for d in all_docs if d.id not in existing_doc_ids]
            if limit:
                target_docs = target_docs[:limit]

        if not target_docs:
            console.print("[yellow]没有需要抽取的文档[/yellow]  [dim]用 --force 重建[/dim]")
            return

        console.print(f"\n[bold]开始构建图谱[/bold] · 共 {len(target_docs)} 个文档\n")

        try:
            extractor = GraphExtractor()
        except LLMError as e:
            console.print(f"[red]LLM 初始化失败:[/red] {e}")
            return

        success, fail = 0, 0
        for i, doc in enumerate(target_docs, 1):
            chunks = self.storage.get_chunks(doc.id)
            content = "\n".join(c.content for c in chunks)
            title_display = doc.title[:50]
            content_preview = content.strip()[:200]

            # 预检：内容过短或无实质信息的文档，跳过 LLM 调用
            if len(content_preview) < 50:
                console.print(f"[{i}/{len(target_docs)}] [cyan]{title_display}[/cyan]")
                console.print(f"  [dim]跳过（内容过短 {len(content)} 字）[/dim]")
                fail += 1
                continue

            console.print(f"[{i}/{len(target_docs)}] [cyan]{title_display}[/cyan]")
            try:
                result = extractor.extract_from_document(
                    doc_id=doc.id, doc_title=doc.title, content=content,
                )
                if result.entities:
                    gs.add_extraction(result)
                    gs.save()
                    console.print(
                        f"  [green]✓[/green] {len(result.entities)} 实体 · {len(result.relations)} 关系"
                    )
                    success += 1
                else:
                    console.print("  [dim]该文档无可抽取的实体（内容可能非政策/无实质信息）[/dim]")
                    fail += 1
            except Exception as e:
                err_msg = str(e).replace("[", "\\[")
                console.print(f"  [red]失败: {type(e).__name__}: {err_msg}[/red]")
                fail += 1

        s = gs.stats()
        console.print(
            f"\n[bold]完成[/bold] · 抽取 {success}/{len(target_docs)} · "
            f"图谱 {s['nodes']} 节点 / {s['edges']} 边\n"
        )
        _record_activity("graph", f"{s['nodes']}节点/{s['edges']}边")
        # 宠物经验埋点：graph_build 行为
        if success > 0:
            self._pet_gain_exp(30, "graph_build")

    def _graph_neighbors(self, gs, name: str) -> None:
        """查询节点邻居：/graph neighbors <名称>"""
        if name not in gs.graph:
            # 模糊匹配
            matches = gs.search_nodes(name)
            if not matches:
                console.print(f"[red]未找到节点: {name}[/red]")
                return
            console.print(f"[yellow]找到 {len(matches)} 个匹配:[/yellow]")
            for m in matches[:5]:
                console.print(f"  [cyan]{m['label']}[/cyan] [dim]({m['type']}, 连接 {m['degree']})[/dim]")
            console.print(f"\n[dim]重试: /graph neighbors \"{matches[0]['label']}\"[/dim]")
            return

        neighbors = gs.neighbors(name)
        node_data = gs.graph.nodes[name]
        type_names = {"document": "政策文档", "region": "地区", "agency": "机构", "topic": "主题"}

        console.print(
            f"\n[bold cyan]{name}[/bold cyan] "
            f"[dim]({type_names.get(node_data.get('type', ''), '')})[/dim]"
        )
        console.print(
            f"  关联文档: {node_data.get('doc_count', 0)} · 连接数: {len(neighbors)}\n"
        )

        if neighbors:
            table = Table(show_lines=False)
            table.add_column("邻居节点", style="white")
            table.add_column("类型", style="cyan", width=10)
            table.add_column("关系", style="yellow")
            for nb in neighbors:
                table.add_row(
                    nb["node"],
                    type_names.get(nb["type"], nb["type"]),
                    nb["relation_label"],
                )
            console.print(table)
        console.print()

    def _graph_export(self, gs) -> None:
        """导出 HTML 可视化：/graph export"""
        import webbrowser
        from core.graph.visualizer import generate_html

        if gs.graph.number_of_nodes() == 0:
            console.print("[yellow]图谱为空[/yellow]  [dim]先 /graph build[/dim]")
            return

        html_path = generate_html(gs)
        s = gs.stats()
        console.print(f"\n[green]✓ 已导出[/green]")
        console.print(f"  文件: {html_path}")
        console.print(f"  节点: {s['nodes']} · 边: {s['edges']}")

        # 自动打开浏览器
        file_url = html_path.as_uri()
        webbrowser.open(file_url)
        console.print(f"  [green]✓ 已在浏览器中打开[/green]\n")

    def _graph_clear(self, gs) -> None:
        """清空图谱：/graph clear"""
        gs.clear()
        console.print("[green]✓ 已清空知识图谱[/green]")
        _record_activity("graph", "清空")

    def _graph_delete_node(self, gs, name: str) -> None:
        """删除图谱节点：/graph delete <节点名>"""
        if not name:
            console.print("[yellow]用法: /graph delete <节点名>[/yellow]")
            console.print("[dim]用 /graph neighbors <节点> 查看节点[/dim]")
            return
        if name not in gs.graph:
            console.print(f"[red]节点不存在: {name}[/red]")
            return
        # 显示节点信息供确认
        node_data = gs.graph.nodes[name]
        degree = gs.graph.degree(name)
        console.print(f"  [dim]类型: {node_data.get('type', '?')} · 连接: {degree}[/dim]")
        confirm = Prompt.ask(
            f"确定删除节点 [cyan]{name}[/cyan] 及其 {degree} 条连边？",
            choices=["y", "n"], default="n",
        )
        if confirm != "y":
            console.print("[dim]已取消[/dim]")
            return
        ok = gs.delete_node(name)
        if ok:
            gs.save()
            console.print(f"[green]✓ 已删除节点: {name}[/green]")
        else:
            console.print(f"[red]删除失败[/red]")

    def _graph_rename_node(self, gs, arg: str) -> None:
        """重命名图谱节点：/graph rename <旧名> <新名>"""
        if not arg:
            console.print("[yellow]用法: /graph rename <旧名> <新名>[/yellow]")
            return
        parts = arg.split(maxsplit=1)
        if len(parts) < 2:
            console.print("[yellow]用法: /graph rename <旧名> <新名>[/yellow]")
            return
        old_name, new_name = parts[0].strip(), parts[1].strip()
        if not new_name:
            console.print("[yellow]新名称不能为空[/yellow]")
            return
        ok = gs.rename_node(old_name, new_name)
        if ok:
            gs.save()
            console.print(f"[green]✓ 已重命名: [/green][dim]{old_name} → [/dim][cyan]{new_name}[/cyan]")
        else:
            console.print(f"[red]重命名失败（节点不存在或新名称已存在）[/red]")

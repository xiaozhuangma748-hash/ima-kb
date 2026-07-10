"""管道处理 Mixin。

从 repl.py 第 820-1018 行迁移，包含：
- ``_handle_pipe`` REPL 内管道链式调用
- ``_pipe_search`` 管道版搜索
- ``_pipe_list`` 管道版列表
- ``_pipe_show`` 管道版文档详情
- ``_pipe_stats`` 管道版统计
- ``_pipe_tags`` 管道版标签
- ``_pipe_ask`` 管道下游 ask
"""
from __future__ import annotations

import sys

from core.llm.client import get_llm, LLMError
from core.cli.constants import console


class PipeMixin:
    """管道链式调用相关方法。"""

    def _handle_pipe(self, user_input: str) -> None:
        """REPL 内管道：支持 "命令1 | 命令2" 链式调用。

        示例:
            /search 骨灰 | ask 这些政策有什么差异
            /list | ask 按类型分类统计
            /show 862e0973 | ask 总结要点
            骨灰安置政策 | ask 翻译成英文

        规则:
            - 上游命令的输出作为下游 ask 的上下文
            - 下游只能是 ask（普通问答）
            - 上游可以是 /search /list /show /stats /tags，或纯文本
        """
        # 按 " | " 分割
        segments = [s.strip() for s in user_input.split(" | ") if s.strip()]
        if len(segments) < 2:
            console.print("[yellow]管道用法: 命令1 | 命令2  （至少两段）[/yellow]")
            console.print("[dim]示例: /search 骨灰 | ask 总结差异[/dim]")
            return

        # 逐段执行，上游输出传给下游
        context = ""
        for i, seg in enumerate(segments):
            is_last = (i == len(segments) - 1)

            if seg.startswith("/"):
                # /xxx 命令
                parts = seg.split(maxsplit=1)
                cmd = parts[0].lower()
                arg = parts[1].strip() if len(parts) > 1 else ""

                # 上游命令：捕获输出为文本（不打印 rich 格式）
                if cmd == "/search":
                    context = self._pipe_search(arg)
                elif cmd == "/list":
                    context = self._pipe_list()
                elif cmd == "/show":
                    context = self._pipe_show(arg)
                elif cmd == "/stats":
                    context = self._pipe_stats()
                elif cmd == "/tags":
                    context = self._pipe_tags()
                else:
                    console.print(f"[red]管道不支持命令: {cmd}[/red]")
                    console.print("[dim]支持的命令: /search /list /show /stats /tags | ask[/dim]")
                    return

                if not is_last:
                    console.print(f"[dim]✓ 上游输出 ({len(context)} 字符)，传给下游...[/dim]\n")

            elif seg.lower().startswith("ask "):
                # ask 下游：带 context 调 LLM
                question = seg[4:].strip()
                if not question:
                    console.print("[red]ask 后面要跟问题[/red]")
                    return
                if not context:
                    context = "(无上游内容)"
                self._pipe_ask(question, context)

            else:
                # 纯文本当作 context
                context = seg
                if not is_last:
                    console.print(f"[dim]✓ 文本 ({len(context)} 字符)作为上下文[/dim]\n")

    def _pipe_search(self, query: str) -> str:
        """管道版搜索：返回纯文本结果。"""
        if not query:
            return "[错误] 搜索关键词为空"
        results = self.storage.bm25_search(query, top_k=10)
        if not results:
            return f"未找到与 '{query}' 相关的内容"
        lines = [f"搜索 '{query}' 找到 {len(results)} 条结果：\n"]
        for i, r in enumerate(results, 1):
            lines.append(
                f"[{i}] {r.doc_title} (相关度 {r.score:.2f})\n"
                f"    文档ID: {r.doc_id[:8]}\n"
                f"    内容: {r.content[:300]}\n"
            )
        return "\n".join(lines)

    def _pipe_list(self) -> str:
        """管道版列表：返回纯文本。"""
        docs = self.storage.list_documents(limit=100)
        if not docs:
            return "知识库为空"
        lines = [f"共 {len(docs)} 个文档：\n"]
        for d in docs:
            tags = "、".join(d.tags) if d.tags else "无"
            lines.append(
                f"- [{d.id[:8]}] {d.title}  "
                f"类型:{d.file_type} 标签:{tags} "
                f"分块:{d.chunk_count} tokens:{d.total_tokens}"
            )
        return "\n".join(lines)

    def _pipe_show(self, doc_id: str) -> str:
        """管道版文档详情：返回纯文本。"""
        doc_id = doc_id.strip()
        if len(doc_id) < 32:
            docs = self.storage.list_documents(limit=10000)
            matched = [d for d in docs if d.id.startswith(doc_id)]
            if not matched:
                return f"未找到文档: {doc_id}"
            doc_id = matched[0].id
        doc = self.storage.get_document(doc_id)
        if doc is None:
            return f"未找到文档: {doc_id}"
        chunks = self.storage.get_chunks(doc_id)
        preview = "\n\n".join(c.content[:500] for c in chunks[:5])
        return (
            f"文档: {doc.title}\n"
            f"ID: {doc.id}\n类型: {doc.file_type}\n"
            f"标签: {', '.join(doc.tags) if doc.tags else '无'}\n"
            f"分块: {doc.chunk_count} / Tokens: {doc.total_tokens}\n\n"
            f"前 5 段内容：\n{preview}"
        )

    def _pipe_stats(self) -> str:
        """管道版统计：返回纯文本。"""
        s = self.storage.stats()
        docs = self.storage.list_documents(limit=10000)
        type_count: dict = {}
        for d in docs:
            type_count[d.file_type] = type_count.get(d.file_type, 0) + 1
        type_str = ", ".join(f"{t}:{n}" for t, n in sorted(type_count.items()))
        return (
            f"知识库统计：\n"
            f"- 文档总数: {s['documents']}\n"
            f"- 分块总数: {s['chunks']}\n"
            f"- 总 Tokens: {s['total_tokens']}\n"
            f"- 原文件大小: {s['total_size_mb']} MB\n"
            f"- 类型分布: {type_str}"
        )

    def _pipe_tags(self) -> str:
        """管道版标签：返回纯文本。"""
        docs = self.storage.list_documents(limit=10000)
        tag_count: dict = {}
        for d in docs:
            for t in (d.tags or []):
                tag_count[t] = tag_count.get(t, 0) + 1
        if not tag_count:
            return "无标签"
        lines = [f"共 {len(tag_count)} 个标签：\n"]
        for t, n in sorted(tag_count.items(), key=lambda x: -x[1]):
            lines.append(f"- {t}: {n} 个文档")
        return "\n".join(lines)

    def _pipe_ask(self, question: str, context: str) -> None:
        """管道下游 ask：带 context 调 LLM，流式输出。"""
        if not self.llm_available:
            console.print("[red]LLM 未配置，无法问答[/red]")
            return
        try:
            llm = get_llm()
        except LLMError as e:
            console.print(f"[red]LLM 初始化失败:[/red] {e}")
            return

        prompt = f"""基于以下上下文回答问题。

[上下文]
{context}

[问题]
{question}

要求：基于上下文回答，不要编造。如果上下文不足以回答，明确说明。"""

        messages = [
            {"role": "system", "content": "你是知识库分析助手，基于提供的上下文回答问题。"},
            {"role": "user", "content": prompt},
        ]

        console.print("[bold yellow]>[/bold yellow] [dim]基于管道上下文回答...[/dim]")
        full: list[str] = []
        first_token = True
        try:
            for token in llm.chat_stream(messages, temperature=0.3):
                if first_token:
                    sys.stdout.write("\033[1A\r\033[K")
                    sys.stdout.flush()
                    console.print("[bold yellow]>[/bold yellow] [bold cyan]AI[/bold cyan]", end="")
                    first_token = False
                sys.stdout.write(token)
                sys.stdout.flush()
                full.append(token)
            if first_token:
                sys.stdout.write("\033[1A\r\033[K")
                sys.stdout.flush()
                console.print("[bold yellow]>[/bold yellow] [dim]（无响应）[/dim]")
            console.print()
        except LLMError as e:
            err_msg = str(e).replace("[", "\\[")
            console.print(f"[red]问答失败:[/red] {err_msg}")

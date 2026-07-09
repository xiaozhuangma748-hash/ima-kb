"""Agent 模式：LLM 主动调工具完成复杂任务。

改进（2026-07-09）：
- 工具调用格式从 <tool>...</tool><args>...</args> 改为 JSON
- 系统提示要求 LLM 返回结构化 JSON，提高解析可靠性
- 保留 XML 格式的向后兼容解析

可用工具：
    search <query>      — BM25 搜索知识库
    list_docs           — 列出所有文档
    get_doc <id>        — 查看文档详情
    analyze <path>      — 数据表分析
    read <id>           — 智能阅读
    web_fetch <url>     — 抓取网页（可选）

用法：
    from core.agent.agent import Agent
    ag = Agent(storage)
    result = ag.run("分析最近的骨灰安置政策，对比不同地区的标准")
"""
from __future__ import annotations

import json
import re
from typing import Optional

from config import settings
from core.llm.client import get_llm, LLMError
from core.storage import Storage


# Agent 系统提示（改进版：要求 JSON 输出）
AGENT_SYSTEM_PROMPT = """你是一个能调用工具的智能助手。用户会给你一个任务，你需要分解任务并调用工具完成。

# 可用工具

调用工具的格式（严格遵循 JSON 格式）：
{"tool": "工具名", "args": "参数"}

最终答案格式：
{"tool": "done", "args": "最终答案"}

可用工具列表：
1. search — BM25 搜索知识库（按关键词找内容）
   {"tool": "search", "args": "搜索关键词"}

2. list_docs — 列出所有已入库文档
   {"tool": "list_docs", "args": ""}

3. get_doc — 查看文档详情和前 3 段预览
   {"tool": "get_doc", "args": "文档ID前8位"}

4. read — 读取文档指定段落的原文（1000 字）
   {"tool": "read", "args": "文档ID前8位 段落号"}
   段落号从 1 开始，如 "862e0973 3" 读第 3 段

5. read_multi — 一次读取多段（高效！比逐段 read 省步数）
   {"tool": "read_multi", "args": "文档ID前8位 起始段-结束段"}
   如 "862e0973 1-5" 读第 1 到 5 段

6. analyze — 数据表分析（Excel/CSV/JSON）
   {"tool": "analyze", "args": "文件路径"}

7. done — 任务完成，给出最终答案
   {"tool": "done", "args": "最终答案"}

# 工具选择建议（重要！）

- 不确定知识库有哪些文档 → 先 list_docs
- 知道关键词要找相关内容 → search（最快）
- 想快速了解某文档讲什么 → get_doc
- 想看某段详细内容 → read
- 想一次看多段 → read_multi（强烈推荐，省步数）
- 分析数据表文件 → analyze

# 工作流程（ReAct 模式）

每一步先写 Thought（思考），再写工具调用：

Thought: 我需要先了解知识库有哪些文档
{"tool": "list_docs", "args": ""}

收到工具返回后，分析结果，继续 Thought + 工具调用。

# 注意

- 每次只调一个工具
- 工具调用必须用 JSON 格式：{"tool": "xxx", "args": "yyy"}
- 不要编造，所有信息必须来自工具返回
- 优先用高效工具：read_multi > read > get_doc > 逐段读
- 信息足够时就用 done 给答案，不要过度调用工具
- Thought 和 JSON 之间可以有换行
- 用中文回复用户
"""


class Agent:
    """Agent 模式：LLM 主动调工具。"""

    MAX_STEPS = 12
    MAX_TOKENS = 2000

    def __init__(self, storage: Optional[Storage] = None) -> None:
        if not settings.has_llm():
            raise LLMError("LLM 未配置，Agent 模式需要 AGNES_API_KEY")
        self.llm = get_llm()
        self.storage = storage or Storage()
        self.tools = {
            "search": self._tool_search,
            "list_docs": self._tool_list_docs,
            "get_doc": self._tool_get_doc,
            "analyze": self._tool_analyze,
            "read": self._tool_read,
            "read_multi": self._tool_read_multi,
        }

    def run(self, task: str, on_step: Optional[callable] = None) -> str:
        """执行任务。

        Args:
            task: 用户的任务描述
            on_step: 回调函数（step_type, content）
        Returns:
            最终答案
        """
        messages = [
            {"role": "system", "content": AGENT_SYSTEM_PROMPT},
            {"role": "user", "content": task},
        ]

        called_tools: set = set()

        for step in range(self.MAX_STEPS):
            reply = self.llm.chat(messages, temperature=0.3, max_tokens=self.MAX_TOKENS)
            messages.append({"role": "assistant", "content": reply})

            # 解析工具调用（支持 JSON 和 XML 两种格式）
            tool_name, tool_args = self._parse_tool_call(reply)

            # 提取并显示 Thought
            if on_step:
                thought = self._extract_thought(reply)
                if thought:
                    on_step("thought", thought)

            if tool_name is None:
                # 没有工具调用，检查截断的 done
                if "<tool>done" in reply or '{"tool": "done"' in reply or "<args>" in reply:
                    extracted = self._extract_truncated_args(reply)
                    if extracted:
                        if on_step:
                            on_step("done", extracted)
                        return extracted

                if on_step:
                    on_step("answer", reply)
                return reply

            if tool_name == "done":
                if on_step:
                    on_step("done", tool_args)
                return tool_args

            if tool_name not in self.tools:
                tool_result = (
                    f"[错误] 未知工具: {tool_name}。可用工具: {list(self.tools.keys()) + ['done']}"
                )
                if on_step:
                    on_step("error", tool_result)
            else:
                call_key = f"{tool_name}:{tool_args}"
                if call_key in called_tools:
                    tool_result = (
                        f"[警告] 你已经调用过 {tool_name} {tool_args}，结果已在上文。"
                        f"请换其他工具或换参数。如果信息已足够，请用 done 给出最终答案。"
                    )
                    if on_step:
                        on_step("error", f"重复调用: {tool_name} {tool_args}（已拦截）")
                else:
                    called_tools.add(call_key)
                    if on_step:
                        on_step("tool", f"{tool_name} {tool_args}")
                    try:
                        tool_result = self.tools[tool_name](tool_args)
                    except Exception as e:
                        tool_result = f"[工具执行失败] {type(e).__name__}: {e}"

                    if on_step:
                        on_step("result", tool_result)

            messages.append({
                "role": "user",
                "content": f"工具 {tool_name} 返回结果：\n\n{tool_result}\n\n请继续。",
            })

        # 达到最大次数，强制总结
        if on_step:
            on_step("tool", "summarize（达到上限，生成最终总结）")
        messages.append({
            "role": "user",
            "content": (
                "已达最大工具调用次数。请基于已获取的信息，"
                "直接给出最终答案（不要再调工具，直接输出回答文本）。"
            ),
        })
        summary = self.llm.chat(messages, temperature=0.3, max_tokens=self.MAX_TOKENS)
        if on_step:
            on_step("done", summary)
        return summary

    # ---- 解析工具调用（双格式支持） ----

    @staticmethod
    def _parse_tool_call(text: str):
        """从 LLM 回复中解析工具调用。

        支持两种格式：
        1. JSON: {"tool": "search", "args": "关键词"}
        2. XML: <tool>search</tool>\n<args>关键词</args>

        Returns:
            (tool_name, tool_args) 或 (None, None)
        """
        # 1. 优先尝试 JSON 格式
        json_match = re.search(
            r'\{\s*"tool"\s*:\s*"(\w+)"\s*,\s*"args"\s*:\s*"([^"]*)"\s*\}',
            text,
        )
        if json_match:
            return json_match.group(1), json_match.group(2)

        # 2. 回退到 XML 格式（向后兼容）
        xml_match = re.search(
            r"<tool>\s*(\w+)\s*</tool>\s*<args>\s*(.*?)\s*</args>",
            text,
            re.DOTALL,
        )
        if xml_match:
            return xml_match.group(1), xml_match.group(2)

        return None, None

    @staticmethod
    def _extract_thought(text: str) -> str:
        """从 LLM 回复中提取 Thought（推理过程）。"""
        # JSON 格式：Thought 在 {"tool": ...} 之前
        json_pos = text.find('{"tool":')
        if json_pos == -1:
            json_pos = text.find('<tool>')

        if json_pos > 0:
            before_tool = text[:json_pos]
        else:
            before_tool = text

        # 提取 Thought: xxx
        match = re.search(r"Thought:\s*(.+)", before_tool, re.DOTALL)
        if match:
            thought = match.group(1).strip()
            if len(thought) > 300:
                thought = thought[:300] + "..."
            return thought
        return ""

    @staticmethod
    def _extract_truncated_args(text: str) -> str:
        """从被截断的 done 调用中提取 args 内容。"""
        # JSON 格式截断
        json_match = re.search(r'\{\s*"tool"\s*:\s*"done"\s*,\s*"args"\s*:\s*"(.*)$', text, re.DOTALL)
        if json_match:
            return json_match.group(1).strip()

        # XML 格式截断
        xml_match = re.search(r'<tool>done</tool>\s*<args>(.*)', text, re.DOTALL)
        if xml_match:
            return xml_match.group(1).strip()

        return ""

    # ---- 工具实现 ----

    def _tool_search(self, query: str) -> str:
        """BM25 搜索。"""
        from core.search.bm25 import SearchResult
        query = query.strip()
        if not query:
            return "[错误] 搜索关键词不能为空"

        results = self.storage.bm25_search(query, top_k=5)
        if not results:
            return "[无结果] 未找到相关内容"

        lines = [f"找到 {len(results)} 条结果：\n"]
        for i, r in enumerate(results, 1):
            lines.append(f"[{i}] {r.doc_title} (相关度 {r.score:.2f})")
            lines.append(f"    {r.content[:200]}...")
        return "\n".join(lines)

    def _tool_list_docs(self, _: str) -> str:
        """列出所有文档。"""
        docs = self.storage.list_documents()
        if not docs:
            return "[空] 知识库中没有文档"

        lines = [f"共 {len(docs)} 篇文档：\n"]
        for d in docs:
            lines.append(
                f"  {d.id[:8]}  {d.title}  "
                f"[{d.chunk_count}段] [{','.join(d.tags[:3])}]"
            )
        return "\n".join(lines)

    def _tool_get_doc(self, args: str) -> str:
        """查看文档详情。"""
        args = args.strip()
        if not args:
            return "[错误] 请指定文档ID"

        doc_id = args[:8]
        doc = self.storage.get_document(doc_id)
        if not doc:
            return f"[错误] 文档不存在: {args[:8]}"

        # 获取前 3 段预览
        chunks = self.storage.get_chunks_by_doc(doc_id, limit=3)
        preview = "\n".join(
            f"  第{i+1}段：{c.content[:200]}..."
            for i, c in enumerate(chunks)
        )

        return (
            f"文档: {doc.title}\n"
            f"ID: {doc.id}\n"
            f"标签: {', '.join(doc.tags)}\n"
            f"总段落: {doc.chunk_count}\n"
            f"总字数: {doc.total_tokens}\n\n"
            f"前 3 段预览：\n{preview}"
        )

    def _tool_analyze(self, file_path: str) -> str:
        """数据表分析。"""
        file_path = file_path.strip()
        from pathlib import Path
        path = Path(file_path).expanduser().resolve()
        if not path.exists():
            return f"文件不存在: {path}"

        try:
            from core.analyze.analyzer import DataAnalyzer
            az = DataAnalyzer()
            result = az.analyze(path)
            return (
                f"文件: {result.file_name}\n"
                f"规模: {result.rows} 行 × {result.cols} 列\n"
                f"字段: {', '.join(result.columns[:8])}\n"
                f"数值列描述: {list(result.describe.keys())}\n"
                f"缺失值: {sum(1 for v in result.missing.values() if v > 0)} 列有缺失\n"
                f"\nAI 洞察：\n{result.insights}"
            )
        except Exception as e:
            return f"分析失败: {e}"

    def _tool_read(self, args: str) -> str:
        """读取指定段落的原文。

        参数格式: "文档ID前8位 段落号"，如 "862e0973 3"
        """
        args = args.strip()
        if not args:
            return "[错误] 请指定文档ID，格式: 文档ID 段落号"

        parts = args.split(None, 1)
        doc_id = parts[0].strip()
        chunk_num = 1
        if len(parts) > 1:
            try:
                chunk_num = int(parts[1].strip())
                if chunk_num < 1:
                    chunk_num = 1
            except ValueError:
                return f"[错误] 段落号必须是数字: {parts[1]}"

        try:
            from core.reader.reader import SmartReader
            sr = SmartReader(storage=self.storage)
            state = sr.open(doc_id)
            total = state.total_chunks
            if chunk_num > total:
                return f"[错误] 该文档共 {total} 段，你请求第 {chunk_num} 段（超出范围）"
            sr.goto(chunk_num - 1)
            chunk = sr.current_chunk()
            return (
                f"文档: {state.doc_title} (共 {total} 段)\n\n"
                f"第 {chunk_num} 段内容：\n{chunk.content[:1000]}"
            )
        except Exception as e:
            return f"阅读失败: {e}"

    def _tool_read_multi(self, args: str) -> str:
        """一次读取多段，格式: "文档ID 起始段-结束段"，如 "862e0973 1-5"。"""
        args = args.strip()
        if not args:
            return "[错误] 格式: 文档ID 起始段-结束段，如 862e0973 1-5"

        parts = args.split(None, 1)
        if len(parts) < 2:
            return "[错误] 请指定段落范围，如 862e0973 1-5"
        doc_id = parts[0].strip()
        range_str = parts[1].strip()

        range_match = re.match(r"^(\d+)\s*[-~]\s*(\d+)$", range_str)
        if not range_match:
            return f"[错误] 段落范围格式错误: {range_str}，应为 起始-结束，如 1-5"

        start = int(range_match.group(1))
        end = int(range_match.group(2))
        if start < 1:
            start = 1
        if end < start:
            return f"[错误] 结束段 {end} 小于起始段 {start}"

        try:
            from core.reader.reader import SmartReader
            sr = SmartReader(storage=self.storage)
            state = sr.open(doc_id)
            total = state.total_chunks
            if start > total:
                return f"[错误] 起始段 {start} 超出范围（共 {total} 段）"
            if end > total:
                end = total
            if end - start + 1 > 8:
                end = start + 7

            lines = [f"文档: {state.doc_title} (共 {total} 段，读取 {start}-{end} 段)\n"]
            for i in range(start, end + 1):
                sr.goto(i - 1)
                chunk = sr.current_chunk()
                lines.append(f"--- 第 {i} 段 ---\n{chunk.content[:500]}\n")
            return "\n".join(lines)
        except Exception as e:
            return f"阅读失败: {e}"

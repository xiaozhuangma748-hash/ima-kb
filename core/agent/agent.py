"""Agent 模式：LLM 主动调工具完成复杂任务。

改进（2026-07-09）：
- 工具调用格式从 <tool>...</tool><args>...</args> 改为 JSON
- 系统提示要求 LLM 返回结构化 JSON，提高解析可靠性
- 保留 XML 格式的向后兼容解析

重构（2026-07-10）：
- 工具系统改为 Tool Registry + Schema 校验（core/agent/tools/）
- 系统提示由 ``ToolRegistry.build_system_prompt()`` 自动生成
- 工具通过 ``@register_tool`` 装饰器扩展，Agent 经 ``ToolContext`` 注入依赖

可用工具（由 Registry 动态注册，详见 core/agent/tools/builtin.py）：
    search <query>      — BM25 搜索知识库
    list_docs           — 列出所有文档
    get_doc <id>        — 查看文档详情
    analyze <path>      — 数据表分析
    read <id> [n]       — 读取文档段落
    read_multi <id> a-b — 读取多段落

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
from core.agent.tools import get_registry
from core.agent.tools.base import ToolContext


class Agent:
    """Agent 模式：LLM 主动调工具。"""

    MAX_STEPS = 12
    MAX_TOKENS = 2000

    def __init__(self, storage: Optional[Storage] = None) -> None:
        if not settings.has_llm():
            raise LLMError("LLM 未配置，Agent 模式需要 AGNES_API_KEY")
        self.llm = get_llm()
        self.storage = storage or Storage()

        # 工具依赖通过 ToolContext 注入；系统提示由 Registry 生成
        self._registry = get_registry()
        self._tool_context = ToolContext(
            storage=self.storage,
            llm=self.llm,
        )
        self._system_prompt = self._registry.build_system_prompt()

    def run(self, task: str, on_step: Optional[callable] = None) -> str:
        """执行任务。

        Args:
            task: 用户的任务描述
            on_step: 回调函数（step_type, content）
        Returns:
            最终答案
        """
        messages = [
            {"role": "system", "content": self._system_prompt},
            {"role": "user", "content": task},
        ]

        called_tools: set = set()
        available_names = self._registry.names() + ["done"]

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

            tool = self._registry.get(tool_name)
            if tool is None:
                tool_result = (
                    f"[错误] 未知工具: {tool_name}。可用工具: {available_names}"
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
                        tool_result = tool.execute_from_str(
                            tool_args, context=self._tool_context
                        )
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

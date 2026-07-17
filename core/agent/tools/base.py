"""Tool 基类、Registry、上下文与注册装饰器。

设计要点：
- ``Tool`` 为基类，子类定义 ``name``/``description``/``args_schema``/``prompt_block``
  并实现 ``execute()`` 与 ``_parse_args_str()``。
- ``ToolRegistry`` 为单例，集中管理工具；``build_system_prompt()`` 自动拼装
  与原 ``AGENT_SYSTEM_PROMPT`` 逐字一致的系统提示。
- ``ToolContext`` 由 Agent 注入，提供 ``storage``/``llm``/``chunker`` 依赖。
- ``@register_tool`` 装饰器注册工具实例到全局 Registry。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple, Type

from pydantic import BaseModel


# ============================================================
# 系统提示静态片段（与原 AGENT_SYSTEM_PROMPT 逐字一致）
# ============================================================

_PROMPT_HEADER = (
    "你是一个能调用工具的智能助手。用户会给你一个任务，你需要分解任务并调用工具完成。\n"
    "\n"
    "# 可用工具\n"
    "\n"
    "调用工具的格式（严格遵循 JSON 格式）：\n"
    '{"tool": "工具名", "args": "参数"}\n'
    "\n"
    "最终答案格式：\n"
    '{"tool": "done", "args": "最终答案"}\n'
    "\n"
    "可用工具列表：\n"
)

_PROMPT_DONE_BLOCK = (
    'done — 任务完成，给出最终答案\n'
    '   {"tool": "done", "args": "最终答案"}'
)

_PROMPT_FOOTER = (
    "# 工具选择建议（重要！）\n"
    "\n"
    "- 不确定知识库有哪些文档 → 先 list_docs\n"
    "- 知道关键词要找相关内容 → search（最快）\n"
    "- 想快速了解某文档讲什么 → get_doc\n"
    "- 想看某段详细内容 → read\n"
    "- 想一次看多段 → read_multi（强烈推荐，省步数）\n"
    "- 分析数据表文件 → analyze\n"
    "\n"
    "# 工作流程（ReAct 模式）\n"
    "\n"
    "每一步先写 Thought（思考），再写工具调用：\n"
    "\n"
    "Thought: 我需要先了解知识库有哪些文档\n"
    '{"tool": "list_docs", "args": ""}\n'
    "\n"
    "收到工具返回后，分析结果，继续 Thought + 工具调用。\n"
    "\n"
    "# 注意\n"
    "\n"
    "- 每次只调一个工具\n"
    '- 工具调用必须用 JSON 格式：{"tool": "xxx", "args": "yyy"}\n'
    "- 不要编造，所有信息必须来自工具返回\n"
    "- 优先用高效工具：read_multi > read > get_doc > 逐段读\n"
    "- 信息足够时就用 done 给答案，不要过度调用工具\n"
    "- Thought 和 JSON 之间可以有换行\n"
    "- 用中文回复用户\n"
    "\n"
    "# 强制输出格式（重要！）\n"
    "\n"
    "**无论是否需要调用工具，每一步都必须先输出 Thought。**\n"
    "即使问题可以直接回答（如问候、自我介绍），也必须在最终答案前输出 Thought：\n"
    "\n"
    "Thought: 用户在问候，我直接回答即可。\n"
    '{"tool": "done", "args": "你好！我是 Agnes-2.0-Flash，由 Sapiens AI 开发的智能助手。"}\n'
    "\n"
    "Thought: 用户问我的身份，我简要回答。\n"
    '{"tool": "done", "args": "我是 Agnes-2.0-Flash，由 Sapiens AI 开发的智能助手。"}\n'
    "\n"
    "绝对禁止：直接输出答案而不带 Thought 前缀。\n"
    "\n"
    "# 引用规范（重要！）\n"
    "\n"
    "最终答案中**不要使用 [n] 形式的引用标记**（如 [1]、[2]），原因：\n"
    "- 每次工具调用（如 search）各自独立编号，[1] 在不同调用中指向不同内容\n"
    "- 多次调用后 [n] 的指向不唯一，用户无法准确追溯\n"
    "\n"
    "正确做法（用文档标题或 ID 标注来源）：\n"
    '- 「根据《海葬政策》第 3 段所述...」\n'
    '- 「如文档 862e0973 所述...」\n'
    '- 「《骨灰安置办法》中提到...」\n'
    "\n"
    "错误做法（避免）：\n"
    '- 「根据[1]所述...」（[1] 指向不明）\n'
    '- 「如[3]所述...」（[3] 可能是任一次 search 的结果）\n'
)


# ============================================================
# 工具执行上下文
# ============================================================

class ToolContext:
    """工具执行上下文，由 Agent 在运行时注入依赖。"""

    def __init__(
        self,
        storage: Any = None,
        llm: Any = None,
        chunker: Any = None,
        hybrid_retriever: Any = None,
        pet: Any = None,
        pet_interactor: Any = None,
        pet_storage: Any = None,
        pet_shop: Any = None,
        pet_task_manager: Any = None,
    ) -> None:
        self.storage = storage
        self.llm = llm
        self.chunker = chunker
        # P0-P5 工业级 RAG 流水线（BM25+向量+RRF+Cross-Encoder+HyDE+缓存）
        # 优先使用注入的 retriever；为 None 时工具回退到旧 BM25 路径
        self.hybrid_retriever = hybrid_retriever
        # 虚拟宠物依赖：让 pet_interact/pet_status/pet_manage/pet_shop 工具
        # 能真正查询和更新宠物状态（未注入时相关工具返回未启用提示）
        self.pet = pet
        self.pet_interactor = pet_interactor
        self.pet_storage = pet_storage
        self.pet_shop = pet_shop
        self.pet_task_manager = pet_task_manager
        # SmartReader 缓存：连续读同一文档时复用实例，避免重复 open
        # key = doc_id（前 8 位前缀），value = (reader, opened_doc_id)
        self._reader_cache: Dict[str, Tuple[Any, str]] = {}
        self._reader_cache_max = 4  # 最多缓存 4 个文档的 reader


# ============================================================
# Tool 基类
# ============================================================

@dataclass
class Tool:
    """工具基类。

    子类需定义 ``name``/``description``/``args_schema``/``prompt_block``，
    实现 ``_parse_args_str()`` 与 ``execute()``。
    """

    name: str = ""
    description: str = ""
    args_schema: Optional[Type[BaseModel]] = None
    prompt_block: str = field(default="")

    # ---- 执行入口 ----

    def execute(self, context: Optional[ToolContext] = None, **kwargs) -> str:
        """业务逻辑，由子类实现。"""
        raise NotImplementedError

    def _parse_args_str(self, args_str: str) -> Tuple[Dict[str, Any], Optional[str]]:
        """从原始参数字符串解析出结构化参数。

        Returns:
            (kwargs_dict, error) — error 非 None 时表示解析失败，直接返回该错误文案。
            默认实现：尝试 JSON 解析为 dict，失败则返回空 dict（无参数）。
            子类按需覆盖以复刻各自的参数格式与错误文案。
        """
        import json as _json

        text = args_str.strip()
        if text:
            # 尝试 JSON 解析（用于结构化参数）
            try:
                parsed = _json.loads(text)
                if isinstance(parsed, dict):
                    return parsed, None
            except (ValueError, TypeError):
                pass
        return {}, None

    def execute_from_str(self, args_str: str, context: Optional[ToolContext] = None) -> str:
        """从字符串解析参数并执行（兼容旧的 ``args: str`` 签名）。

        流程：``_parse_args_str`` → ``args_schema`` 校验 → ``execute``。
        """
        kwargs, error = self._parse_args_str(args_str)
        if error is not None:
            return error

        if self.args_schema is not None:
            try:
                validated = self.args_schema(**kwargs)
                kwargs = validated.model_dump()
            except Exception as e:  # pydantic.ValidationError 等
                return f"[参数校验失败] {type(e).__name__}: {e}"

        return self.execute(context=context, **kwargs)


# ============================================================
# Tool Registry（单例）
# ============================================================

class ToolRegistry:
    """工具注册器（单例）。按注册顺序保存工具，用于构建系统提示。"""

    _instance: Optional["ToolRegistry"] = None

    def __new__(cls) -> "ToolRegistry":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._tools = {}  # type: ignore[attr-defined]
        return cls._instance

    def __init__(self) -> None:
        # __new__ 已初始化 _tools，这里避免重复覆盖
        if not hasattr(self, "_tools"):
            self._tools: Dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        """注册一个工具实例。"""
        self._tools[tool.name] = tool

    def get(self, name: str) -> Optional[Tool]:
        """按名取工具，不存在返回 None。"""
        return self._tools.get(name)

    def all(self) -> List[Tool]:
        """返回所有已注册工具（按注册顺序）。"""
        return list(self._tools.values())

    def names(self) -> List[str]:
        return list(self._tools.keys())

    def build_system_prompt(self) -> str:
        """自动生成系统提示的工具描述部分。

        与原 ``AGENT_SYSTEM_PROMPT`` 逐字一致：注册工具依次编号，
        末尾追加 ``done`` 工具块。
        """
        parts: List[str] = [_PROMPT_HEADER]
        tools = self.all()
        for i, tool in enumerate(tools, 1):
            parts.append(f"{i}. {tool.prompt_block}\n\n")
        # done 不是可执行工具，单独追加
        parts.append(f"{len(tools) + 1}. {_PROMPT_DONE_BLOCK}\n\n")
        parts.append(_PROMPT_FOOTER)
        return "".join(parts)


# ============================================================
# 全局 Registry 与装饰器
# ============================================================

_registry = ToolRegistry()


def register_tool(tool_cls: Type[Tool]) -> Type[Tool]:
    """装饰器：注册工具到全局 Registry。

    传入工具类，注册其实例（工具无状态，依赖通过 ``ToolContext`` 注入），
    返回原类以便外部继续引用。
    """
    _registry.register(tool_cls())
    return tool_cls


def get_registry() -> ToolRegistry:
    """获取全局 Tool Registry 单例。"""
    return _registry

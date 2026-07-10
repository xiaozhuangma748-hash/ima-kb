"""Agent 工具系统：Tool Registry + Schema 校验。

通过 ``@register_tool`` 装饰器注册工具，Agent 运行时从 Registry 取用，
系统提示由 ``ToolRegistry.build_system_prompt()`` 自动生成。

用法：
    from core.agent.tools import get_registry, ToolContext

    registry = get_registry()
    tool = registry.get("search")
    tool.execute_from_str("骨灰安置", context=ctx)
"""
from .base import (
    Tool,
    ToolRegistry,
    ToolContext,
    register_tool,
    get_registry,
)
from .builtin import *  # noqa: F401,F403  触发所有内置工具注册

__all__ = [
    "Tool",
    "ToolRegistry",
    "ToolContext",
    "register_tool",
    "get_registry",
]

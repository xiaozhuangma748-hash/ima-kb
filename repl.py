"""交互式 REPL CLI — 顶层 re-export 兼容层。

本文件原为 4487 行单文件，现已拆分到 ``core/cli/`` 包（Mixin 模式）。
保留此文件仅为向后兼容：
- ``run.py`` 的 ``from repl import main`` 仍可用
- 测试的 ``from repl import REPL`` 仍可用
- 测试的 ``patch("repl.Prompt.ask", ...)`` 仍可用

实际实现位于：
- ``core/cli/repl.py``  REPL 主类
- ``core/cli/main.py``  入口函数
- ``core/cli/constants.py``  常量
- ``core/cli/completer.py``  补全器
- ``core/cli/welcome.py``    启动面板
- ``core/cli/chat.py``       AI 对话 Mixin
- ``core/cli/commands/``     命令 Mixin 子包
"""
from __future__ import annotations

# re-export 主要符号，保持向后兼容
from rich.prompt import Prompt  # noqa: F401 — 测试用 patch("repl.Prompt.ask", ...)

from core.cli.repl import REPL  # noqa: F401
from core.cli.main import main  # noqa: F401


if __name__ == "__main__":
    main()

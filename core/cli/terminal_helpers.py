"""终端模式辅助函数。

prompt_toolkit 接管终端后，直接用 input() 回车会显示 ^M。
改用 prompt_toolkit 自身做确认和输入，与 REPL 共用同一终端库，无冲突。
"""

from __future__ import annotations

import sys


def repl_confirm(msg: str, default: str = "n") -> bool:
    """REPL 环境下安全确认（y/n），使用 prompt_toolkit。"""
    from prompt_toolkit.shortcuts import prompt as pt_prompt
    from prompt_toolkit.styles import Style

    default_hint = f" ({default})" if default else ""
    prompt_text = f"{msg} [y/n]{default_hint}: "

    try:
        result = pt_prompt(
            prompt_text,
            default=default,
            style=Style.from_dict({"": ""}),
        )
    except (EOFError, KeyboardInterrupt):
        return False
    if not result:
        return default == "y"
    return result.strip().lower() in ("y", "yes")


def repl_input(prompt_text: str, default: str = "") -> str:
    """REPL 环境下安全读取输入，使用 prompt_toolkit。"""
    from prompt_toolkit.shortcuts import prompt as pt_prompt
    from prompt_toolkit.styles import Style

    try:
        result = pt_prompt(
            prompt_text + " ",
            default=default,
            style=Style.from_dict({"": ""}),
        )
    except (EOFError, KeyboardInterrupt):
        return default
    return result.strip() if result.strip() else default

"""命令补全器与输入读取。

从 repl.py 第 522-631 行迁移：
- ``CommandCompleter`` 类（中文描述 + 子命令嵌套补全）
- ``_build_nested_completer()`` 构建函数
- ``_read_input()`` 输入读取函数

注意：``_INPUT_STYLE`` 是可变全局（``_cmd_theme`` 会重赋值），
``_read_input`` 必须通过 ``constants._INPUT_STYLE`` 属性动态读取，
不能用 ``from ... import`` 快照。
"""
from __future__ import annotations

from prompt_toolkit import prompt as pt_prompt
from prompt_toolkit.completion import Completer, Completion

from core.cli import constants
from core.cli.constants import (
    _cmd_history,
    COMMAND_LIST,
    _SUB_MENU_NESTED,
    _SUB_MENU_DESC,
    _CMD_ALIASES,
)


class CommandCompleter(Completer):
    """命令补全器：支持中文描述 + 子命令嵌套。"""

    def __init__(self, commands, sub_menus, sub_desc):
        self._cmd_meta = dict(commands)       # 命令 → 中文描述
        self._sub_menus = sub_menus           # 完整命令 → 子命令字典
        self._sub_desc = sub_desc           # tuple path → 子命令描述

    def _resolve(self, cmd: str) -> str:
        """解析别名到完整命令名。"""
        return _CMD_ALIASES.get(cmd, cmd)

    def get_completions(self, document, complete_event):
        text = document.text_before_cursor.lstrip()
        parts = text.split() if text else []
        trailing = text.endswith(" ")              # 是否已按空格 → 进入下一级

        if not parts:
            # 空输入 → 显示所有命令
            for cmd, meta in sorted(self._cmd_meta.items()):
                yield Completion(cmd, start_position=0, display_meta=meta)
            return

        first = parts[0]

        # 仅一个词 且 未按空格 → 正在输入命令名
        if len(parts) == 1 and not trailing:
            for cmd, meta in sorted(self._cmd_meta.items()):
                if cmd.startswith(first):
                    yield Completion(cmd, start_position=-len(first), display_meta=meta)
            return

        # ——— 走到这里说明需要子命令 / 多级嵌套 ———

        resolved = self._resolve(first)
        menu = self._sub_menus.get(resolved)
        if menu is None:
            return

        # 把 parts[1:] 作为导航路径，trailing 表示最后一级也已完成
        nav = list(parts[1:])
        if trailing:
            nav.append("")                          # 空字符串 → 展示当前级全部选项

        # 逐级深入子菜单；path 用于描述查找
        path = [resolved]

        for i, seg in enumerate(nav):
            if isinstance(menu, dict) and seg in menu:
                # 该级已命中 → 进入下一级
                menu = menu[seg]
                path.append(seg)
            elif isinstance(menu, dict):
                # 未命中(或空串) → 在当前级做前缀匹配并显示描述
                for sub_cmd in sorted(menu.keys()):
                    if sub_cmd.startswith(seg):
                        desc_path = tuple(path + [sub_cmd])
                        desc = self._sub_desc.get(desc_path)
                        yield Completion(
                            sub_cmd, start_position=-len(seg),
                            display_meta=desc if desc else None,
                        )
                return
            else:
                return


def _build_nested_completer() -> CommandCompleter:
    """构建命令补全器，顶层命令带中文描述，子命令按嵌套字典补全。"""
    commands = list(COMMAND_LIST)
    # 别名命令也纳入补全
    commands.append(('/m', '/memory（别名）'))
    commands.append(('/g', '/graph（别名）'))
    commands.append(('/p', '/pet（别名）'))
    commands.append(('/h', '/help（别名）'))
    commands.append(('/q', '/quit（别名）'))
    return CommandCompleter(commands, _SUB_MENU_NESTED, _SUB_MENU_DESC)


def _read_input() -> str:
    """读取用户输入，输入 / 时自动弹出命令补全菜单。

    - 橙色 > 提示符（Claude Code 风格）
    - 输入 / 后立即显示所有命令列表 + 描述
    - 用方向键 ↑↓ 选择，Tab/Enter 确认
    - Ctrl+D / Ctrl+C 退出
    """
    try:
        text = pt_prompt(
            [("class:prompt", "> ")],
            completer=_build_nested_completer(),
            complete_while_typing=True,
            style=constants._INPUT_STYLE,
            history=_cmd_history,
        )
        return text.strip()
    except (EOFError, KeyboardInterrupt):
        raise

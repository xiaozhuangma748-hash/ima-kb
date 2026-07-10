"""REPL 入口函数。

从 repl.py 第 4472-4487 行迁移：
- ``main()`` REPL 启动入口，捕获异常后退出
"""
from __future__ import annotations

import sys

from core.cli.constants import console
from core.cli.repl import REPL


def main() -> None:
    """REPL 入口。"""
    try:
        repl = REPL()
        repl.run()
    except KeyboardInterrupt:
        console.print("\n[dim]再见[/dim]")
    except Exception as e:
        # 错误信息可能含 rich markup 字符，用 [red]...[/] 简写避免闭合问题
        err_msg = str(e).replace("[", "\\[")
        console.print(f"\n[red]错误:[/red] {type(e).__name__}: {err_msg}")
        sys.exit(1)


if __name__ == "__main__":
    main()

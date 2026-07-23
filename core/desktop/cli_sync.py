"""CLI 桌宠状态联动（零侵入，独立脚本）。

设计目的：
- 用户在终端使用 ``ima ask`` / ``ima ingest`` 等命令时，
  桌面宠物自动切换到对应状态（listening → thinking → retrieving → answering）。
- 不修改 ``run.py`` 任何现有代码，通过独立 CLI 命令实现。

用法：
    # 手动切换桌宠状态
    python -m core.desktop.cli_sync state thinking

    # 带状态联动的问答（替代 ima ask）
    python -m core.desktop.cli_sync ask "什么是殡葬改革"

    # 带状态联动的入库（替代 ima ingest）
    python -m core.desktop.cli_sync ingest /path/to/file.pdf

    # 检查桌宠是否在运行
    python -m core.desktop.cli_sync status

零侵入约束：
- 本模块属于 ``core/desktop/`` 新增模块，不修改项目任何现有文件。
- 复用 ``run.py`` 内部函数（``_ingest_one`` 等），但不修改 ``run.py``。
"""
from __future__ import annotations

import logging
import sys
import time
from typing import Optional

logger = logging.getLogger(__name__)


def _try_set_state(state: str) -> bool:
    """尝试通过 IPC 切换桌宠状态（失败静默，不影响 CLI 正常运行）。

    Returns:
        True 表示发送成功；False 表示桌宠未运行或发送失败。
    """
    try:
        from core.desktop.ipc import IpcClient
        client = IpcClient()
        if not client.is_server_running():
            return False
        return client.set_state(state)
    except Exception as e:
        logger.debug(f"IPC set_state({state}) 失败（桌宠可能未运行）: {e}")
        return False


def cmd_state(state: str) -> int:
    """手动切换桌宠状态。

    Args:
        state: 状态名（idle/listening/thinking/retrieving/ranking/
               answering/celebrating/error/sleeping/ingesting/analyzing/notifying）

    Returns:
        0 成功；1 桌宠未运行；2 无效状态
    """
    valid_states = {
        "idle", "listening", "thinking", "retrieving", "ranking",
        "answering", "celebrating", "error", "sleeping",
        "ingesting", "analyzing", "notifying",
    }
    if state not in valid_states:
        print(f"无效状态: {state}")
        print(f"可选: {', '.join(sorted(valid_states))}")
        return 2

    if _try_set_state(state):
        print(f"✓ 桌宠状态已切换: {state}")
        return 0
    else:
        print("✗ 桌宠未运行，请先启动: ./bin/ima-desktop")
        return 1


def cmd_ask(question: str) -> int:
    """带桌宠状态联动的问答（替代 ``ima ask``）。

    流程：
    1. listening（倾听用户问题）
    2. thinking（思考中）
    3. retrieving → ranking（检索 + 重排，由 ask_stream 内部事件驱动）
    4. answering（生成回答）
    5. celebrating / error（完成/失败）

    Returns:
        0 成功；1 桌宠未运行（回退到普通 ask）；2 问答失败
    """
    from rich.console import Console
    from rich.markdown import Markdown

    console = Console()

    # 推送初始状态
    pet_running = _try_set_state("listening")
    if pet_running:
        console.print("[dim]🐾 桌宠状态联动中[/dim]")

    _try_set_state("thinking")

    try:
        from core.pet.administrator import PetAdministrator
        from core.pet.storage import PetStorage
        from core.storage import Storage
        from core.memory.store import MemoryStore
        from core.retrieval.hybrid import HybridRetriever
        from core.retrieval.rerank import Reranker
        from core.llm.client import get_llm
    except Exception as e:
        console.print(f"[red]依赖加载失败: {e}[/red]")
        _try_set_state("error")
        return 2

    try:
        pet = PetStorage().load()
        if not pet:
            console.print("[red]请先领养宠物: ima pet adopt[/red]")
            _try_set_state("error")
            return 2

        storage = Storage()
        memory = MemoryStore()

        vector_index = None
        try:
            from core.retrieval.vector import VectorIndex
            vector_index = VectorIndex()
        except Exception:
            pass

        hybrid = HybridRetriever(bm25_index=storage.bm25, vector_index=vector_index, storage=storage)
        llm = get_llm()
        reranker = Reranker(llm)

        admin = PetAdministrator(pet=pet, storage=storage, memory_store=memory,
                                 hybrid_retriever=hybrid, reranker=reranker, llm=llm)

        # 流式问答 + 状态联动
        console.print(f"\n[bold cyan]问:[/bold cyan] {question}\n")
        _try_set_state("retrieving")

        full_text = ""
        citations = []

        for event in admin.ask_stream(question):
            evt_type = event.get("type")
            if evt_type == "stage":
                stage = event.get("stage", "")
                if "检索" in stage or "retriev" in stage.lower():
                    _try_set_state("retrieving")
                elif "重排" in stage or "rank" in stage.lower():
                    _try_set_state("ranking")
                elif "生成" in stage or "回答" in stage or "answer" in stage.lower():
                    _try_set_state("answering")
            elif evt_type == "token":
                chunk = event.get("text", "")
                full_text += chunk
                console.print(chunk, end="", style="green", highlight=False)
            elif evt_type == "done":
                result = event.get("result")
                if result and result.citations:
                    citations = result.citations

        console.print()
        if full_text:
            console.print(Markdown(full_text))

        if citations:
            console.print("\n[bold]引用溯源:[/bold]")
            for c in citations:
                console.print(f"  [{c.marker}] {c.title}")

        _try_set_state("celebrating")
        time.sleep(1)
        _try_set_state("idle")
        return 0

    except Exception as e:
        console.print(f"\n[red]问答失败: {e}[/red]")
        _try_set_state("error")
        return 2


def cmd_ingest(file_path: str) -> int:
    """带桌宠状态联动的入库（替代 ``ima ingest``）。

    流程：
    1. ingesting（入库中）
    2. analyzing（分析/分块/打标签）
    3. celebrating / error（成功/失败）

    Returns:
        0 成功；1 桌宠未运行；2 入库失败
    """
    from pathlib import Path
    from rich.console import Console

    console = Console()
    p = Path(file_path)

    if not p.exists():
        console.print(f"[red]文件不存在: {file_path}[/red]")
        return 2

    pet_running = _try_set_state("ingesting")
    if pet_running:
        console.print("[dim]🐾 桌宠状态联动中[/dim]")

    _try_set_state("analyzing")

    try:
        from core.desktop.ingest_helper import ingest_file
        from core.storage import Storage

        storage = Storage()
        result = ingest_file(str(p), storage=storage)

        if result.get("success"):
            if result.get("error") == "already_exists":
                console.print(f"[yellow]已存在: {result.get('file_name')}[/yellow]")
            else:
                console.print(f"[green]✓ 已入库: {result.get('file_name')}[/green]")
                console.print(f"  文档ID: {result.get('doc_id', 'N/A')}")
            _try_set_state("celebrating")
            time.sleep(1)
            _try_set_state("idle")
            return 0
        else:
            console.print(f"[red]入库失败: {result.get('error')}[/red]")
            _try_set_state("error")
            return 2

    except Exception as e:
        console.print(f"[red]入库异常: {e}[/red]")
        _try_set_state("error")
        return 2


def cmd_status() -> int:
    """检查桌宠是否在运行。"""
    try:
        from core.desktop.ipc import IpcClient
        client = IpcClient()
        if client.is_server_running():
            info = client.get_pet_info()
            stats = client.get_stats()
            print("✓ 桌面宠物运行中")
            if info:
                print(f"  宠物: {info.get('name', '?')} / {info.get('branch', '?')} / Lv{info.get('level', 1)}")
            if stats:
                print(f"  知识库: {stats.get('total_docs', 0)} 文档 / {stats.get('total_chunks', 0)} 分块")
            return 0
        else:
            print("✗ 桌面宠物未运行")
            print("  启动: ./bin/ima-desktop")
            return 1
    except Exception as e:
        print(f"✗ 检查失败: {e}")
        return 1


def main() -> int:
    """CLI 入口。"""
    import argparse

    parser = argparse.ArgumentParser(
        description="桌面宠物 CLI 状态联动（零侵入，独立于 run.py）",
        prog="python -m core.desktop.cli_sync",
    )
    sub = parser.add_subparsers(dest="command")

    # state: 手动切换状态
    p_state = sub.add_parser("state", help="手动切换桌宠状态")
    p_state.add_argument("state", help="状态名 (idle/listening/thinking/...)")

    # ask: 带状态联动的问答
    p_ask = sub.add_parser("ask", help="带桌宠状态联动的问答")
    p_ask.add_argument("question", help="问题")

    # ingest: 带状态联动的入库
    p_ingest = sub.add_parser("ingest", help="带桌宠状态联动的入库")
    p_ingest.add_argument("file", help="文件路径")

    # status: 检查桌宠状态
    sub.add_parser("status", help="检查桌宠是否在运行")

    args = parser.parse_args()

    if args.command == "state":
        return cmd_state(args.state)
    elif args.command == "ask":
        return cmd_ask(args.question)
    elif args.command == "ingest":
        return cmd_ingest(args.file)
    elif args.command == "status":
        return cmd_status()
    else:
        parser.print_help()
        return 0


if __name__ == "__main__":
    sys.exit(main())

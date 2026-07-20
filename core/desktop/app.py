"""桌面宠物守护者主入口（Task 12 集成版 + macOS 托盘兼容）。

零侵入约束：
- 本模块属于 ``core/desktop/`` 新增模块，不修改项目任何现有文件。
- 删除 ``core/desktop/`` 与根目录 ``ima-desktop`` / ``requirements-desktop.txt`` /
  ``install-desktop.sh`` 即可完全回退。

集成模块（Task 12）：
1. 检查依赖（pywebview + pystray）→ 缺失则友好提示 + exit(1)
2. 加载配置（``DesktopPetSettings``）
3. 检查宠物领养状态（``PetStorage.load()``）→ 未领养则提示 + exit(1)
4. 创建 ``AsciiArtLoader`` / ``DesktopPetAdministrator`` / ``DesktopBridge``
5. 创建 ``TrayManager``（pystray 可用时），注入回调
6. 启动 Mobile 同步服务（fastapi/uvicorn 可用时）
7. 创建 pywebview 窗口，注入 bridge 作为 ``js_api``
8. 窗口加载后注入 ``evaluate_js`` 给 bridge
9. 启动托盘（macOS 上禁用，避免 NSApplication 冲突）+ pywebview 主循环
10. Ctrl+C 优雅退出（停止托盘）
"""
from __future__ import annotations

import logging
import signal
import sys

logger = logging.getLogger(__name__)


def _missing_dependencies() -> list:
    """返回缺失的桌面宠物依赖列表（空列表表示全部可用）。

    检测 ``pywebview``（导入名为 ``webview``）与 ``pystray`` 是否均可导入。
    两者均为独立可选依赖，未声明在 ``pyproject.toml`` 中（零侵入），
    需通过 ``requirements-desktop.txt`` 单独安装。
    """
    missing = []
    try:
        import webview  # noqa: F401  仅做导入检测
    except ImportError:
        missing.append("pywebview")
    try:
        import pystray  # noqa: F401  仅做导入检测
    except ImportError:
        missing.append("pystray")
    return missing


def is_desktop_available() -> bool:
    """检测桌面宠物依赖（pywebview + pystray）是否全部可用。

    Returns:
        True 表示 ``pywebview`` 与 ``pystray`` 均可导入；
        False 表示至少一个依赖缺失（此时 ``main()`` 会输出友好提示并 exit(1)）。
    """
    return not _missing_dependencies()


def _setup_logging() -> None:
    """配置日志（basicConfig，幂等，不影响项目其他模块的日志配置）。"""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )


def _create_pet_administrator():
    """创建 ``DesktopPetAdministrator`` 实例（含所有 PetAdministrator 依赖）。

    流程：
    1. 通过 ``PetStorage.load()`` 加载宠物；未领养返回 ``None``。
    2. 构造 ``Storage`` / ``MemoryStore`` / ``HybridRetriever`` / ``Reranker`` / ``LLMClient``。
    3. ``VectorIndex`` 可选（导入失败时传 ``None``，HybridRetriever 仍可工作）。
    4. 返回 ``DesktopPetAdministrator`` 实例。

    Returns:
        ``DesktopPetAdministrator`` 实例，或 ``None``（宠物未领养或依赖失败）。
    """
    try:
        from core.pet.storage import PetStorage
        from core.storage import Storage
        from core.memory.store import MemoryStore
        from core.retrieval.hybrid import HybridRetriever
        from core.retrieval.rerank import Reranker
        from core.llm.client import get_llm
        from core.desktop.pet_wrapper import DesktopPetAdministrator

        pet_storage = PetStorage()
        pet = pet_storage.load()
        if not pet:
            return None

        storage = Storage()
        memory = MemoryStore()

        # VectorIndex 可选（未安装向量依赖时传 None，HybridRetriever 降级为纯 BM25）
        vector_index = None
        try:
            from core.retrieval.vector import VectorIndex
            vector_index = VectorIndex()
        except Exception as e:
            logger.info(f"VectorIndex 不可用，降级为纯 BM25: {e}")

        hybrid = HybridRetriever(
            bm25_index=storage.bm25,
            vector_index=vector_index,
            storage=storage,
        )
        llm = get_llm()
        reranker = Reranker(llm)

        return DesktopPetAdministrator(
            pet=pet, storage=storage, memory_store=memory,
            hybrid_retriever=hybrid, reranker=reranker, llm=llm,
        )
    except Exception as e:
        logger.error(f"创建 PetAdministrator 失败: {e}")
        return None


def _is_tray_supported_on_platform() -> bool:
    """检查当前平台是否支持同时启动系统托盘与 pywebview。

    macOS 上 pystray 的 AppKit 后端与 pywebview 的 NSApplication 主循环冲突，
    同时启动会导致 ``webview.start()`` 立即返回、窗口一闪而过。
    因此在 macOS 上禁用托盘，让 pywebview 独占主线程。

    Returns:
        True 表示当前平台可以同时启动托盘与 pywebview（Windows/Linux）。
        False 表示当前平台需要禁用托盘（macOS）。
    """
    import platform

    return platform.system() != "Darwin"


def _create_tray_manager(bridge, settings):
    """创建托盘管理器（pystray 不可用时返回 ``None``）。

    Args:
        bridge: ``DesktopBridge`` 实例（用于切换人格 / 显示统计 / 通知 JS）
        settings: ``DesktopPetSettings`` 实例（用于切换 DND / 音效 / 尺寸）

    Returns:
        ``TrayManager`` 实例，或 ``None``（pystray 不可用）。
    """
    from core.desktop.tray import TrayManager

    def on_switch_style(style):
        if bridge:
            try:
                bridge.switch_style(style)
            except Exception as e:
                logger.warning(f"切换人格失败: {e}")

    def on_toggle_web():
        # TrayManager 内部已通过 subprocess.Popen(["ima", "web"]) 启动/停止 Web 后台
        # 此处无需额外操作（零侵入：不修改 web/）
        pass

    def on_toggle_dnd():
        try:
            settings.toggle_dnd()
            if bridge and bridge._evaluate_js:
                bridge._call_js(f"setDndMode({str(settings.dnd).lower()})")
        except Exception as e:
            logger.warning(f"切换 DND 失败: {e}")

    def on_toggle_sound():
        try:
            settings.toggle_sound()
            if bridge and bridge._evaluate_js:
                bridge._call_js(f"setSoundEnabled({str(settings.sound).lower()})")
        except Exception as e:
            logger.warning(f"切换音效失败: {e}")

    def on_set_size(size):
        try:
            settings.update_size(size)
        except Exception as e:
            logger.warning(f"切换尺寸失败: {e}")

    def on_set_state(state):
        """手动切换宠物状态（托盘菜单触发）。"""
        if bridge:
            try:
                bridge.set_state(state)
            except Exception as e:
                logger.warning(f"切换状态失败: {e}")

    def on_show_stats():
        try:
            stats = bridge.get_stats() if bridge else {}
            if bridge and bridge._evaluate_js:
                total_docs = stats.get("total_docs", 0)
                total_chunks = stats.get("total_chunks", 0)
                bridge._call_js(f"showBubble('文档: {total_docs} / 分块: {total_chunks}')")
        except Exception as e:
            logger.warning(f"显示统计失败: {e}")

    def on_exit():
        logger.info("用户通过托盘退出")
        # 通过 SIGINT 触发主线程的 KeyboardInterrupt（pywebview.start 阻塞主线程）
        import os
        try:
            os.kill(os.getpid(), signal.SIGINT)
        except Exception:
            pass

    return TrayManager.create(
        on_switch_style=on_switch_style,
        on_toggle_web=on_toggle_web,
        on_toggle_dnd=on_toggle_dnd,
        on_toggle_sound=on_toggle_sound,
        on_set_size=on_set_size,
        on_set_state=on_set_state,
        on_show_stats=on_show_stats,
        on_exit=on_exit,
    )


def main() -> None:
    """桌面宠物主入口（Task 12 集成版）。

    流程：
    1. 配置日志
    2. 检查依赖（pywebview + pystray），缺失 → 友好提示 + exit(1)
    3. 加载配置（``DesktopPetSettings``）
    4. 创建 PetAdministrator（含宠物领养检查），未领养 → 提示 + exit(1)
    5. 创建 ``AsciiArtLoader``
    6. 创建 ``DesktopBridge``，注入状态变更回调到 pet_admin
    7. 创建 ``TrayManager``（pystray 可用时）
    8. 启动 Mobile 同步服务（fastapi/uvicorn 可用时）
    9. 创建 pywebview 窗口，注入 bridge 作为 ``js_api``
    10. 窗口加载后注入 ``evaluate_js`` 给 bridge
    11. 启动托盘
    12. 启动 pywebview 主循环
    13. Ctrl+C 优雅退出（停止托盘）
    """
    _setup_logging()

    # 1. 依赖检查
    if not is_desktop_available():
        missing = _missing_dependencies()
        deps = " 与 ".join(missing)
        print(f"桌面宠物需要 {deps}：pip install -r requirements-desktop.txt")
        sys.exit(1)

    # 2. 加载配置
    from core.desktop.settings import DesktopPetSettings
    settings = DesktopPetSettings.load()
    logger.info(f"加载配置: {settings.to_dict()}")

    # 3. 创建 PetAdministrator（含宠物领养检查）
    pet_admin = _create_pet_administrator()
    if pet_admin is None:
        print("请先在 REPL 中执行 /pet adopt 领养宠物")
        sys.exit(1)

    # 4. 创建 AsciiArtLoader（按宠物分支与等级）
    from core.desktop.renderer import AsciiArtLoader
    ascii_loader = AsciiArtLoader(
        branch=pet_admin.pet.branch or "scholar",
        level=pet_admin.pet.level,
    )

    # 5. 创建 Bridge（注入 ascii_loader / pet_admin / storage）
    from core.desktop.bridge import DesktopBridge
    bridge = DesktopBridge(
        ascii_loader=ascii_loader,
        pet_admin=pet_admin,
        storage=pet_admin.storage,
    )

    # 注入状态变更回调到 pet_admin（bridge.notify_state_change）
    pet_admin._on_state_change = bridge.notify_state_change

    # 6. 创建托盘（pystray 可用时）
    tray = _create_tray_manager(bridge, settings)

    # 7. 启动 Mobile 同步服务（如果可用）
    try:
        from core.desktop.mobile_server import (
            is_mobile_server_available,
            start_mobile_server,
        )
        if is_mobile_server_available():
            mobile_port, mobile_thread = start_mobile_server()
            logger.info(f"Mobile 同步服务: http://0.0.0.0:{mobile_port}/")
        else:
            logger.info("FastAPI/uvicorn 未安装，跳过 Mobile 同步")
    except Exception as e:
        logger.warning(f"Mobile 同步服务启动失败: {e}")

    # 8. 创建窗口并启动 pywebview
    from core.desktop.window import create_window
    import webview

    config = create_window()

    # 窗口加载后注入 evaluate_js 给 bridge，并初始化 JS 端状态
    # pywebview 6.x 的 events.loaded 事件在某些版本不稳定，
    # 改用 webview.start(func=...) 在独立线程中延迟初始化更可靠。
    def _init_after_start():
        import time as _time
        # 等 webview 窗口就绪（最多等 5 秒）
        for _ in range(50):
            if webview.windows:
                break
            _time.sleep(0.1)
        if not webview.windows:
            logger.warning("等待 webview 窗口就绪超时（5 秒），跳过初始化")
            return

        try:
            win = webview.windows[0]
            # 注入 evaluate_js（让 Python 端能反向调用 JS）
            bridge.set_evaluate_js(win.evaluate_js)
            logger.info("evaluate_js 已注入 bridge")

            # 给 JS 一点时间完成 DOMContentLoaded
            _time.sleep(0.5)

            # 推送初始 GIF 状态：idle（不推送欢迎气泡，保持安静）
            # GIF 文件名映射在 JS 端硬编码，Python 端只需推送状态名
            bridge._call_js("setCatGif('idle')")
            bridge._call_js("updateStateDirect('idle')")
            logger.info("已推送初始 GIF 状态 (idle)")
        except Exception as e:
            logger.warning(f"窗口加载后初始化失败: {e}")
            import traceback
            traceback.print_exc()

    print("桌面宠物已启动，按 Ctrl+C 退出")

    # 9. 启动 IPC 服务（让独立托盘进程 / CLI 能驱动主进程）
    from core.desktop.ipc import IpcServer
    ipc_server = IpcServer(bridge=bridge)
    ipc_server.start()

    # 10. 启动托盘
    # macOS 兼容性：pystray 的 AppKit 后端与 pywebview 的 NSApplication 冲突，
    # 在独立子进程中运行托盘，通过 IPC 通信。
    # Windows/Linux：在进程内独立线程运行托盘。
    tray_started = False
    tray_subprocess = None
    if tray and _is_tray_supported_on_platform():
        # Windows/Linux: 进程内托盘
        tray.start()
        tray_started = True
    elif tray:
        # macOS: 子进程托盘
        try:
            import subprocess as _sp
            tray_subprocess = _sp.Popen(
                [sys.executable, "-m", "core.desktop.tray_runner"],
                stdout=_sp.DEVNULL,
                stderr=_sp.DEVNULL,
            )
            logger.info(f"macOS 托盘子进程已启动 (PID={tray_subprocess.pid})")
        except Exception as e:
            logger.warning(f"启动托盘子进程失败: {e}")

    # 11. 启动 pywebview（js_api=bridge 让 JS 可调用 bridge 方法）
    try:
        window = webview.create_window(
            title=config.title,
            url=config.url,
            width=config.size[0],
            height=config.size[1],
            frameless=config.frameless,
            on_top=config.on_top,
            transparent=config.transparent,
            easy_drag=config.easy_drag,
            hidden=config.hidden,
            js_api=bridge,
        )
        # 使用 func 参数在独立线程中初始化（比 events.loaded 更稳定）
        webview.start(func=_init_after_start)
    except KeyboardInterrupt:
        print("\n桌面宠物已退出")
    finally:
        # 优雅退出：停止托盘 + IPC + 子进程
        if tray and tray_started:
            tray.stop()
        if tray_subprocess:
            try:
                tray_subprocess.terminate()
                tray_subprocess.wait(timeout=3)
            except Exception:
                pass
        ipc_server.stop()
        logger.info("桌面宠物已完全退出")


if __name__ == "__main__":
    main()

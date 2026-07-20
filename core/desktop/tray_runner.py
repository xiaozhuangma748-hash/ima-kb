"""独立托盘进程入口（解决 macOS 上 pystray 与 pywebview 主循环冲突）。

设计：
- 在独立 Python 进程中运行 pystray（独占 AppKit 主循环）
- 所有菜单操作通过 IPC（Unix socket）转发给主 pywebview 进程
- 主进程通过 ``subprocess.Popen([python, "-m", "core.desktop.tray_runner"])`` 启动

用法（自动启动）：
    由 ``app.py`` 在 macOS 上自动以子进程方式启动，无需手动运行。

手动启动（调试）：
    ./.venv/bin/python -m core.desktop.tray_runner

零侵入约束：
- 本模块属于 ``core/desktop/`` 新增模块，不修改项目任何现有文件。
"""
from __future__ import annotations

import logging
import sys
import time

logger = logging.getLogger(__name__)


def main() -> None:
    """启动独立托盘进程。

    流程：
    1. 设置为 macOS 后台应用（不显示在 Dock）
    2. 检查 IPC 服务是否在线（主进程是否在运行）
    3. 创建 TrayManager，所有回调走 IPC
    4. 在主线程运行 pystray（独占 AppKit）
    """
    # 1. macOS 后台应用：不显示在 Dock，但菜单栏图标可见
    # NSApplicationActivationPolicyRegular = 0 (默认，Dock 显示)
    # NSApplicationActivationPolicyAccessory = 1 (不显示 Dock，但有菜单栏)
    try:
        from AppKit import NSApplication
        NSApplication.sharedApplication()
        # 在创建 NSApp 之后、pystray 接管之前设置
        import objc
        # 不在这里直接设置，等 pystray 创建后设置
    except Exception:
        pass

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    from core.desktop.ipc import IpcClient
    from core.desktop.tray import TrayManager

    ipc = IpcClient()

    # 等待主进程 IPC 就绪（最多等 15 秒）
    for i in range(30):
        if ipc.is_server_running():
            break
        time.sleep(0.5)
    else:
        logger.error("等待主进程 IPC 超时（15 秒），托盘进程退出")
        sys.exit(1)

    logger.info("已连接到主进程 IPC")

    # 所有回调通过 IPC 转发
    def on_set_state(state):
        try:
            ok = ipc.set_state(state)
            logger.info(f"IPC set_state({state}) -> {ok}")
        except Exception as e:
            logger.error(f"IPC set_state 失败: {e}")

    def on_switch_style(style):
        try:
            ipc.send("switch_style", style=style)
        except Exception as e:
            logger.error(f"IPC switch_style 失败: {e}")

    def on_toggle_dnd():
        # DND 逻辑在主进程端执行，这里仅通知
        try:
            ipc.show_bubble("勿扰模式已切换")
        except Exception:
            pass

    def on_toggle_sound():
        try:
            ipc.show_bubble("音效已切换")
        except Exception:
            pass

    def on_set_size(size):
        try:
            ipc.show_bubble(f"尺寸: {size}")
        except Exception:
            pass

    def on_show_stats():
        try:
            stats = ipc.get_stats()
            ipc.show_bubble(f"文档: {stats.get('total_docs', 0)} / 分块: {stats.get('total_chunks', 0)}")
        except Exception as e:
            logger.error(f"IPC get_stats 失败: {e}")

    def on_exit():
        logger.info("用户通过托盘退出")
        # 发送退出信号给主进程（通过显示气泡提示，主进程的 SIGINT 仍需用户 Ctrl+C）
        # 更彻底的方案：主进程监听特定 IPC 命令来退出
        try:
            ipc.show_bubble("再见！")
        except Exception:
            pass
        sys.exit(0)

    tray = TrayManager.create(
        on_set_state=on_set_state,
        on_switch_style=on_switch_style,
        on_toggle_dnd=on_toggle_dnd,
        on_toggle_sound=on_toggle_sound,
        on_set_size=on_set_size,
        on_show_stats=on_show_stats,
        on_exit=on_exit,
    )

    if tray is None:
        logger.error("pystray 不可用，托盘进程退出")
        sys.exit(1)

    # 在主线程运行 pystray（阻塞）
    # macOS 上 pystray 的 run() 会接管 AppKit 主循环
    try:
        from pystray import Icon
        from PIL import Image, ImageDraw

        # 生成猫爪图标
        def _make_icon():
            img = Image.new('RGBA', (64, 64), (0, 0, 0, 0))
            draw = ImageDraw.Draw(img)
            # 简易猫爪：一个大椭圆 + 4 个小圆
            draw.ellipse([20, 28, 44, 52], fill=(255, 180, 100, 230))
            draw.ellipse([12, 20, 22, 30], fill=(255, 180, 100, 230))
            draw.ellipse([24, 14, 34, 24], fill=(255, 180, 100, 230))
            draw.ellipse([36, 14, 46, 24], fill=(255, 180, 100, 230))
            draw.ellipse([42, 20, 52, 30], fill=(255, 180, 100, 230))
            return img

        menu, _ = tray._build_menu()
        icon = Icon("ima-desktop-pet", _make_icon(), "IMA 桌面宠物", menu)

        # macOS 后台应用策略：不显示在 Dock，只在菜单栏显示托盘图标
        # NSApplicationActivationPolicyAccessory = 1
        try:
            from AppKit import NSApplication
            app = NSApplication.sharedApplication()
            # 在 icon.run() 之前设置（pystray 内部会调用 NSApp.run()）
            app.setActivationPolicy_(1)  # Accessory
            logger.info("已设置为 macOS 后台应用（不显示在 Dock）")
        except Exception as e:
            logger.debug(f"设置后台应用策略失败（不影响功能）: {e}")

        logger.info("独立托盘进程已启动")
        icon.run()
    except KeyboardInterrupt:
        pass
    finally:
        logger.info("托盘进程退出")


if __name__ == "__main__":
    main()

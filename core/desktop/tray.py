"""系统托盘管理（pystray，独立线程）。

零侵入约束：
- 本模块属于 ``core/desktop/`` 新增模块，不修改项目任何现有文件。
- 不依赖 pystray 实际安装：``TrayManager.create()`` 工厂方法在 pystray 未安装时
  返回 ``None``，桌面宠物仍可启动（仅托盘菜单不可用）。
- Web 后台启动通过 ``subprocess.Popen(["ima", "web"])``，**不修改** ``web/``。

设计：
1. ``is_tray_available()`` 检测 ``pystray`` 是否可导入。
2. ``TrayManager`` 封装 ``pystray.Icon``，在独立线程运行，不阻塞 pywebview 主循环。
3. 菜单项回调通过构造参数注入（``on_switch_style`` / ``on_toggle_web`` 等），
   与 ``DesktopBridge`` / ``DesktopPetAdministrator`` 解耦。
4. 内部维护 Web 子进程 ``_web_process`` 与各项状态（DND / 音效 / 当前人格 / 尺寸）。
"""
from __future__ import annotations

import logging
import subprocess
import threading
from typing import Callable, Optional

logger = logging.getLogger(__name__)


def is_tray_available() -> bool:
    """检查 ``pystray`` 是否可用。

    Returns:
        True 表示 ``pystray`` 可导入；False 表示未安装。
    """
    try:
        import pystray  # noqa: F401  仅做导入检测
        return True
    except ImportError:
        return False


class TrayManager:
    """系统托盘管理器（pystray）。

    pystray 未安装时 ``create()`` 工厂方法返回 ``None``，桌面宠物仍可启动。

    所有菜单项回调均为可选，未注入时仅更新内部状态（不报错）。
    Web 后台通过 ``subprocess.Popen(["ima", "web"])`` 启动，**不修改** ``web/``。
    """

    def __init__(
        self,
        on_switch_style: Optional[Callable[[str], None]] = None,
        on_toggle_web: Optional[Callable[[], bool]] = None,  # 返回当前 web 是否运行
        on_toggle_dnd: Optional[Callable[[], bool]] = None,  # 返回当前 dnd 是否开启
        on_toggle_sound: Optional[Callable[[], bool]] = None,
        on_set_size: Optional[Callable[[str], None]] = None,  # 'S' / 'M' / 'L'
        on_show_stats: Optional[Callable[[], None]] = None,
        on_exit: Optional[Callable[[], None]] = None,
        on_set_state: Optional[Callable[[str], None]] = None,
    ) -> None:
        self._on_switch_style = on_switch_style
        self._on_toggle_web = on_toggle_web
        self._on_toggle_dnd = on_toggle_dnd
        self._on_toggle_sound = on_toggle_sound
        self._on_set_size = on_set_size
        self._on_show_stats = on_show_stats
        self._on_exit = on_exit
        self._on_set_state = on_set_state

        self._icon = None
        self._thread = None
        self._web_process: Optional[subprocess.Popen] = None
        self._dnd_enabled = False
        self._sound_enabled = True
        self._current_style = "auto"
        self._current_size = "M"

    @classmethod
    def create(cls, **kwargs) -> Optional['TrayManager']:
        """工厂方法：pystray 不可用时返回 ``None``。

        Args:
            **kwargs: 透传给 ``TrayManager.__init__`` 的回调参数。

        Returns:
            pystray 可用时返回 ``TrayManager`` 实例；不可用时返回 ``None``。
        """
        if not is_tray_available():
            logger.info("pystray 未安装，跳过系统托盘")
            return None
        return cls(**kwargs)

    def _build_menu(self):
        """构建托盘菜单（``pystray.Menu``）与图标。

        Returns:
            ``(menu, icon_image)`` 元组。
        """
        from pystray import Menu, MenuItem
        from PIL import Image, ImageDraw

        # 生成简单的图标（蓝色方块带星）
        def _make_icon():
            img = Image.new('RGBA', (64, 64), (0, 0, 0, 0))
            draw = ImageDraw.Draw(img)
            draw.rectangle([8, 8, 56, 56], fill=(74, 144, 226, 220))
            draw.text((28, 22), "✻", fill=(255, 255, 255))
            return img

        # 切换人格子菜单
        style_submenu = Menu(
            MenuItem("scholar (学者)", lambda: self._handle_switch_style("scholar")),
            MenuItem("warrior (武士)", lambda: self._handle_switch_style("warrior")),
            MenuItem("artisan (工匠)", lambda: self._handle_switch_style("artisan")),
            MenuItem("neutral (中立)", lambda: self._handle_switch_style("neutral")),
            MenuItem("auto (自动)", lambda: self._handle_switch_style("auto")),
        )

        # 切换状态子菜单（12 个 GIF 状态）
        state_submenu = Menu(
            MenuItem("idle (待机)", lambda: self._handle_set_state("idle")),
            MenuItem("listening (倾听)", lambda: self._handle_set_state("listening")),
            MenuItem("thinking (思考)", lambda: self._handle_set_state("thinking")),
            MenuItem("retrieving (检索)", lambda: self._handle_set_state("retrieving")),
            MenuItem("ranking (重排)", lambda: self._handle_set_state("ranking")),
            MenuItem("answering (回答)", lambda: self._handle_set_state("answering")),
            MenuItem("celebrating (庆祝)", lambda: self._handle_set_state("celebrating")),
            MenuItem("error (出错)", lambda: self._handle_set_state("error")),
            MenuItem("sleeping (睡眠)", lambda: self._handle_set_state("sleeping")),
            MenuItem("ingesting (入库)", lambda: self._handle_set_state("ingesting")),
            MenuItem("analyzing (分析)", lambda: self._handle_set_state("analyzing")),
            MenuItem("notifying (通知)", lambda: self._handle_set_state("notifying")),
        )

        # 尺寸子菜单
        size_submenu = Menu(
            MenuItem("S (小)", lambda: self._handle_set_size("S")),
            MenuItem("M (中)", lambda: self._handle_set_size("M")),
            MenuItem("L (大)", lambda: self._handle_set_size("L")),
        )

        menu = Menu(
            MenuItem("IMA Desktop Pet", None, enabled=False),
            Menu.SEPARATOR,
            MenuItem("切换状态", state_submenu),
            MenuItem("切换人格", style_submenu),
            MenuItem("启动 Web 后台", lambda: self._handle_toggle_web()),
            MenuItem("勿扰模式", lambda: self._handle_toggle_dnd(),
                     checked=lambda _: self._dnd_enabled),
            MenuItem("音效", lambda: self._handle_toggle_sound(),
                     checked=lambda _: self._sound_enabled),
            MenuItem("尺寸", size_submenu),
            Menu.SEPARATOR,
            MenuItem("显示统计", lambda: self._handle_show_stats()),
            Menu.SEPARATOR,
            MenuItem("退出", lambda: self._handle_exit()),
        )

        return menu, _make_icon()

    # ------------------------------------------------------------------
    # 菜单回调处理（私有方法，供 MenuItem lambda 调用）
    # ------------------------------------------------------------------

    def _handle_switch_style(self, style: str) -> None:
        """处理切换人格菜单项。"""
        self._current_style = style
        if self._on_switch_style:
            try:
                self._on_switch_style(style)
            except Exception as e:
                logger.error(f"切换人格回调失败: {e}")

    def _handle_toggle_web(self) -> None:
        """处理启动/停止 Web 后台菜单项。

        Web 后台通过 ``subprocess.Popen(["ima", "web"])`` 启动（不修改 ``web/``）。
        若已在运行则终止子进程；否则启动新进程。
        """
        if self._web_process and self._web_process.poll() is None:
            # 正在运行，停止
            try:
                self._web_process.terminate()
                self._web_process.wait(timeout=5)
            except Exception as e:
                logger.warning(f"停止 Web 失败: {e}")
            finally:
                self._web_process = None
        else:
            # 启动
            try:
                self._web_process = subprocess.Popen(
                    ["ima", "web"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                logger.info(f"Web 后台已启动，PID={self._web_process.pid}")
            except Exception as e:
                logger.error(f"启动 Web 失败: {e}")
                self._web_process = None
        if self._on_toggle_web:
            try:
                self._on_toggle_web()
            except Exception:
                pass

    def _handle_toggle_dnd(self) -> None:
        """处理勿扰模式菜单项（翻转内部状态）。"""
        self._dnd_enabled = not self._dnd_enabled
        if self._on_toggle_dnd:
            try:
                self._on_toggle_dnd()
            except Exception as e:
                logger.error(f"切换勿扰回调失败: {e}")

    def _handle_toggle_sound(self) -> None:
        """处理音效开关菜单项（翻转内部状态）。"""
        self._sound_enabled = not self._sound_enabled
        if self._on_toggle_sound:
            try:
                self._on_toggle_sound()
            except Exception as e:
                logger.error(f"切换音效回调失败: {e}")

    def _handle_set_size(self, size: str) -> None:
        """处理尺寸菜单项（'S' / 'M' / 'L'）。"""
        self._current_size = size
        if self._on_set_size:
            try:
                self._on_set_size(size)
            except Exception as e:
                logger.error(f"切换尺寸回调失败: {e}")

    def _handle_set_state(self, state: str) -> None:
        """处理切换宠物状态菜单项（idle/listening/thinking/...）。"""
        if self._on_set_state:
            try:
                self._on_set_state(state)
            except Exception as e:
                logger.error(f"切换状态回调失败: {e}")

    def _handle_show_stats(self) -> None:
        """处理显示统计菜单项。"""
        if self._on_show_stats:
            try:
                self._on_show_stats()
            except Exception as e:
                logger.error(f"显示统计回调失败: {e}")

    def _handle_exit(self) -> None:
        """处理退出菜单项：调用退出回调 → 终止 Web 进程 → 停止托盘。"""
        if self._on_exit:
            try:
                self._on_exit()
            except Exception as e:
                logger.error(f"退出回调失败: {e}")
        if self._web_process and self._web_process.poll() is None:
            try:
                self._web_process.terminate()
            except Exception:
                pass
        self.stop()

    # ------------------------------------------------------------------
    # 生命周期
    # ------------------------------------------------------------------

    def start(self) -> None:
        """在独立线程启动托盘（不阻塞调用方）。

        pystray 不可用时直接返回；启动异常时记录日志并将 ``_icon`` 置 None，
        保证调用方不抛异常。
        """
        if not is_tray_available():
            return
        try:
            from pystray import Icon
            menu, icon_image = self._build_menu()
            self._icon = Icon("ima-desktop", icon_image, "IMA Desktop Pet", menu)
            self._thread = threading.Thread(target=self._icon.run, daemon=True)
            self._thread.start()
            logger.info("系统托盘已启动")
        except Exception as e:
            logger.error(f"系统托盘启动失败: {e}")
            self._icon = None

    def stop(self) -> None:
        """停止托盘（停止图标 + 等待线程退出）。"""
        if self._icon:
            try:
                self._icon.stop()
            except Exception:
                pass
            self._icon = None
        if self._thread:
            self._thread.join(timeout=2)
            self._thread = None

    # ------------------------------------------------------------------
    # 只读属性（供测试与外部观察状态）
    # ------------------------------------------------------------------

    @property
    def is_web_running(self) -> bool:
        """Web 后台子进程是否仍在运行。"""
        return self._web_process is not None and self._web_process.poll() is None

    @property
    def dnd_enabled(self) -> bool:
        """勿扰模式是否开启。"""
        return self._dnd_enabled

    @property
    def sound_enabled(self) -> bool:
        """音效是否开启。"""
        return self._sound_enabled

    @property
    def current_style(self) -> str:
        """当前人格风格（``scholar``/``warrior``/``artisan``/``neutral``/``auto``）。"""
        return self._current_style

    @property
    def current_size(self) -> str:
        """当前尺寸（``S``/``M``/``L``）。"""
        return self._current_size

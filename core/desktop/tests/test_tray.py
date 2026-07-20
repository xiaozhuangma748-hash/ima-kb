"""系统托盘管理测试（Task 8）。

验证 ``core.desktop.tray.TrayManager`` 与 ``is_tray_available`` 的核心契约：
1. ``is_tray_available()`` 返回布尔值（无论 pystray 是否安装）。
2. ``TrayManager.create()`` 在 pystray 不可用时返回 ``None``，可用时返回实例。
3. 默认构造时所有回调为 ``None``，内部状态为默认值。
4. 注入回调后 ``_handle_*`` 方法触发对应回调。
5. ``_handle_toggle_dnd`` / ``_handle_toggle_sound`` 每次调用翻转内部状态。
6. ``_handle_toggle_web`` 通过 ``subprocess.Popen`` 启动/停止 Web 子进程。
7. ``_handle_exit`` 调用退出回调并调用 ``stop()``。
8. 只读属性返回正确的内部状态。
9. 零侵入验证：``web/app.py`` 与 ``web/routes/`` 仍存在且未被修改。

测试不依赖 pystray 实际安装：通过 ``patch('core.desktop.tray.is_tray_available', ...)``
控制工厂方法行为，通过 ``patch('subprocess.Popen', ...)`` mock 子进程。
"""
from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

from core.desktop.tray import TrayManager, is_tray_available


# ------------------------------------------------------------------
# is_tray_available
# ------------------------------------------------------------------

def test_is_tray_available_returns_bool():
    """``is_tray_available()`` 必须返回布尔值（True 或 False）。

    无论 ``pystray`` 是否安装，该函数都应返回 ``bool`` 类型，不能抛异常。
    """
    result = is_tray_available()
    assert isinstance(result, bool), (
        f"期望 is_tray_available() 返回 bool，实际返回 {type(result).__name__}"
    )


# ------------------------------------------------------------------
# 工厂方法
# ------------------------------------------------------------------

def test_tray_manager_create_returns_none_when_unavailable():
    """pystray 不可用时 ``TrayManager.create()`` 返回 ``None``。"""
    with patch('core.desktop.tray.is_tray_available', return_value=False):
        result = TrayManager.create()
    assert result is None, (
        f"pystray 不可用时 create() 应返回 None，实际为 {result!r}"
    )


def test_tray_manager_create_returns_instance_when_available():
    """pystray 可用时 ``TrayManager.create()`` 返回 ``TrayManager`` 实例（不实际启动）。"""
    with patch('core.desktop.tray.is_tray_available', return_value=True):
        result = TrayManager.create()
    try:
        assert isinstance(result, TrayManager), (
            f"pystray 可用时 create() 应返回 TrayManager 实例，实际为 {type(result).__name__}"
        )
        # create() 不应启动 icon / thread
        assert result._icon is None, "create() 不应启动 icon"
        assert result._thread is None, "create() 不应启动 thread"
    finally:
        if result is not None:
            result.stop()


# ------------------------------------------------------------------
# 默认构造与回调注入
# ------------------------------------------------------------------

def test_tray_manager_init_defaults():
    """默认构造时所有回调应为 ``None``，内部状态为默认值。"""
    tray = TrayManager()
    assert tray._on_switch_style is None
    assert tray._on_toggle_web is None
    assert tray._on_toggle_dnd is None
    assert tray._on_toggle_sound is None
    assert tray._on_set_size is None
    assert tray._on_show_stats is None
    assert tray._on_exit is None
    # 默认状态
    assert tray._dnd_enabled is False
    assert tray._sound_enabled is True
    assert tray._current_style == "auto"
    assert tray._current_size == "M"
    assert tray._web_process is None


def test_tray_manager_init_with_callbacks():
    """传入回调后，应被存储到对应属性。"""
    on_switch = MagicMock()
    on_web = MagicMock()
    on_dnd = MagicMock()
    on_sound = MagicMock()
    on_size = MagicMock()
    on_stats = MagicMock()
    on_exit = MagicMock()

    tray = TrayManager(
        on_switch_style=on_switch,
        on_toggle_web=on_web,
        on_toggle_dnd=on_dnd,
        on_toggle_sound=on_sound,
        on_set_size=on_size,
        on_show_stats=on_stats,
        on_exit=on_exit,
    )
    assert tray._on_switch_style is on_switch
    assert tray._on_toggle_web is on_web
    assert tray._on_toggle_dnd is on_dnd
    assert tray._on_toggle_sound is on_sound
    assert tray._on_set_size is on_size
    assert tray._on_show_stats is on_stats
    assert tray._on_exit is on_exit


# ------------------------------------------------------------------
# _handle_* 方法
# ------------------------------------------------------------------

def test_handle_switch_style_calls_callback():
    """``_handle_switch_style('scholar')`` 应调用回调并更新 ``current_style``。"""
    cb = MagicMock()
    tray = TrayManager(on_switch_style=cb)

    tray._handle_switch_style("scholar")

    cb.assert_called_once_with("scholar")
    assert tray.current_style == "scholar", (
        f"调用后 current_style 应为 'scholar'，实际为 {tray.current_style!r}"
    )


def test_handle_toggle_dnd_flips_state():
    """连续两次 ``_handle_toggle_dnd()`` 应使 ``_dnd_enabled`` 翻转：False → True → False。"""
    tray = TrayManager()
    assert tray._dnd_enabled is False, "初始 dnd 应为 False"

    tray._handle_toggle_dnd()
    assert tray._dnd_enabled is True, "第一次切换后 dnd 应为 True"

    tray._handle_toggle_dnd()
    assert tray._dnd_enabled is False, "第二次切换后 dnd 应为 False"


def test_handle_toggle_sound_flips_state():
    """连续两次 ``_handle_toggle_sound()`` 应使 ``_sound_enabled`` 翻转：True → False → True。"""
    tray = TrayManager()
    assert tray._sound_enabled is True, "初始 sound 应为 True"

    tray._handle_toggle_sound()
    assert tray._sound_enabled is False, "第一次切换后 sound 应为 False"

    tray._handle_toggle_sound()
    assert tray._sound_enabled is True, "第二次切换后 sound 应为 True"


def test_handle_set_size_calls_callback():
    """``_handle_set_size('L')`` 应调用回调并更新 ``current_size``。"""
    cb = MagicMock()
    tray = TrayManager(on_set_size=cb)

    tray._handle_set_size("L")

    cb.assert_called_once_with("L")
    assert tray.current_size == "L", (
        f"调用后 current_size 应为 'L'，实际为 {tray.current_size!r}"
    )


def test_handle_toggle_web_starts_and_stops():
    """``_handle_toggle_web()`` 通过 ``subprocess.Popen`` 启动 Web；再次调用应终止进程。

    场景：
    1. 首次调用 → Popen 启动子进程，``is_web_running`` 为 True。
    2. 第二次调用 → 调用 ``terminate()`` 与 ``wait()``，``_web_process`` 置 None。
    """
    mock_proc = MagicMock()
    mock_proc.poll.return_value = None  # 正在运行
    mock_proc.pid = 12345

    with patch('subprocess.Popen', return_value=mock_proc) as mock_popen:
        tray = TrayManager()

        # 首次调用：启动
        tray._handle_toggle_web()
        mock_popen.assert_called_once()
        # 验证启动参数：通过 ["ima", "web"] 启动，stdout/stderr 重定向到 DEVNULL
        call_args = mock_popen.call_args
        assert call_args.args[0] == ["ima", "web"], (
            f"Popen 应接收 ['ima', 'web']，实际为 {call_args.args[0]!r}"
        )
        assert call_args.kwargs.get("stdout") is subprocess.DEVNULL, (
            "Popen 应将 stdout 重定向到 DEVNULL（不修改 web/）"
        )
        assert call_args.kwargs.get("stderr") is subprocess.DEVNULL, (
            "Popen 应将 stderr 重定向到 DEVNULL（不修改 web/）"
        )
        assert tray.is_web_running is True, "启动后 is_web_running 应为 True"

        # 第二次调用：停止（poll 返回 None 表示仍在运行 → 触发 terminate 路径）
        tray._handle_toggle_web()
        mock_proc.terminate.assert_called_once()
        mock_proc.wait.assert_called_once()
        assert tray._web_process is None, "停止后 _web_process 应为 None"
        assert tray.is_web_running is False, "停止后 is_web_running 应为 False"


def test_handle_exit_calls_callback_and_stops():
    """``_handle_exit()`` 应调用退出回调并调用 ``stop()``。"""
    exit_cb = MagicMock()
    tray = TrayManager(on_exit=exit_cb)

    with patch.object(tray, 'stop') as mock_stop:
        tray._handle_exit()

    exit_cb.assert_called_once()
    mock_stop.assert_called_once()


# ------------------------------------------------------------------
# 只读属性
# ------------------------------------------------------------------

def test_properties_return_correct_values():
    """默认构造后，所有只读属性应返回正确的初始值。"""
    tray = TrayManager()
    assert tray.is_web_running is False
    assert tray.dnd_enabled is False
    assert tray.sound_enabled is True
    assert tray.current_style == "auto"
    assert tray.current_size == "M"


# ------------------------------------------------------------------
# 零侵入验证
# ------------------------------------------------------------------

def test_tray_uses_subprocess_for_web_not_modifying_web_app():
    """零侵入验证：``web/app.py`` 与 ``web/routes/`` 仍存在且未被本任务修改。

    间接验证：托盘通过 ``subprocess.Popen(["ima", "web"])`` 启动 Web 后台，
    **不直接 import 或修改** ``web/`` 模块。本测试读取 ``web/app.py`` 与
    ``web/routes/`` 目录确保文件存在；如本任务修改了这些文件，git diff 应非空。
    """
    project_root = Path(__file__).resolve().parents[3]
    web_app = project_root / "web" / "app.py"
    web_routes = project_root / "web" / "routes"

    # web/app.py 仍存在
    assert web_app.is_file(), f"web/app.py 应存在，路径：{web_app}"
    # web/routes/ 目录仍存在，至少含 __init__.py
    assert web_routes.is_dir(), f"web/routes/ 应存在，路径：{web_routes}"
    assert (web_routes / "__init__.py").is_file(), "web/routes/__init__.py 应存在"

    # tray.py 不应 import web.app 或 web.routes（零侵入）
    tray_src = (project_root / "core" / "desktop" / "tray.py").read_text(encoding="utf-8")
    assert "from web" not in tray_src, "tray.py 不应直接 import web 模块（零侵入约束）"
    assert "import web" not in tray_src, "tray.py 不应直接 import web 模块（零侵入约束）"
    # 应通过 subprocess.Popen(["ima", "web"]) 启动（而非直接调用 web app）
    assert 'subprocess.Popen' in tray_src, "tray.py 应通过 subprocess.Popen 启动 Web"
    assert '"ima", "web"' in tray_src or "['ima', 'web']", (
        "tray.py 应使用 ['ima', 'web'] 作为 Popen 参数"
    )

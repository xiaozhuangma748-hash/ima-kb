"""REPL 子命令菜单功能测试。

验证：
- SUBCOMMAND_MENU 包含所有预期的主命令
- _show_subcommand_menu 的交互逻辑（radiolist_dialog 选择/取消/占位符参数输入）
- _handle_command 在主命令无参数时触发菜单
- _menu_skip 标志避免递归死循环
- 纯数字参数（/memory 3）直接选择菜单项

注意：
- _show_subcommand_menu 使用 prompt_toolkit 的 radiolist_dialog（弹出选择菜单）
- _prompt_subcmd_params 使用 Rich 的 Prompt.ask 输入参数值
"""
import pytest
from unittest.mock import MagicMock, patch

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import repl as repl_module
from repl import REPL
from rich.prompt import Prompt


def _make_repl(tmp_path, monkeypatch):
    """构建最小化的 REPL 实例（不真正初始化所有依赖）。"""
    monkeypatch.setattr("config.settings.storage_path", tmp_path)
    with patch.object(REPL, "__init__", lambda self: None):
        repl = REPL()
    repl.storage = MagicMock()
    repl.storage.list_documents.return_value = []
    repl.memory_store = MagicMock()
    repl.memory_store.get_data.return_value = {"profile": {}, "tasks": []}
    repl.pet = None
    repl.running = True
    repl.history = []
    repl._menu_skip = False
    repl.workflow_tracker = MagicMock()
    repl.profile_mgr = MagicMock()
    return repl


def _mock_radiolist_dialog(return_value):
    """创建 radiolist_dialog 的 mock。

    radiolist_dialog(...) 返回一个有 .run() 方法的对象，
    .run() 返回用户选择的值。
    """
    class FakeDialog:
        def run(self):
            return return_value

    def fake_factory(*args, **kwargs):
        return FakeDialog()

    return fake_factory


def _mock_prompt_ask(outputs):
    """创建 Prompt.ask 的 mock，按序返回 outputs 中的值。"""
    it = iter(outputs)

    def fake_ask(*args, **kwargs):
        try:
            return next(it)
        except StopIteration:
            return "q"

    return fake_ask


# ============================================================
# 1. SUBCOMMAND_MENU 结构验证
# ============================================================

def test_subcommand_menu_contains_expected_commands():
    """SUBCOMMAND_MENU 应包含所有有子命令的主命令。"""
    expected = {"/memory", "/pet", "/graph", "/sync", "/session", "/tag", "/dedup", "/health"}
    actual = set(REPL.SUBCOMMAND_MENU.keys())
    assert expected.issubset(actual), f"缺少: {expected - actual}"


def test_subcommand_menu_memory_has_six_plus_options():
    """/memory 菜单应至少有 6 个子命令。"""
    items = REPL.SUBCOMMAND_MENU["/memory"]
    assert len(items) >= 6
    assert items[0][0] == ""


def test_subcommand_menu_each_item_is_tuple_of_two():
    """每项应为 (子命令, 描述) 二元组。"""
    for cmd, items in REPL.SUBCOMMAND_MENU.items():
        for item in items:
            assert isinstance(item, tuple) and len(item) == 2
            assert isinstance(item[0], str) and isinstance(item[1], str)


# ============================================================
# 2. _show_subcommand_menu 交互逻辑（使用 radiolist_dialog mock）
# ============================================================

def test_show_menu_select_clear(tmp_path, monkeypatch):
    """用户选 clear 后确认，应返回 'clear'。"""
    repl = _make_repl(tmp_path, monkeypatch)
    # mock radiolist_dialog 返回 "clear"
    monkeypatch.setattr(
        "prompt_toolkit.shortcuts.radiolist_dialog",
        _mock_radiolist_dialog("clear"),
    )
    result = repl._show_subcommand_menu("/memory")
    assert result == "clear"


def test_show_menu_select_default_empty(tmp_path, monkeypatch):
    """选择默认行为（第 1 项，空子命令）应返回空字符串。"""
    repl = _make_repl(tmp_path, monkeypatch)
    monkeypatch.setattr(
        "prompt_toolkit.shortcuts.radiolist_dialog",
        _mock_radiolist_dialog(""),
    )
    result = repl._show_subcommand_menu("/memory")
    assert result == ""


def test_show_menu_cancel_returns_none(tmp_path, monkeypatch):
    """用户取消（Esc/q）应返回 None。"""
    repl = _make_repl(tmp_path, monkeypatch)
    monkeypatch.setattr(
        "prompt_toolkit.shortcuts.radiolist_dialog",
        _mock_radiolist_dialog(None),
    )
    result = repl._show_subcommand_menu("/memory")
    assert result is None


def test_show_menu_exception_returns_none(tmp_path, monkeypatch):
    """radiolist_dialog 抛异常时应返回 None。"""
    repl = _make_repl(tmp_path, monkeypatch)

    def raise_error(*args, **kwargs):
        raise RuntimeError("非交互环境")

    monkeypatch.setattr("prompt_toolkit.shortcuts.radiolist_dialog", raise_error)
    result = repl._show_subcommand_menu("/memory")
    assert result is None


def test_show_menu_select_no_subcmd_items(tmp_path, monkeypatch):
    """菜单表为空时应返回空字符串。"""
    repl = _make_repl(tmp_path, monkeypatch)
    # 临时设置一个空菜单
    original = REPL.SUBCOMMAND_MENU.get("/test_empty")
    try:
        REPL.SUBCOMMAND_MENU["/test_empty"] = []
        result = repl._show_subcommand_menu("/test_empty")
        assert result == ""
    finally:
        if original is None:
            REPL.SUBCOMMAND_MENU.pop("/test_empty", None)


# ============================================================
# 3. 占位符参数输入（_prompt_subcmd_params 使用 Prompt.ask）
# ============================================================

def test_show_menu_placeholder_prompts_for_input(tmp_path, monkeypatch):
    """带占位符的子命令应提示输入参数。"""
    repl = _make_repl(tmp_path, monkeypatch)
    # radiolist_dialog 返回 "topic add <主题>"
    monkeypatch.setattr(
        "prompt_toolkit.shortcuts.radiolist_dialog",
        _mock_radiolist_dialog("topic add <主题>"),
    )
    monkeypatch.setattr(Prompt, "ask", _mock_prompt_ask(["殡葬政策"]))
    result = repl._show_subcommand_menu("/memory")
    assert result == "topic add 殡葬政策"


def test_show_menu_choices_placeholder_validates(tmp_path, monkeypatch):
    """有固定选项的占位符应验证输入。"""
    repl = _make_repl(tmp_path, monkeypatch)
    monkeypatch.setattr(
        "prompt_toolkit.shortcuts.radiolist_dialog",
        _mock_radiolist_dialog("format <格式|table|list|prose|auto|none>"),
    )
    monkeypatch.setattr(Prompt, "ask", _mock_prompt_ask(["3", "table"]))
    result = repl._show_subcommand_menu("/memory")
    assert result == "format table"


def test_show_menu_choices_placeholder_accepts_valid(tmp_path, monkeypatch):
    """有固定选项的占位符接受有效值。"""
    repl = _make_repl(tmp_path, monkeypatch)
    monkeypatch.setattr(
        "prompt_toolkit.shortcuts.radiolist_dialog",
        _mock_radiolist_dialog("format <格式|table|list|prose|auto|none>"),
    )
    monkeypatch.setattr(Prompt, "ask", _mock_prompt_ask(["list"]))
    result = repl._show_subcommand_menu("/memory")
    assert result == "format list"


def test_show_menu_choices_placeholder_empty_cancels(tmp_path, monkeypatch):
    """有固定选项的占位符空输入应取消。"""
    repl = _make_repl(tmp_path, monkeypatch)
    monkeypatch.setattr(
        "prompt_toolkit.shortcuts.radiolist_dialog",
        _mock_radiolist_dialog("format <格式|table|list|prose|auto|none>"),
    )
    monkeypatch.setattr(Prompt, "ask", _mock_prompt_ask([""]))
    result = repl._show_subcommand_menu("/memory")
    assert result is None


def test_prompt_subcmd_params_directly(tmp_path, monkeypatch):
    """直接测试 _prompt_subcmd_params。"""
    repl = _make_repl(tmp_path, monkeypatch)
    monkeypatch.setattr(Prompt, "ask", _mock_prompt_ask(["测试主题"]))
    result = repl._prompt_subcmd_params("/memory", "topic add <主题>")
    assert result == "topic add 测试主题"


def test_prompt_subcmd_params_choices(tmp_path, monkeypatch):
    """_prompt_subcmd_params 有选项的占位符。"""
    repl = _make_repl(tmp_path, monkeypatch)
    monkeypatch.setattr(Prompt, "ask", _mock_prompt_ask(["table"]))
    result = repl._prompt_subcmd_params("/memory", "format <格式|table|list|prose|auto|none>")
    assert result == "format table"


def test_prompt_subcmd_params_no_placeholder(tmp_path, monkeypatch):
    """_prompt_subcmd_params 无占位符时直接返回。"""
    repl = _make_repl(tmp_path, monkeypatch)
    result = repl._prompt_subcmd_params("/memory", "clear")
    assert result == "clear"


# ============================================================
# 4. _handle_command 集成
# ============================================================

def test_handle_command_triggers_menu_when_no_arg(tmp_path, monkeypatch):
    """主命令无参数时应触发菜单。"""
    repl = _make_repl(tmp_path, monkeypatch)
    monkeypatch.setattr(repl, "_show_subcommand_menu", lambda cmd: "")
    called = MagicMock()
    monkeypatch.setattr(repl, "_cmd_memory", called)
    repl._handle_command("/memory")
    called.assert_called_once_with("")


def test_handle_command_menu_cancel_does_nothing(tmp_path, monkeypatch):
    """菜单取消时不执行任何命令。"""
    repl = _make_repl(tmp_path, monkeypatch)
    monkeypatch.setattr(repl, "_show_subcommand_menu", lambda cmd: None)
    called = MagicMock()
    monkeypatch.setattr(repl, "_cmd_memory", called)
    repl._handle_command("/memory")
    called.assert_not_called()


def test_handle_command_menu_select_subcmd_dispatches(tmp_path, monkeypatch):
    """选择子命令后应拼接并重新分发。"""
    repl = _make_repl(tmp_path, monkeypatch)
    call_count = {"menu": 0}

    def mock_menu(cmd):
        call_count["menu"] += 1
        if call_count["menu"] == 1:
            return "clear"
        return None

    monkeypatch.setattr(repl, "_show_subcommand_menu", mock_menu)
    clear_called = MagicMock()
    monkeypatch.setattr(repl, "_memory_clear", clear_called)
    repl._handle_command("/memory")
    assert call_count["menu"] == 1
    clear_called.assert_called_once()


def test_handle_command_menu_skip_flag_prevents_loop(tmp_path, monkeypatch):
    """_menu_skip 标志应防止递归时再次弹菜单。"""
    repl = _make_repl(tmp_path, monkeypatch)
    menu_calls = []

    def mock_menu(cmd):
        menu_calls.append(cmd)
        return ""

    monkeypatch.setattr(repl, "_show_subcommand_menu", mock_menu)
    show_called = MagicMock()
    monkeypatch.setattr(repl, "_memory_show", show_called)
    repl._handle_command("/memory")
    assert len(menu_calls) == 1
    show_called.assert_called_once()


def test_handle_command_with_arg_skips_menu(tmp_path, monkeypatch):
    """主命令带非数字参数时应跳过菜单直接执行。"""
    repl = _make_repl(tmp_path, monkeypatch)
    menu_called = MagicMock()
    monkeypatch.setattr(repl, "_show_subcommand_menu", menu_called)
    cmd_called = MagicMock()
    monkeypatch.setattr(repl, "_cmd_memory", cmd_called)
    repl._handle_command("/memory clear")
    menu_called.assert_not_called()
    cmd_called.assert_called_once_with("clear")


def test_handle_command_alias_triggers_menu(tmp_path, monkeypatch):
    """别名展开后也应触发菜单。"""
    repl = _make_repl(tmp_path, monkeypatch)
    monkeypatch.setattr(repl, "_show_subcommand_menu", lambda cmd: None)
    repl._handle_command("/m")


def test_alias_then_menu_works(tmp_path, monkeypatch):
    """别名 /m 输入后应展开为 /memory 并弹菜单。"""
    repl = _make_repl(tmp_path, monkeypatch)
    captured_cmd = []

    def mock_menu(cmd):
        captured_cmd.append(cmd)
        return None

    monkeypatch.setattr(repl, "_show_subcommand_menu", mock_menu)
    repl._handle_command("/m")
    assert captured_cmd == ["/memory"]


def test_help_command_not_in_menu(tmp_path, monkeypatch):
    """/help 不在菜单表中，应直接执行。"""
    repl = _make_repl(tmp_path, monkeypatch)
    menu_called = MagicMock()
    monkeypatch.setattr(repl, "_show_subcommand_menu", menu_called)
    repl._handle_command("/help")
    menu_called.assert_not_called()


# ============================================================
# 5. 纯数字参数（/memory 3 直接选择菜单项）
# ============================================================

def test_handle_command_numeric_arg_triggers_menu_select(tmp_path, monkeypatch):
    """/memory 3 应直接选择菜单第 3 项（format）并提示输入参数。"""
    repl = _make_repl(tmp_path, monkeypatch)
    monkeypatch.setattr(Prompt, "ask", _mock_prompt_ask(["table"]))
    cmd_called = MagicMock()
    monkeypatch.setattr(repl, "_cmd_memory", cmd_called)
    repl._handle_command("/memory 3")
    cmd_called.assert_called_once_with("format table")


def test_handle_command_numeric_arg_no_placeholder(tmp_path, monkeypatch):
    """/memory 2 (clear) 无占位符，直接执行。"""
    repl = _make_repl(tmp_path, monkeypatch)
    clear_called = MagicMock()
    monkeypatch.setattr(repl, "_memory_clear", clear_called)
    repl._handle_command("/memory 2")
    clear_called.assert_called_once()


def test_handle_command_numeric_arg_invalid_range(tmp_path, monkeypatch):
    """/memory 999 超出范围应报错。"""
    repl = _make_repl(tmp_path, monkeypatch)
    cmd_called = MagicMock()
    monkeypatch.setattr(repl, "_cmd_memory", cmd_called)
    repl._handle_command("/memory 999")
    cmd_called.assert_not_called()


def test_handle_command_numeric_arg_with_alias(tmp_path, monkeypatch):
    """/m 3 别名也应支持数字参数。"""
    repl = _make_repl(tmp_path, monkeypatch)
    monkeypatch.setattr(Prompt, "ask", _mock_prompt_ask(["table"]))
    cmd_called = MagicMock()
    monkeypatch.setattr(repl, "_cmd_memory", cmd_called)
    repl._handle_command("/m 3")
    cmd_called.assert_called_once_with("format table")

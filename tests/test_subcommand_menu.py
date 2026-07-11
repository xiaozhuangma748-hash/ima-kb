"""REPL 子命令菜单功能测试。

注意：子命令菜单已禁用（SUBCOMMAND_MENU = {}），用户偏好直接输入命令。
本文件验证禁用后的行为正确性，以及 _show_subcommand_menu / _prompt_subcmd_params
等底层方法在菜单为空时的降级行为。
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


# ============================================================
# 1. SUBCOMMAND_MENU 已禁用
# ============================================================

def test_subcommand_menu_is_disabled():
    """SUBCOMMAND_MENU 应为空字典（菜单已禁用）。"""
    assert REPL.SUBCOMMAND_MENU == {}


def test_subcommand_menu_contains_expected_commands():
    """SUBCOMMAND_MENU 为空，不包含任何命令（已禁用）。"""
    assert REPL.SUBCOMMAND_MENU == {}


def test_subcommand_menu_memory_has_six_plus_options():
    """菜单已禁用，/memory 不在菜单中。"""
    assert "/memory" not in REPL.SUBCOMMAND_MENU


def test_subcommand_menu_each_item_is_tuple_of_two():
    """菜单已禁用，无需验证元组结构。"""
    assert REPL.SUBCOMMAND_MENU == {}


# ============================================================
# 2. _show_subcommand_menu 降级行为（菜单为空时返回 ""）
# ============================================================

def test_show_menu_select_clear(tmp_path, monkeypatch):
    """菜单已禁用，_show_subcommand_menu 应返回空字符串。"""
    repl = _make_repl(tmp_path, monkeypatch)
    result = repl._show_subcommand_menu("/memory")
    assert result == ""


def test_show_menu_select_default_empty(tmp_path, monkeypatch):
    """菜单已禁用，应返回空字符串。"""
    repl = _make_repl(tmp_path, monkeypatch)
    result = repl._show_subcommand_menu("/memory")
    assert result == ""


def test_show_menu_cancel_returns_none(tmp_path, monkeypatch):
    """菜单已禁用，应返回空字符串而非 None。"""
    repl = _make_repl(tmp_path, monkeypatch)
    result = repl._show_subcommand_menu("/memory")
    assert result == ""


def test_show_menu_exception_returns_none(tmp_path, monkeypatch):
    """菜单已禁用，不应抛异常。"""
    repl = _make_repl(tmp_path, monkeypatch)
    result = repl._show_subcommand_menu("/memory")
    assert result == ""


def test_show_menu_select_no_subcmd_items(tmp_path, monkeypatch):
    """菜单表为空时应返回空字符串。"""
    repl = _make_repl(tmp_path, monkeypatch)
    original = REPL.SUBCOMMAND_MENU.get("/test_empty")
    try:
        REPL.SUBCOMMAND_MENU["/test_empty"] = []
        result = repl._show_subcommand_menu("/test_empty")
        assert result == ""
    finally:
        if original is None:
            REPL.SUBCOMMAND_MENU.pop("/test_empty", None)


# ============================================================
# 3. 占位符参数输入（_prompt_subcmd_params）
# ============================================================

def test_show_menu_placeholder_prompts_for_input(tmp_path, monkeypatch):
    """_prompt_subcmd_params 带占位符应提示输入参数。"""
    repl = _make_repl(tmp_path, monkeypatch)
    monkeypatch.setattr(Prompt, "ask", lambda *a, **kw: "殡葬政策")
    result = repl._prompt_subcmd_params("/memory", "topic add <主题>")
    assert result == "topic add 殡葬政策"


def test_show_menu_choices_placeholder_validates(tmp_path, monkeypatch):
    """_prompt_subcmd_params 有固定选项应验证输入。"""
    repl = _make_repl(tmp_path, monkeypatch)
    call_count = [0]
    def fake_ask(*a, **kw):
        call_count[0] += 1
        return "table" if call_count[0] > 1 else "3"
    monkeypatch.setattr(Prompt, "ask", fake_ask)
    result = repl._prompt_subcmd_params("/memory", "format <格式|table|list|prose|auto|none>")
    assert result == "format table"


def test_show_menu_choices_placeholder_accepts_valid(tmp_path, monkeypatch):
    """_prompt_subcmd_params 有固定选项接受有效值。"""
    repl = _make_repl(tmp_path, monkeypatch)
    monkeypatch.setattr(Prompt, "ask", lambda *a, **kw: "list")
    result = repl._prompt_subcmd_params("/memory", "format <格式|table|list|prose|auto|none>")
    assert result == "format list"


def test_show_menu_choices_placeholder_empty_cancels(tmp_path, monkeypatch):
    """_prompt_subcmd_params 有固定选项空输入应取消。"""
    repl = _make_repl(tmp_path, monkeypatch)
    monkeypatch.setattr(Prompt, "ask", lambda *a, **kw: "")
    result = repl._prompt_subcmd_params("/memory", "format <格式|table|list|prose|auto|none>")
    assert result is None


def test_prompt_subcmd_params_directly(tmp_path, monkeypatch):
    """直接测试 _prompt_subcmd_params。"""
    repl = _make_repl(tmp_path, monkeypatch)
    monkeypatch.setattr(Prompt, "ask", lambda *a, **kw: "测试主题")
    result = repl._prompt_subcmd_params("/memory", "topic add <主题>")
    assert result == "topic add 测试主题"


def test_prompt_subcmd_params_choices(tmp_path, monkeypatch):
    """_prompt_subcmd_params 有选项的占位符。"""
    repl = _make_repl(tmp_path, monkeypatch)
    monkeypatch.setattr(Prompt, "ask", lambda *a, **kw: "table")
    result = repl._prompt_subcmd_params("/memory", "format <格式|table|list|prose|auto|none>")
    assert result == "format table"


def test_prompt_subcmd_params_no_placeholder(tmp_path, monkeypatch):
    """_prompt_subcmd_params 无占位符时直接返回。"""
    repl = _make_repl(tmp_path, monkeypatch)
    result = repl._prompt_subcmd_params("/memory", "clear")
    assert result == "clear"


# ============================================================
# 4. _handle_command 集成（菜单禁用后直接执行）
# ============================================================

def test_handle_command_triggers_menu_when_no_arg(tmp_path, monkeypatch):
    """菜单已禁用，主命令无参数时应直接执行默认行为。"""
    repl = _make_repl(tmp_path, monkeypatch)
    called = MagicMock()
    monkeypatch.setattr(repl, "_cmd_memory", called)
    repl._handle_command("/memory")
    called.assert_called_once_with("")


def test_handle_command_menu_cancel_does_nothing(tmp_path, monkeypatch):
    """菜单已禁用，不会取消，直接执行。"""
    repl = _make_repl(tmp_path, monkeypatch)
    called = MagicMock()
    monkeypatch.setattr(repl, "_cmd_memory", called)
    repl._handle_command("/memory")
    called.assert_called_once_with("")


def test_handle_command_menu_select_subcmd_dispatches(tmp_path, monkeypatch):
    """菜单已禁用，带参数直接执行子命令。"""
    repl = _make_repl(tmp_path, monkeypatch)
    clear_called = MagicMock()
    monkeypatch.setattr(repl, "_memory_clear", clear_called)
    repl._handle_command("/memory clear")
    clear_called.assert_called_once()


def test_handle_command_menu_skip_flag_prevents_loop(tmp_path, monkeypatch):
    """菜单已禁用，_menu_skip 标志不影响行为。"""
    repl = _make_repl(tmp_path, monkeypatch)
    show_called = MagicMock()
    monkeypatch.setattr(repl, "_memory_show", show_called)
    repl._handle_command("/memory")
    # 菜单禁用后 _handle_command 走 dict 派发，不会调 _memory_show
    # 但 _cmd_memory 会被调用
    cmd_called = MagicMock()
    monkeypatch.setattr(repl, "_cmd_memory", cmd_called)
    repl._handle_command("/memory")
    cmd_called.assert_called()


def test_handle_command_with_arg_skips_menu(tmp_path, monkeypatch):
    """主命令带非数字参数时应直接执行。"""
    repl = _make_repl(tmp_path, monkeypatch)
    cmd_called = MagicMock()
    monkeypatch.setattr(repl, "_cmd_memory", cmd_called)
    repl._handle_command("/memory clear")
    cmd_called.assert_called_once_with("clear")


def test_handle_command_alias_triggers_menu(tmp_path, monkeypatch):
    """别名展开后也应直接执行（菜单已禁用）。"""
    repl = _make_repl(tmp_path, monkeypatch)
    cmd_called = MagicMock()
    monkeypatch.setattr(repl, "_cmd_memory", cmd_called)
    repl._handle_command("/m")
    cmd_called.assert_called_once_with("")


def test_alias_then_menu_works(tmp_path, monkeypatch):
    """别名 /m 输入后应展开为 /memory 并直接执行。"""
    repl = _make_repl(tmp_path, monkeypatch)
    cmd_called = MagicMock()
    monkeypatch.setattr(repl, "_cmd_memory", cmd_called)
    repl._handle_command("/m")
    cmd_called.assert_called_once_with("")


def test_help_command_not_in_menu(tmp_path, monkeypatch):
    """/help 不在菜单表中，应直接执行。"""
    repl = _make_repl(tmp_path, monkeypatch)
    cmd_called = MagicMock()
    monkeypatch.setattr(repl, "_cmd_help", cmd_called)
    repl._handle_command("/help")
    cmd_called.assert_called_once_with("")


# ============================================================
# 5. 纯数字参数（菜单禁用后数字参数作为普通参数处理）
# ============================================================

def test_handle_command_numeric_arg_triggers_menu_select(tmp_path, monkeypatch):
    """菜单已禁用，/memory 3 应作为普通参数传递。"""
    repl = _make_repl(tmp_path, monkeypatch)
    cmd_called = MagicMock()
    monkeypatch.setattr(repl, "_cmd_memory", cmd_called)
    repl._handle_command("/memory 3")
    cmd_called.assert_called_once_with("3")


def test_handle_command_numeric_arg_no_placeholder(tmp_path, monkeypatch):
    """菜单已禁用，/memory 2 作为普通参数。"""
    repl = _make_repl(tmp_path, monkeypatch)
    cmd_called = MagicMock()
    monkeypatch.setattr(repl, "_cmd_memory", cmd_called)
    repl._handle_command("/memory 2")
    cmd_called.assert_called_once_with("2")


def test_handle_command_numeric_arg_invalid_range(tmp_path, monkeypatch):
    """菜单已禁用，/memory 999 作为普通参数。"""
    repl = _make_repl(tmp_path, monkeypatch)
    cmd_called = MagicMock()
    monkeypatch.setattr(repl, "_cmd_memory", cmd_called)
    repl._handle_command("/memory 999")
    cmd_called.assert_called_once_with("999")


def test_handle_command_numeric_arg_with_alias(tmp_path, monkeypatch):
    """菜单已禁用，/m 3 别名也应作为普通参数。"""
    repl = _make_repl(tmp_path, monkeypatch)
    cmd_called = MagicMock()
    monkeypatch.setattr(repl, "_cmd_memory", cmd_called)
    repl._handle_command("/m 3")
    cmd_called.assert_called_once_with("3")

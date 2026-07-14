"""Agent CLI 命令测试。"""
from unittest.mock import MagicMock, patch

from core.cli.commands.agent import AgentMixin, _AgentStatus


class _DummyREPL(AgentMixin):
    pass


def test_hide_thoughts_live_reused():
    """Hide Thoughts 模式：Live 在 tool/result 时停止，llm_start 时重启。"""
    repl = _DummyREPL()
    mock_live = MagicMock()

    with patch("core.cli.commands.agent.Live", return_value=mock_live), \
         patch("core.cli.commands.agent.console.print") as mock_print:
        on_step, stop, t0, step_n = repl._make_agent_on_step(show_thoughts=False)

        on_step("llm_start", "Step 1")
        on_step("tool", "search 生态安葬")
        on_step("result", "some result content")
        on_step("llm_start", "Step 2")
        on_step("done", "")
        stop()

    # Live 在 tool/result 时停止，在下一个 llm_start 时重启
    assert mock_live.start.call_count == 2, "Live 应启动两次（Step 1 和 Step 2）"
    assert mock_live.stop.call_count >= 2, "Live 应在 tool/result 时停止"
    # tool 和 result 应打印永久行
    assert mock_print.call_count >= 2, "tool 和 result 各打印一行"


def test_show_thoughts_no_live():
    """Show Thoughts 模式不使用 _AgentStatus Live。"""
    repl = _DummyREPL()

    with patch("core.cli.commands.agent.console.print"), \
         patch("core.cli.commands.agent.Live") as live_factory:
        on_step, stop, *_ = repl._make_agent_on_step(show_thoughts=True)

        on_step("llm_start", "")
        on_step("thought", "I need to search")
        on_step("tool", "search")
        on_step("result", "some result")
        on_step("done", "")
        stop()

    # Show Thoughts 模式用 Live 来显示 Spinner，但 renderable 是 Spinner 不是 _AgentStatus
    # 关键验证：不依赖 _AgentStatus 的动态刷新
    for call in live_factory.call_args_list:
        args, kwargs = call
        renderable = args[0] if args else kwargs.get("renderable")
        assert not isinstance(renderable, _AgentStatus), \
            "Show Thoughts 不应使用 _AgentStatus"


def test_step_count_hide_thoughts():
    """Hide Thoughts 模式下 step_n 应正确递增（在 llm_start 时计数）。"""
    repl = _DummyREPL()

    with patch("core.cli.commands.agent.Live"):
        on_step, stop, t0, step_n = repl._make_agent_on_step(show_thoughts=False)

        on_step("llm_start", "Step 1")
        on_step("tool", "search test")
        on_step("result", "result")
        on_step("llm_start", "Step 2")
        on_step("tool", "read doc1")
        on_step("result", "result2")
        on_step("llm_start", "Step 3")
        on_step("done", "final answer")
        stop()

    assert step_n[0] == 3, f"3 次 LLM 调用应计为 3 步，实际 {step_n[0]}"


def test_step_count_show_thoughts():
    """Show Thoughts 模式下 step_n 也应正确递增。"""
    repl = _DummyREPL()

    with patch("core.cli.commands.agent.Live"), \
         patch("core.cli.commands.agent.console.print"):
        on_step, stop, t0, step_n = repl._make_agent_on_step(show_thoughts=True)

        on_step("llm_start", "Step 1")
        on_step("thought", "thinking 1")
        on_step("tool", "search test")
        on_step("result", "result")
        on_step("llm_start", "Step 2")
        on_step("done", "final answer")
        stop()

    assert step_n[0] == 2, f"2 次 LLM 调用应计为 2 步，实际 {step_n[0]}"


def test_agent_status_thinking():
    """_AgentStatus 在 thinking 模式下显示耗时。"""
    status = _AgentStatus()
    status.set_thinking()
    assert status._thinking is True
    # __rich_console__ 应 yield Spinner 对象
    from rich.console import Console
    console = Console()
    results = list(status.__rich_console__(console, None))
    assert len(results) == 1
    from rich.spinner import Spinner
    assert isinstance(results[0], Spinner)


def test_agent_status_static():
    """_AgentStatus 在 static 模式下显示工具名和详情。"""
    status = _AgentStatus()
    status.set_static("search", "1234 chars")
    assert status._thinking is False
    assert status._label == "search"
    assert status._detail == "1234 chars"

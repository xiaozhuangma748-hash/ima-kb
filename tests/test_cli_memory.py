"""CLI memory 子命令测试（Group 5: CLI/REPL 不对等）。

验证 ima memory 的各子命令能正确写入记忆。
"""
import pytest
from pathlib import Path
from click.testing import CliRunner

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from run import cli


def _run(cmd_args, env_storage_path):
    """运行 CLI 命令，返回 (exit_code, output)。"""
    runner = CliRunner()
    # 通过环境变量指定 storage 路径，避免污染真实数据
    import os
    env = os.environ.copy()
    env["IMA_STORAGE_PATH"] = str(env_storage_path)
    # 让 MemoryStore 使用指定路径
    env["IMA_STORAGE"] = str(env_storage_path)
    result = runner.invoke(cli, cmd_args, env=env, catch_exceptions=False)
    return result.exit_code, result.output


def test_cli_memory_show(tmp_path, monkeypatch):
    """ima memory 无参数应显示概览。"""
    monkeypatch.setenv("IMA_STORAGE_PATH", str(tmp_path))
    # 让 config.settings 使用 tmp_path
    monkeypatch.setattr("config.settings.storage_path", tmp_path, raising=False)
    monkeypatch.setattr("core.memory.store.MemoryStore._default_path", tmp_path, raising=False)
    runner = CliRunner()
    result = runner.invoke(cli, ["memory"], catch_exceptions=False)
    assert result.exit_code == 0
    assert "记忆概览" in result.output or "偏好格式" in result.output


def test_cli_memory_clear(tmp_path, monkeypatch):
    """ima memory clear 应清空记忆。"""
    monkeypatch.setattr("config.settings.storage_path", tmp_path, raising=False)
    runner = CliRunner()
    result = runner.invoke(cli, ["memory", "clear"], catch_exceptions=False)
    assert result.exit_code == 0
    assert "清空" in result.output


def test_cli_memory_format(tmp_path, monkeypatch):
    """ima memory format table 应设置格式偏好。"""
    monkeypatch.setattr("config.settings.storage_path", tmp_path, raising=False)
    runner = CliRunner()
    result = runner.invoke(cli, ["memory", "format", "table"], catch_exceptions=False)
    assert result.exit_code == 0
    assert "table" in result.output

    # 验证确实写入了
    from core.memory.store import MemoryStore
    from core.memory.profile import ProfileManager
    store = MemoryStore(storage_path=tmp_path)
    profile = ProfileManager(store).get_profile()
    assert profile.preferred_format == "table"


def test_cli_memory_format_invalid(tmp_path, monkeypatch):
    """ima memory format invalid 应提示无效。"""
    monkeypatch.setattr("config.settings.storage_path", tmp_path, raising=False)
    runner = CliRunner()
    result = runner.invoke(cli, ["memory", "format", "invalid_value"], catch_exceptions=False)
    assert result.exit_code == 0
    assert "无效" in result.output


def test_cli_memory_style(tmp_path, monkeypatch):
    """ima memory style scholar 应设置风格偏好。"""
    monkeypatch.setattr("config.settings.storage_path", tmp_path, raising=False)
    runner = CliRunner()
    result = runner.invoke(cli, ["memory", "style", "scholar"], catch_exceptions=False)
    assert result.exit_code == 0
    assert "scholar" in result.output

    from core.memory.store import MemoryStore
    from core.memory.profile import ProfileManager
    store = MemoryStore(storage_path=tmp_path)
    profile = ProfileManager(store).get_profile()
    assert profile.preferred_style == "scholar"


def test_cli_memory_topic_add(tmp_path, monkeypatch):
    """ima memory topic add <主题> 应添加主题。"""
    monkeypatch.setattr("config.settings.storage_path", tmp_path, raising=False)
    runner = CliRunner()
    result = runner.invoke(cli, ["memory", "topic", "add", "殡葬政策"], catch_exceptions=False)
    assert result.exit_code == 0
    assert "殡葬政策" in result.output

    from core.memory.store import MemoryStore
    from core.memory.profile import ProfileManager
    store = MemoryStore(storage_path=tmp_path)
    profile = ProfileManager(store).get_profile()
    assert "殡葬政策" in profile.focus_topics


def test_cli_memory_topic_remove(tmp_path, monkeypatch):
    """ima memory topic remove <主题> 应移除主题。"""
    monkeypatch.setattr("config.settings.storage_path", tmp_path, raising=False)
    # 先添加
    from core.memory.store import MemoryStore
    from core.memory.profile import ProfileManager
    store = MemoryStore(storage_path=tmp_path)
    ProfileManager(store).add_topic("测试主题")

    # 再移除
    runner = CliRunner()
    result = runner.invoke(cli, ["memory", "topic", "remove", "测试主题"], catch_exceptions=False)
    assert result.exit_code == 0
    assert "测试主题" in result.output

    # 重新加载 store 读取最新数据（CLI 操作由另一个 MemoryStore 实例完成）
    store2 = MemoryStore(storage_path=tmp_path)
    profile = ProfileManager(store2).get_profile()
    assert "测试主题" not in profile.focus_topics


def test_cli_memory_region_add(tmp_path, monkeypatch):
    """ima memory region add <地区> 应添加地区。"""
    monkeypatch.setattr("config.settings.storage_path", tmp_path, raising=False)
    runner = CliRunner()
    result = runner.invoke(cli, ["memory", "region", "add", "杭州市"], catch_exceptions=False)
    assert result.exit_code == 0
    assert "杭州市" in result.output

    from core.memory.store import MemoryStore
    from core.memory.profile import ProfileManager
    store = MemoryStore(storage_path=tmp_path)
    profile = ProfileManager(store).get_profile()
    assert "杭州市" in profile.focus_regions


def test_cli_memory_task_add(tmp_path, monkeypatch):
    """ima memory task add <描述> 应添加任务。"""
    monkeypatch.setattr("config.settings.storage_path", tmp_path, raising=False)
    runner = CliRunner()
    result = runner.invoke(cli, ["memory", "task", "add", "测试任务"], catch_exceptions=False)
    assert result.exit_code == 0
    assert "测试任务" in result.output

    from core.memory.store import MemoryStore
    from core.memory.tasks import TaskManager
    store = MemoryStore(storage_path=tmp_path)
    tasks = TaskManager(store).get_all_tasks()
    assert len(tasks) == 1
    assert tasks[0].description == "测试任务"


def test_cli_memory_task_done(tmp_path, monkeypatch):
    """ima memory task done <id> 应标记任务完成。"""
    monkeypatch.setattr("config.settings.storage_path", tmp_path, raising=False)
    # 先添加任务
    from core.memory.store import MemoryStore
    from core.memory.tasks import TaskManager
    store = MemoryStore(storage_path=tmp_path)
    task_id = TaskManager(store).add_task("待完成任务")

    # 标记完成
    runner = CliRunner()
    result = runner.invoke(cli, ["memory", "task", "done", task_id[:12]], catch_exceptions=False)
    assert result.exit_code == 0
    assert "completed" in result.output

    # 重新加载 store 读取最新数据（CLI 操作由另一个 MemoryStore 实例完成）
    store2 = MemoryStore(storage_path=tmp_path)
    tasks = TaskManager(store2).get_all_tasks()
    assert tasks[0].status == "completed"


def test_cli_memory_tasks_list(tmp_path, monkeypatch):
    """ima memory tasks 应列出任务。"""
    monkeypatch.setattr("config.settings.storage_path", tmp_path, raising=False)
    from core.memory.store import MemoryStore
    from core.memory.tasks import TaskManager
    store = MemoryStore(storage_path=tmp_path)
    TaskManager(store).add_task("任务一")
    TaskManager(store).add_task("任务二")

    runner = CliRunner()
    result = runner.invoke(cli, ["memory", "tasks"], catch_exceptions=False)
    assert result.exit_code == 0
    assert "任务一" in result.output
    assert "任务二" in result.output

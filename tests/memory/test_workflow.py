"""工作流模式测试。"""
import pytest
from core.memory.workflow import WorkflowTracker
from core.memory.store import MemoryStore


def test_record_command_no_suggestion_initially(tmp_path):
    """首次执行命令时无推荐。"""
    store = MemoryStore(storage_path=tmp_path)
    tracker = WorkflowTracker(store)
    assert tracker.suggest_next("ingest") is None


def test_suggest_next_after_pattern_formed(tmp_path):
    """形成模式后能推荐下一步。"""
    store = MemoryStore(storage_path=tmp_path)
    tracker = WorkflowTracker(store)
    # 重复 ingest → analyze 序列 3 次
    for _ in range(3):
        tracker.record_command("ingest")
        tracker.record_command("analyze")

    suggestion = tracker.suggest_next("ingest")
    assert suggestion == "analyze"


def test_suggest_next_returns_none_for_unknown_cmd(tmp_path):
    """未形成模式的命令无推荐。"""
    store = MemoryStore(storage_path=tmp_path)
    tracker = WorkflowTracker(store)
    tracker.record_command("ingest")
    tracker.record_command("analyze")
    assert tracker.suggest_next("search") is None


def test_pattern_count_increments(tmp_path):
    """重复序列计数递增。"""
    store = MemoryStore(storage_path=tmp_path)
    tracker = WorkflowTracker(store)
    tracker.record_command("ingest")
    tracker.record_command("analyze")
    tracker.record_command("ingest")
    tracker.record_command("analyze")

    data = store.get_data()
    patterns = data["workflow"]["patterns"]
    assert len(patterns) == 1
    assert patterns[0]["count"] == 2


def test_suggestions_disabled(tmp_path):
    """suggestions_enabled=False 时不推荐。"""
    store = MemoryStore(storage_path=tmp_path)
    store.update("workflow", "suggestions_enabled", False)
    tracker = WorkflowTracker(store)
    for _ in range(3):
        tracker.record_command("ingest")
        tracker.record_command("analyze")
    assert tracker.suggest_next("ingest") is None


def test_window_timeout(tmp_path):
    """超过 30 分钟窗口的命令不形成模式。"""
    store = MemoryStore(storage_path=tmp_path)
    tracker = WorkflowTracker(store)
    # 第一组命令（旧时间）
    tracker.record_command("ingest", timestamp="2026-07-01T10:00:00")
    tracker.record_command("analyze", timestamp="2026-07-01T10:05:00")
    # 第二组命令（新时间，间隔 > 30 分钟）
    tracker.record_command("ingest", timestamp="2026-07-01T11:00:00")
    tracker.record_command("analyze", timestamp="2026-07-01T11:05:00")

    # 仍然能形成模式（count=2，因为两组都是 ingest→analyze）
    suggestion = tracker.suggest_next("ingest")
    assert suggestion == "analyze"


def test_persistence_across_instances(tmp_path):
    """工作流模式跨实例持久化。"""
    store = MemoryStore(storage_path=tmp_path)
    tracker1 = WorkflowTracker(store)
    tracker1.record_command("ingest")
    tracker1.record_command("analyze")
    store.save()

    store2 = MemoryStore(storage_path=tmp_path)
    tracker2 = WorkflowTracker(store2)
    # 再重复一次让 count 达到 2
    tracker2.record_command("ingest")
    tracker2.record_command("analyze")
    assert tracker2.suggest_next("ingest") == "analyze"


# ---- Group 1: 数据累积无清理 ----

def test_clear_patterns(tmp_path):
    """clear_patterns 清空所有模式记录。"""
    store = MemoryStore(storage_path=tmp_path)
    tracker = WorkflowTracker(store)
    for _ in range(3):
        tracker.record_command("ingest")
        tracker.record_command("analyze")
    assert len(store.get_data()["workflow"]["patterns"]) > 0
    count = tracker.clear_patterns()
    assert count > 0
    assert store.get_data()["workflow"]["patterns"] == []


def test_set_suggestions_enabled(tmp_path):
    """set_suggestions_enabled 切换推荐开关。"""
    store = MemoryStore(storage_path=tmp_path)
    tracker = WorkflowTracker(store)
    # 默认启用
    assert store.get_data()["workflow"].get("suggestions_enabled", True) is True
    # 关闭
    tracker.set_suggestions_enabled(False)
    assert store.get_data()["workflow"]["suggestions_enabled"] is False
    # 再启用
    tracker.set_suggestions_enabled(True)
    assert store.get_data()["workflow"]["suggestions_enabled"] is True


def test_max_patterns_pruning(tmp_path):
    """超过 MAX_PATTERNS 上限时自动淘汰低频模式。"""
    from core.memory.workflow import MAX_PATTERNS
    store = MemoryStore(storage_path=tmp_path)
    tracker = WorkflowTracker(store)
    # 生成 MAX_PATTERNS + 10 个不同的命令对
    for i in range(MAX_PATTERNS + 10):
        tracker.record_command(f"cmd_a_{i}")
        tracker.record_command(f"cmd_b_{i}")
    patterns = store.get_data()["workflow"]["patterns"]
    assert len(patterns) <= MAX_PATTERNS

"""TodoManager 单元测试。

覆盖：
- 增删改查（add/list_day/update_status/edit/set_priority/delete/clear_day）
- 序号引用 + id 前缀引用
- 排序（状态 → 优先级 → 创建时间）
- 跨天处理（get_yesterday_pending/carry_over/archive_pending/should_ask_carry）
- 历史（list_history/get_day/stats_day）
- 持久化（reload/损坏文件容错）
- 上限保护（MAX_TASKS_PER_DAY/MAX_HISTORY_DAYS 清理）
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from core.todo.manager import (
    TodoManager,
    TodoItem,
    MAX_HISTORY_DAYS,
    MAX_TASKS_PER_DAY,
)


@pytest.fixture
def tmp_mgr(tmp_path: Path) -> TodoManager:
    """用临时目录的 TodoManager。"""
    return TodoManager(storage_path=tmp_path)


# ---- 增删改查 ----

class TestAdd:
    def test_add_basic(self, tmp_mgr: TodoManager):
        item = tmp_mgr.add("写报告")
        assert item.description == "写报告"
        assert item.status == "pending"
        assert item.priority == "medium"
        assert item.note == ""
        assert item.date == datetime.now().strftime("%Y-%m-%d")
        assert item.completed_at is None
        assert item.id.startswith("todo_")

    def test_add_with_priority_and_note(self, tmp_mgr: TodoManager):
        item = tmp_mgr.add("紧急任务", priority="high", note="需今天完成")
        assert item.priority == "high"
        assert item.note == "需今天完成"

    def test_add_invalid_priority_falls_back_to_medium(self, tmp_mgr: TodoManager):
        item = tmp_mgr("任务", priority="urgent") if False else tmp_mgr.add("任务", priority="urgent")
        assert item.priority == "medium"

    def test_add_to_specific_date(self, tmp_mgr: TodoManager):
        item = tmp_mgr.add("昨日任务", date_str="2026-07-10")
        assert item.date == "2026-07-10"
        # 验证持久化
        items = tmp_mgr.list_day("2026-07-10")
        assert len(items) == 1

    def test_add_exceeds_daily_limit(self, tmp_mgr: TodoManager):
        """超过单日上限应抛 ValueError。"""
        for i in range(MAX_TASKS_PER_DAY):
            tmp_mgr.add(f"任务{i}")
        with pytest.raises(ValueError, match="单日任务已达上限"):
            tmp_mgr.add("超额任务")


class TestListAndSort:
    def test_list_empty_day(self, tmp_mgr: TodoManager):
        items = tmp_mgr.list_day()
        assert items == []

    def test_list_sorts_by_status_then_priority(self, tmp_mgr: TodoManager):
        """pending 在前，done 在后；同状态按优先级 high→low。"""
        a = tmp_mgr.add("低优先级", priority="low")
        b = tmp_mgr.add("高优先级", priority="high")
        c = tmp_mgr.add("中优先级", priority="medium")
        # 把 a 标记完成
        tmp_mgr.update_status("1", "done")  # 序号 1 是低优先级（先添加）
        items = tmp_mgr.list_day()
        # 排序后：pending(b high) → pending(c medium) → done(a low)
        assert items[0].description == "高优先级"
        assert items[1].description == "中优先级"
        assert items[2].description == "低优先级"
        assert items[2].status == "done"


class TestUpdateStatus:
    def test_done_by_index(self, tmp_mgr: TodoManager):
        tmp_mgr.add("任务A")
        item = tmp_mgr.update_status("1", "done")
        assert item is not None
        assert item.status == "done"
        assert item.completed_at is not None

    def test_done_by_id_prefix(self, tmp_mgr: TodoManager):
        added = tmp_mgr.add("任务B")
        # 用完整 id
        item = tmp_mgr.update_status(added.id, "done")
        assert item is not None
        assert item.status == "done"

    def test_done_by_id_short_prefix(self, tmp_mgr: TodoManager):
        added = tmp_mgr.add("任务C")
        # 用前缀（todo_ 后面的部分）
        prefix = added.id[:10]
        item = tmp_mgr.update_status(prefix, "done")
        assert item is not None

    def test_reopen_clears_completed_at(self, tmp_mgr: TodoManager):
        tmp_mgr.add("任务D")
        tmp_mgr.update_status("1", "done")
        item = tmp_mgr.update_status("1", "pending")
        assert item.status == "pending"
        assert item.completed_at is None

    def test_cancel(self, tmp_mgr: TodoManager):
        tmp_mgr.add("任务E")
        item = tmp_mgr.update_status("1", "cancelled")
        assert item.status == "cancelled"

    def test_invalid_status_raises(self, tmp_mgr: TodoManager):
        tmp_mgr.add("任务F")
        with pytest.raises(ValueError, match="无效状态"):
            tmp_mgr.update_status("1", "invalid")

    def test_not_found_returns_none(self, tmp_mgr: TodoManager):
        tmp_mgr.add("任务G")
        assert tmp_mgr.update_status("999", "done") is None
        assert tmp_mgr.update_status("nonexistent_id", "done") is None


class TestEdit:
    def test_edit_description(self, tmp_mgr: TodoManager):
        tmp_mgr.add("旧描述")
        item = tmp_mgr.edit("1", "新描述")
        assert item.description == "新描述"

    def test_edit_not_found(self, tmp_mgr: TodoManager):
        assert tmp_mgr.edit("999", "新描述") is None


class TestSetPriority:
    def test_set_priority(self, tmp_mgr: TodoManager):
        tmp_mgr.add("任务")
        item = tmp_mgr.set_priority("1", "high")
        assert item.priority == "high"

    def test_invalid_priority_raises(self, tmp_mgr: TodoManager):
        tmp_mgr.add("任务")
        with pytest.raises(ValueError, match="无效优先级"):
            tmp_mgr.set_priority("1", "urgent")


class TestDelete:
    def test_delete_by_index(self, tmp_mgr: TodoManager):
        tmp_mgr.add("任务1")
        tmp_mgr.add("任务2")
        ok = tmp_mgr.delete("1")
        assert ok is True
        items = tmp_mgr.list_day()
        assert len(items) == 1
        assert items[0].description == "任务2"

    def test_delete_not_found(self, tmp_mgr: TodoManager):
        assert tmp_mgr.delete("999") is False

    def test_delete_clears_empty_date(self, tmp_mgr: TodoManager):
        """删除某天最后一条任务后，该日期键应被清理。"""
        tmp_mgr.add("唯一任务", date_str="2026-07-10")
        tmp_mgr.delete("1", date_str="2026-07-10")
        data = tmp_mgr._load()
        assert "2026-07-10" not in data["days"]


class TestClearDay:
    def test_clear_day(self, tmp_mgr: TodoManager):
        tmp_mgr.add("A")
        tmp_mgr.add("B")
        count = tmp_mgr.clear_day()
        assert count == 2
        assert tmp_mgr.list_day() == []

    def test_clear_empty_day(self, tmp_mgr: TodoManager):
        count = tmp_mgr.clear_day()
        assert count == 0


# ---- 跨天处理 ----

class TestCarryOver:
    def test_get_yesterday_pending(self, tmp_mgr: TodoManager):
        yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
        tmp_mgr.add("昨日任务1", date_str=yesterday)
        tmp_mgr.add("昨日任务2", date_str=yesterday, priority="high")
        # 一个完成的任务不应出现
        tmp_mgr.update_status("1", "done", date_str=yesterday)

        pending = tmp_mgr.get_yesterday_pending()
        assert len(pending) == 1
        assert pending[0].description == "昨日任务2"

    def test_carry_over_moves_tasks(self, tmp_mgr: TodoManager):
        yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
        item1 = tmp_mgr.add("任务A", date_str=yesterday)
        item2 = tmp_mgr.add("任务B", date_str=yesterday, priority="high")

        moved = tmp_mgr.carry_over([item1, item2])
        assert moved == 2

        # 昨日列表应为空
        assert tmp_mgr.list_day(yesterday) == []
        # 今日应有 2 条
        today_items = tmp_mgr.list_day()
        assert len(today_items) == 2
        # date 字段应更新为今天
        today = datetime.now().strftime("%Y-%m-%d")
        assert all(t.date == today for t in today_items)

    def test_archive_pending(self, tmp_mgr: TodoManager):
        yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
        tmp_mgr.add("任务A", date_str=yesterday)
        tmp_mgr.add("任务B", date_str=yesterday)
        tmp_mgr.update_status("1", "done", date_str=yesterday)

        count = tmp_mgr.archive_pending(yesterday)
        assert count == 1  # 只有 pending 的被归档
        items = tmp_mgr.list_day(yesterday)
        statuses = [t.status for t in items]
        assert "done" in statuses
        assert "cancelled" in statuses
        assert "pending" not in statuses

    def test_should_ask_carry_initially_true(self, tmp_mgr: TodoManager):
        assert tmp_mgr.should_ask_carry() is True

    def test_mark_carry_asked(self, tmp_mgr: TodoManager):
        tmp_mgr.mark_carry_asked()
        assert tmp_mgr.should_ask_carry() is False


# ---- 历史 ----

class TestHistory:
    def test_list_history_includes_today(self, tmp_mgr: TodoManager):
        tmp_mgr.add("今日任务")
        history = tmp_mgr.list_history(days=7)
        assert len(history) >= 1
        today = datetime.now().strftime("%Y-%m-%d")
        assert history[0][0] == today

    def test_list_history_excludes_empty_days(self, tmp_mgr: TodoManager):
        tmp_mgr.add("今日任务")
        history = tmp_mgr.list_history(days=7)
        # 只包含有任务的日子
        for date_str, items in history:
            assert len(items) > 0

    def test_get_day(self, tmp_mgr: TodoManager):
        tmp_mgr.add("任务", date_str="2026-07-10")
        items = tmp_mgr.get_day("2026-07-10")
        assert len(items) == 1

    def test_stats_day_empty(self, tmp_mgr: TodoManager):
        stats = tmp_mgr.stats_day()
        assert stats["total"] == 0
        assert stats["done"] == 0
        assert stats["completion_rate"] == 0.0

    def test_stats_day_with_tasks(self, tmp_mgr: TodoManager):
        tmp_mgr.add("A")
        tmp_mgr.add("B")
        tmp_mgr.update_status("1", "done")
        stats = tmp_mgr.stats_day()
        assert stats["total"] == 2
        assert stats["done"] == 1
        assert stats["pending"] == 1
        assert stats["completion_rate"] == 0.5


# ---- 持久化 ----

class TestPersistence:
    def test_persistence_across_instances(self, tmp_path: Path):
        mgr1 = TodoManager(storage_path=tmp_path)
        mgr1.add("持久化任务")
        # 新实例应能读到
        mgr2 = TodoManager(storage_path=tmp_path)
        items = mgr2.list_day()
        assert len(items) == 1
        assert items[0].description == "持久化任务"

    def test_reload_clears_cache(self, tmp_path: Path):
        mgr1 = TodoManager(storage_path=tmp_path)
        mgr1.add("任务A")
        # 另一个实例直接改文件
        mgr2 = TodoManager(storage_path=tmp_path)
        mgr2.add("任务B")
        # mgr1 有缓存，需 reload
        mgr1.reload()
        items = mgr1.list_day()
        assert len(items) == 2

    def test_corrupted_file_recovers(self, tmp_path: Path):
        """损坏的 todo.json 应被备份并重置。"""
        file_path = tmp_path / "todo.json"
        file_path.write_text("这不是 json", encoding="utf-8")
        mgr = TodoManager(storage_path=tmp_path)
        # 应该用空数据初始化
        assert mgr.list_day() == []
        # 损坏文件应被备份
        bak_files = list(tmp_path.glob("todo.json.bak.*"))
        assert len(bak_files) == 1


# ---- 上限保护 ----

class TestLimits:
    def test_cleanup_old_days(self, tmp_mgr: TodoManager):
        """超过 MAX_HISTORY_DAYS 的旧数据应被清理。"""
        old_date = (datetime.now() - timedelta(days=MAX_HISTORY_DAYS + 5)).strftime("%Y-%m-%d")
        tmp_mgr.add("老任务", date_str=old_date)
        # add 时会触发 _cleanup_old_days
        tmp_mgr.add("新任务")
        data = tmp_mgr._load()
        assert old_date not in data["days"]

"""每日任务测试。"""
from datetime import datetime, timedelta
from core.pet.pet import Pet
from core.pet.tasks import DailyTaskManager, TASK_POOL


def test_refresh_creates_3_tasks():
    p = Pet(name="小白")
    mgr = DailyTaskManager()
    mgr.refresh(pet=p)
    assert len(p.daily_tasks) == 3
    for task in p.daily_tasks:
        assert "task_id" in task
        assert "progress" in task
        assert "completed" in task


def test_refresh_resets_at_midnight():
    p = Pet(name="小白", daily_reset_at="2026-07-05T23:59:00")
    mgr = DailyTaskManager()
    # 模拟跨天
    now = datetime(2026, 7, 6, 8, 0)
    if mgr.should_refresh(p, now=now):
        mgr.refresh(pet=p, now=now)
    assert "2026-07-06" in p.daily_reset_at


def test_check_progress_completes_task():
    p = Pet(name="小白")
    mgr = DailyTaskManager()
    # 手动设置一个 qa5 任务
    p.daily_tasks = [{
        "task_id": "qa5",
        "description": "问 5 个问题",
        "target": 5,
        "reward": 80,
        "progress": 4,
        "completed": False,
    }]
    # 触发第 5 次问答
    completed = mgr.check_progress(p, "qa")
    assert len(completed) == 1
    assert completed[0]["task_id"] == "qa5"
    assert completed[0]["reward"] == 80


def test_check_progress_no_match():
    p = Pet(name="小白")
    mgr = DailyTaskManager()
    p.daily_tasks = [{
        "task_id": "ingest1",
        "description": "入库 1 个文档",
        "target": 1,
        "reward": 100,
        "progress": 0,
        "completed": False,
    }]
    # 触发 qa，不匹配 ingest
    completed = mgr.check_progress(p, "qa")
    assert len(completed) == 0


def test_check_progress_skips_completed():
    p = Pet(name="小白")
    mgr = DailyTaskManager()
    p.daily_tasks = [{
        "task_id": "qa5",
        "description": "问 5 个问题",
        "target": 5,
        "reward": 80,
        "progress": 5,
        "completed": True,
    }]
    completed = mgr.check_progress(p, "qa")
    assert len(completed) == 0  # 已完成，不再触发

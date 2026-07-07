"""跨会话任务测试。"""
import pytest
from core.memory.tasks import Task, TaskManager
from core.memory.store import MemoryStore


def test_add_task_returns_id(tmp_path):
    """添加任务返回 task_id。"""
    store = MemoryStore(storage_path=tmp_path)
    mgr = TaskManager(store)
    task_id = mgr.add_task("整理殡葬政策对比")
    assert task_id.startswith("task_")
    tasks = mgr.get_active_tasks()
    assert len(tasks) == 1
    assert tasks[0].description == "整理殡葬政策对比"
    assert tasks[0].status == "pending"


def test_add_task_with_related_docs(tmp_path):
    """添加任务时可指定关联文档。"""
    store = MemoryStore(storage_path=tmp_path)
    mgr = TaskManager(store)
    mgr.add_task("任务", related_docs=["doc1", "doc2"])
    tasks = mgr.get_active_tasks()
    assert tasks[0].related_docs == ["doc1", "doc2"]


def test_update_task_status(tmp_path):
    """更新任务状态。"""
    store = MemoryStore(storage_path=tmp_path)
    mgr = TaskManager(store)
    task_id = mgr.add_task("任务")
    mgr.update_task(task_id, status="in_progress")
    tasks = mgr.get_active_tasks()
    assert tasks[0].status == "in_progress"


def test_completed_task_not_in_active(tmp_path):
    """完成的任务不在 active 列表中。"""
    store = MemoryStore(storage_path=tmp_path)
    mgr = TaskManager(store)
    task_id = mgr.add_task("任务")
    mgr.update_task(task_id, status="completed")
    assert mgr.get_active_tasks() == []


def test_link_doc(tmp_path):
    """关联文档到任务。"""
    store = MemoryStore(storage_path=tmp_path)
    mgr = TaskManager(store)
    task_id = mgr.add_task("任务")
    mgr.link_doc(task_id, "doc_new")
    tasks = mgr.get_active_tasks()
    assert "doc_new" in tasks[0].related_docs


def test_persistence_across_instances(tmp_path):
    """任务跨实例持久化。"""
    store = MemoryStore(storage_path=tmp_path)
    mgr1 = TaskManager(store)
    mgr1.add_task("任务1")
    store.save()

    store2 = MemoryStore(storage_path=tmp_path)
    mgr2 = TaskManager(store2)
    tasks = mgr2.get_active_tasks()
    assert len(tasks) == 1
    assert tasks[0].description == "任务1"


def test_task_with_context(tmp_path):
    """任务包含 context 字段。"""
    store = MemoryStore(storage_path=tmp_path)
    mgr = TaskManager(store)
    mgr.add_task("任务", context="用户在整理拱墅区政策")
    tasks = mgr.get_active_tasks()
    assert tasks[0].context == "用户在整理拱墅区政策"


# ---- Group 1: 数据累积无清理 ----

def test_update_task_returns_bool(tmp_path):
    """update_task 返回 bool 表示是否找到并更新。"""
    store = MemoryStore(storage_path=tmp_path)
    mgr = TaskManager(store)
    task_id = mgr.add_task("任务")
    assert mgr.update_task(task_id, "completed") is True
    assert mgr.update_task("nonexistent", "completed") is False
    assert mgr.update_task(task_id, "invalid_status") is False


def test_update_task_cancelled_status(tmp_path):
    """update_task 支持 cancelled 状态。"""
    store = MemoryStore(storage_path=tmp_path)
    mgr = TaskManager(store)
    task_id = mgr.add_task("任务")
    assert mgr.update_task(task_id, "cancelled") is True
    # cancelled 任务也不在 active 列表
    assert mgr.get_active_tasks() == []


def test_delete_task(tmp_path):
    """delete_task 彻底删除任务。"""
    store = MemoryStore(storage_path=tmp_path)
    mgr = TaskManager(store)
    task_id = mgr.add_task("任务")
    assert mgr.delete_task(task_id) is True
    assert mgr.get_all_tasks() == []
    # 再删一次返回 False
    assert mgr.delete_task(task_id) is False


def test_get_all_tasks_includes_completed(tmp_path):
    """get_all_tasks 包含已完成/已取消任务。"""
    store = MemoryStore(storage_path=tmp_path)
    mgr = TaskManager(store)
    id1 = mgr.add_task("任务1")
    id2 = mgr.add_task("任务2")
    # ID 不应相同
    assert id1 != id2
    mgr.update_task(id1, "completed")
    mgr.update_task(id2, "cancelled")
    # get_active_tasks 不含任何
    assert mgr.get_active_tasks() == []
    # get_all_tasks 全部包含
    all_tasks = mgr.get_all_tasks()
    assert len(all_tasks) == 2


def test_max_tasks_pruning(tmp_path):
    """超过 MAX_TASKS 上限时自动淘汰最旧的已完成任务。"""
    from core.memory.tasks import MAX_TASKS
    store = MemoryStore(storage_path=tmp_path)
    mgr = TaskManager(store)
    # 添加 MAX_TASKS + 10 个任务，前 10 个标记为 completed
    for i in range(MAX_TASKS + 10):
        tid = mgr.add_task(f"任务{i}")
        if i < 10:
            mgr.update_task(tid, "completed")
    all_tasks = mgr.get_all_tasks()
    assert len(all_tasks) == MAX_TASKS
    # 已完成的旧任务应被淘汰
    completed = [t for t in all_tasks if t.status == "completed"]
    assert len(completed) == 0

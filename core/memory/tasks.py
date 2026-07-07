"""跨会话任务记忆。"""
from __future__ import annotations

import random
import time
from dataclasses import dataclass, field
from typing import List, Optional

from core.memory.store import MemoryStore


# 任务列表上限（含已完成任务，避免无限累积）
MAX_TASKS = 100
# 允许的任务状态
VALID_STATUSES = {"pending", "in_progress", "completed", "cancelled"}


@dataclass
class Task:
    """单条任务。"""
    id: str
    description: str
    created_at: str
    updated_at: str
    status: str  # pending / in_progress / completed / cancelled
    related_docs: List[str] = field(default_factory=list)
    context: str = ""


class TaskManager:
    """任务管理：增删改查 + 持久化。"""

    def __init__(self, store: MemoryStore) -> None:
        self.store = store

    def add_task(
        self,
        description: str,
        related_docs: Optional[List[str]] = None,
        context: str = "",
    ) -> str:
        """添加任务，返回 task_id。"""
        now = time.strftime("%Y-%m-%dT%H:%M:%S")
        # 加随机后缀避免同毫秒创建时 ID 冲突
        task_id = f"task_{int(time.time() * 1000)}_{random.randint(1000, 9999)}"
        task = {
            "id": task_id,
            "description": description,
            "created_at": now,
            "updated_at": now,
            "status": "pending",
            "related_docs": related_docs or [],
            "context": context,
        }
        data = self.store.get_data()
        data["tasks"].append(task)
        # 上限保护：超出时优先淘汰已 cancelled/completed 的最旧任务
        if len(data["tasks"]) > MAX_TASKS:
            tasks = data["tasks"]
            # 先按状态优先级排序（cancelled/completed 排前），再按创建时间
            retired_rank = {"cancelled": 0, "completed": 1, "pending": 2, "in_progress": 3}
            tasks.sort(
                key=lambda t: (retired_rank.get(t.get("status", "pending"), 2), t.get("created_at", ""))
            )
            del tasks[: len(tasks) - MAX_TASKS]
        self.store.save()
        return task_id

    def update_task(self, task_id: str, status: str) -> bool:
        """更新任务状态。

        Args:
            task_id: 任务 ID
            status: 新状态（pending / in_progress / completed / cancelled）

        Returns:
            True 表示找到并更新成功，False 表示未找到或状态无效
        """
        if status not in VALID_STATUSES:
            return False
        data = self.store.get_data()
        for task in data["tasks"]:
            if task["id"] == task_id:
                task["status"] = status
                task["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
                self.store.save()
                return True
        return False

    def delete_task(self, task_id: str) -> bool:
        """彻底删除一条任务（不论状态）。

        Args:
            task_id: 任务 ID

        Returns:
            True 表示删除成功，False 表示未找到
        """
        data = self.store.get_data()
        tasks = data.get("tasks", [])
        for i, task in enumerate(tasks):
            if task["id"] == task_id:
                tasks.pop(i)
                self.store.save()
                return True
        return False

    def get_all_tasks(self) -> List[Task]:
        """获取所有任务（含已完成/已取消）。"""
        data = self.store.get_data()
        tasks = []
        for t in data.get("tasks", []):
            tasks.append(Task(
                id=t["id"],
                description=t["description"],
                created_at=t["created_at"],
                updated_at=t["updated_at"],
                status=t["status"],
                related_docs=t.get("related_docs", []),
                context=t.get("context", ""),
            ))
        return tasks

    def get_active_tasks(self) -> List[Task]:
        """获取未完成任务（pending / in_progress）。"""
        data = self.store.get_data()
        tasks = []
        for t in data.get("tasks", []):
            if t["status"] not in ("completed", "cancelled"):
                tasks.append(Task(
                    id=t["id"],
                    description=t["description"],
                    created_at=t["created_at"],
                    updated_at=t["updated_at"],
                    status=t["status"],
                    related_docs=t.get("related_docs", []),
                    context=t.get("context", ""),
                ))
        return tasks

    def link_doc(self, task_id: str, doc_id: str) -> None:
        """关联文档到任务。"""
        data = self.store.get_data()
        for task in data["tasks"]:
            if task["id"] == task_id:
                if doc_id not in task.get("related_docs", []):
                    task.setdefault("related_docs", []).append(doc_id)
                    task["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
                break
        self.store.save()

"""每日任务系统。"""
from __future__ import annotations

import random
from datetime import datetime, date
from typing import TYPE_CHECKING, List, Optional

if TYPE_CHECKING:
    from core.pet.pet import Pet


# 任务池：task_id → 定义
TASK_POOL = [
    {"task_id": "ingest1", "action": "ingest", "target": 1, "reward": 100, "description": "入库 1 个文档"},
    {"task_id": "ingest3", "action": "ingest", "target": 3, "reward": 250, "description": "入库 3 个文档"},
    {"task_id": "qa5", "action": "qa", "target": 5, "reward": 80, "description": "问 5 个问题"},
    {"task_id": "qa10", "action": "qa", "target": 10, "reward": 180, "description": "问 10 个问题"},
    {"task_id": "analyze1", "action": "analyze", "target": 1, "reward": 120, "description": "使用 /analyze 1 次"},
    {"task_id": "agent1", "action": "agent", "target": 1, "reward": 150, "description": "使用 /agent 完成任务 1 次"},
    {"task_id": "read1", "action": "read", "target": 1, "reward": 100, "description": "用 /read 阅读 1 个文档"},
    {"task_id": "report1", "action": "report", "target": 1, "reward": 150, "description": "生成 1 份报告"},
    {"task_id": "graph_build", "action": "graph_build", "target": 1, "reward": 200, "description": "构建知识图谱"},
    {"task_id": "compare1", "action": "compare", "target": 1, "reward": 120, "description": "用 /compare 对比 1 次"},
    {"task_id": "smart3", "action": "smart", "target": 3, "reward": 100, "description": "用 /smart 路由 3 次"},
    {"task_id": "tag_retag", "action": "retag", "target": 1, "reward": 120, "description": "重新打标签 1 次"},
]

# 每天抽 3 个
TASKS_PER_DAY = 3

# task_id → action 回查表（兼容外部手动构造的 task dict 缺少 action 字段的情况）
_TASK_ACTION_MAP = {t["task_id"]: t["action"] for t in TASK_POOL}


class DailyTaskManager:
    """每日任务管理器。"""

    def refresh(self, pet: "Pet", now: Optional[datetime] = None) -> None:
        """刷新今日任务。7 天内尽量不重复（保证任务多样性）。"""
        if now is None:
            now = datetime.now()
        # 排除最近 7 天用过的任务
        recent_ids = set()
        if hasattr(pet, "task_history") and pet.task_history:
            # task_history: [{"date": "2026-07-05", "task_ids": ["qa5", "ingest1"]}, ...]
            cutoff = now.date()
            for entry in pet.task_history:
                try:
                    entry_date = datetime.fromisoformat(entry["date"]).date()
                    if (cutoff - entry_date).days < 7:
                        recent_ids.update(entry["task_ids"])
                except (ValueError, KeyError):
                    continue
        # 候选池：未在 7 天内出现过的任务
        candidates = [t for t in TASK_POOL if t["task_id"] not in recent_ids]
        # 如果排除后不够 3 个，从全池补
        if len(candidates) < TASKS_PER_DAY:
            candidates = TASK_POOL
        chosen = random.sample(candidates, TASKS_PER_DAY)
        pet.daily_tasks = [
            {
                "task_id": t["task_id"],
                "description": t["description"],
                "target": t["target"],
                "reward": t["reward"],
                "progress": 0,
                "completed": False,
                "action": t["action"],
            }
            for t in chosen
        ]
        pet.daily_reset_at = now.isoformat()
        # 记录到历史
        if not hasattr(pet, "task_history") or pet.task_history is None:
            pet.task_history = []
        pet.task_history.append({
            "date": now.date().isoformat(),
            "task_ids": [t["task_id"] for t in chosen],
        })
        # 只保留最近 14 天
        pet.task_history = pet.task_history[-14:]

    def should_refresh(self, pet: "Pet", now: Optional[datetime] = None) -> bool:
        """判断是否需要刷新（公开方法）。"""
        if now is None:
            now = datetime.now()
        if not pet.daily_reset_at:
            return True
        try:
            last = datetime.fromisoformat(pet.daily_reset_at)
            return last.date() < now.date()
        except (ValueError, TypeError):
            return True

    # 兼容旧调用
    _should_refresh = should_refresh

    def check_progress(self, pet: "Pet", action_type: str) -> List[dict]:
        """检查任务进度，返回新完成的任务列表。

        Args:
            pet: 宠物
            action_type: 行为类型（ingest/qa/analyze/...）

        Returns:
            新完成的任务列表（每个含 task_id / reward）
        """
        newly_completed: List[dict] = []
        if not pet.daily_tasks:
            return newly_completed
        for task in pet.daily_tasks:
            if task["completed"]:
                continue
            # 优先用 task 自带 action；缺失时回查 TASK_POOL（兼容外部手动构造的 task）
            action = task.get("action")
            if action is None:
                action = _TASK_ACTION_MAP.get(task.get("task_id", ""), "")
            if action != action_type:
                continue
            task["progress"] += 1
            if task["progress"] >= task["target"]:
                task["completed"] = True
                newly_completed.append({
                    "task_id": task["task_id"],
                    "reward": task["reward"],
                    "description": task["description"],
                })
        return newly_completed

    def list_tasks(self, pet: "Pet") -> List[dict]:
        """列出今日任务（含进度）。"""
        return pet.daily_tasks or []

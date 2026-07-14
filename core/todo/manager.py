"""每日任务管理器：增删改查 + 跨天 + 历史。

数据存储于 storage/todo.json，结构：
{
  "days": {
    "2026-07-14": [ TodoItem, ... ],
    ...
  },
  "carry_notice": "2026-07-14"   # 已提示过跨天的日期，避免重复打扰
}

TodoItem 字段：
- id           唯一 ID
- description  任务描述
- status       pending / done / cancelled
- priority     high / medium / low（默认 medium）
- note         备注（可选）
- created_at   创建时间 ISO
- completed_at 完成时间 ISO，未完成为 null
- date         归属日期 YYYY-MM-DD
"""
from __future__ import annotations

import json
import logging
import random
import time
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Optional, Tuple

from config import settings

logger = logging.getLogger(__name__)

# 历史保留天数（超出自动淘汰）
MAX_HISTORY_DAYS = 90
# 单日任务上限（防止异常堆积）
MAX_TASKS_PER_DAY = 200

VALID_STATUSES = {"pending", "done", "cancelled"}
VALID_PRIORITIES = {"high", "medium", "low"}

# 优先级排序权重（数字越小越靠前）
_PRIORITY_RANK = {"high": 0, "medium": 1, "low": 2}
# 状态排序权重（未完成在前）
_STATUS_RANK = {"pending": 0, "done": 1, "cancelled": 2}


@dataclass
class TodoItem:
    """单条任务。"""
    id: str
    description: str
    status: str
    priority: str
    note: str
    created_at: str
    completed_at: Optional[str]
    date: str

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "TodoItem":
        return cls(
            id=d["id"],
            description=d.get("description", ""),
            status=d.get("status", "pending"),
            priority=d.get("priority", "medium"),
            note=d.get("note", ""),
            created_at=d.get("created_at", ""),
            completed_at=d.get("completed_at"),
            date=d.get("date", ""),
        )


class TodoManager:
    """每日任务管理器。

    所有方法都不直接读写文件，通过 _load/_save 统一处理。
    日期参数统一用 YYYY-MM-DD 字符串。
    """

    def __init__(self, storage_path: Optional[Path] = None) -> None:
        if storage_path is None:
            storage_path = settings.storage_path
        self.file_path = Path(storage_path) / "todo.json"
        self.file_path.parent.mkdir(parents=True, exist_ok=True)
        self._cache: Optional[dict] = None

    # ---- 持久化 ----

    def _load(self) -> dict:
        """加载数据（带缓存）。"""
        if self._cache is not None:
            return self._cache
        if not self.file_path.exists():
            self._cache = {"days": {}, "carry_notice": None}
            return self._cache
        try:
            data = json.loads(self.file_path.read_text(encoding="utf-8"))
            # 容错：补全字段
            data.setdefault("days", {})
            data.setdefault("carry_notice", None)
            self._cache = data
            return data
        except (json.JSONDecodeError, ValueError) as e:
            logger.warning(f"todo.json 损坏，重置: {e}")
            # 备份损坏文件
            bak = self.file_path.parent / f"todo.json.bak.{int(time.time())}"
            try:
                self.file_path.rename(bak)
            except Exception:
                pass
            self._cache = {"days": {}, "carry_notice": None}
            return self._cache

    def _save(self) -> None:
        """原子写入。"""
        if self._cache is None:
            return
        tmp = self.file_path.with_suffix(".json.tmp")
        tmp.write_text(
            json.dumps(self._cache, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        tmp.replace(self.file_path)

    def reload(self) -> None:
        """清空缓存，强制下次从磁盘读取。"""
        self._cache = None

    # ---- 工具 ----

    @staticmethod
    def _today() -> str:
        return datetime.now().strftime("%Y-%m-%d")

    @staticmethod
    def _now_iso() -> str:
        return datetime.now().strftime("%Y-%m-%dT%H:%M:%S")

    def _gen_id(self) -> str:
        return f"todo_{int(time.time() * 1000)}_{random.randint(1000, 9999)}"

    def _get_day(self, date_str: str) -> List[dict]:
        """获取指定日期的任务列表（可变引用）。"""
        data = self._load()
        return data["days"].setdefault(date_str, [])

    def _sort_tasks(self, tasks: List[dict]) -> List[dict]:
        """排序：状态优先（pending→done→cancelled），再按优先级，再按创建时间。"""
        return sorted(
            tasks,
            key=lambda t: (
                _STATUS_RANK.get(t.get("status", "pending"), 0),
                _PRIORITY_RANK.get(t.get("priority", "medium"), 1),
                t.get("created_at", ""),
            ),
        )

    def _find_task(self, date_str: str, task_ref: str) -> Tuple[Optional[dict], Optional[int]]:
        """在指定日期查找任务。支持序号（1-based）和 id 前缀匹配。

        Returns:
            (task_dict, index) 或 (None, None)
        """
        tasks = self._get_day(date_str)
        # 序号匹配（1-based）
        if task_ref.isdigit():
            idx = int(task_ref) - 1
            if 0 <= idx < len(tasks):
                return tasks[idx], idx
            return None, None
        # id 前缀匹配
        for i, t in enumerate(tasks):
            if t["id"].startswith(task_ref) or task_ref in t["id"]:
                return t, i
        return None, None

    # ---- 增删改查 ----

    def add(
        self,
        description: str,
        priority: str = "medium",
        note: str = "",
        date_str: Optional[str] = None,
    ) -> TodoItem:
        """添加任务，返回 TodoItem。"""
        if priority not in VALID_PRIORITIES:
            priority = "medium"
        if date_str is None:
            date_str = self._today()
        tasks = self._get_day(date_str)
        if len(tasks) >= MAX_TASKS_PER_DAY:
            raise ValueError(f"单日任务已达上限 ({MAX_TASKS_PER_DAY})")
        item = {
            "id": self._gen_id(),
            "description": description,
            "status": "pending",
            "priority": priority,
            "note": note,
            "created_at": self._now_iso(),
            "completed_at": None,
            "date": date_str,
        }
        tasks.append(item)
        self._cleanup_old_days()
        self._save()
        return TodoItem.from_dict(item)

    def list_day(self, date_str: Optional[str] = None) -> List[TodoItem]:
        """列出某天的任务（排序后）。默认今天。"""
        if date_str is None:
            date_str = self._today()
        tasks = self._get_day(date_str)
        return [TodoItem.from_dict(t) for t in self._sort_tasks(tasks)]

    def update_status(self, task_ref: str, status: str, date_str: Optional[str] = None) -> Optional[TodoItem]:
        """更新任务状态。支持序号或 id 前缀。

        Returns:
            更新后的 TodoItem，未找到返回 None
        """
        if status not in VALID_STATUSES:
            raise ValueError(f"无效状态: {status}（允许: {VALID_STATUSES}）")
        if date_str is None:
            date_str = self._today()
        task, _ = self._find_task(date_str, task_ref)
        if task is None:
            return None
        task["status"] = status
        task["completed_at"] = self._now_iso() if status == "done" else None
        self._save()
        return TodoItem.from_dict(task)

    def edit(self, task_ref: str, description: str, date_str: Optional[str] = None) -> Optional[TodoItem]:
        """编辑任务描述。"""
        if date_str is None:
            date_str = self._today()
        task, _ = self._find_task(date_str, task_ref)
        if task is None:
            return None
        task["description"] = description
        self._save()
        return TodoItem.from_dict(task)

    def set_priority(self, task_ref: str, priority: str, date_str: Optional[str] = None) -> Optional[TodoItem]:
        """修改优先级。"""
        if priority not in VALID_PRIORITIES:
            raise ValueError(f"无效优先级: {priority}（允许: {VALID_PRIORITIES}）")
        if date_str is None:
            date_str = self._today()
        task, _ = self._find_task(date_str, task_ref)
        if task is None:
            return None
        task["priority"] = priority
        self._save()
        return TodoItem.from_dict(task)

    def set_note(self, task_ref: str, note: str, date_str: Optional[str] = None) -> Optional[TodoItem]:
        """修改备注。"""
        if date_str is None:
            date_str = self._today()
        task, _ = self._find_task(date_str, task_ref)
        if task is None:
            return None
        task["note"] = note
        self._save()
        return TodoItem.from_dict(task)

    def delete(self, task_ref: str, date_str: Optional[str] = None) -> bool:
        """彻底删除任务。"""
        if date_str is None:
            date_str = self._today()
        task, idx = self._find_task(date_str, task_ref)
        if task is None or idx is None:
            return False
        tasks = self._get_day(date_str)
        tasks.pop(idx)
        # 空日期清理
        if not tasks:
            data = self._load()
            data["days"].pop(date_str, None)
        self._save()
        return True

    def clear_day(self, date_str: Optional[str] = None) -> int:
        """清空某天的所有任务，返回清理数量。"""
        if date_str is None:
            date_str = self._today()
        data = self._load()
        tasks = data["days"].get(date_str, [])
        count = len(tasks)
        data["days"].pop(date_str, None)
        self._save()
        return count

    # ---- 跨天处理 ----

    def get_yesterday_pending(self) -> List[TodoItem]:
        """获取昨日未完成任务（pending 状态）。"""
        yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
        tasks = self._get_day(yesterday)
        return [
            TodoItem.from_dict(t)
            for t in tasks
            if t.get("status") == "pending"
        ]

    def carry_over(self, items: List[TodoItem], to_date: Optional[str] = None) -> int:
        """把指定任务顺延到目标日期（默认今天）。

        从原日期移除，添加到目标日期，date 字段更新。
        """
        if to_date is None:
            to_date = self._today()
        data = self._load()
        today_tasks = data["days"].setdefault(to_date, [])
        moved = 0
        for item in items:
            from_tasks = data["days"].get(item.date, [])
            # 从原日期移除
            for i, t in enumerate(from_tasks):
                if t["id"] == item.id:
                    from_tasks.pop(i)
                    break
            # 加到目标日期
            item.date = to_date
            today_tasks.append(item.to_dict())
            moved += 1
        # 清空原日期空列表
        for item in items:
            if item.date != to_date and not data["days"].get(item.date):
                data["days"].pop(item.date, None)
        self._save()
        return moved

    def archive_pending(self, date_str: str) -> int:
        """把某天未完成任务标记为 cancelled（归档，保留历史）。"""
        tasks = self._get_day(date_str)
        count = 0
        for t in tasks:
            if t.get("status") == "pending":
                t["status"] = "cancelled"
                count += 1
        if count:
            self._save()
        return count

    def should_ask_carry(self) -> bool:
        """今天是否还没提示过跨天。"""
        data = self._load()
        return data.get("carry_notice") != self._today()

    def mark_carry_asked(self) -> None:
        """标记今天已提示过跨天。"""
        data = self._load()
        data["carry_notice"] = self._today()
        self._save()

    # ---- 历史 ----

    def list_history(self, days: int = 7) -> List[Tuple[str, List[TodoItem]]]:
        """获取最近 N 天的历史（含今天），按日期倒序。

        Returns:
            [(date_str, [TodoItem, ...]), ...]
        """
        data = self._load()
        today = datetime.now().date()
        result: List[Tuple[str, List[TodoItem]]] = []
        for i in range(days):
            d = today - timedelta(days=i)
            d_str = d.strftime("%Y-%m-%d")
            tasks = data["days"].get(d_str, [])
            if tasks:
                result.append((d_str, [TodoItem.from_dict(t) for t in self._sort_tasks(tasks)]))
        return result

    def get_day(self, date_str: str) -> List[TodoItem]:
        """获取指定日期的任务列表。"""
        tasks = self._get_day(date_str)
        return [TodoItem.from_dict(t) for t in self._sort_tasks(tasks)]

    def stats_day(self, date_str: Optional[str] = None) -> dict:
        """统计某天任务完成情况。"""
        if date_str is None:
            date_str = self._today()
        tasks = self._get_day(date_str)
        total = len(tasks)
        done = sum(1 for t in tasks if t.get("status") == "done")
        pending = sum(1 for t in tasks if t.get("status") == "pending")
        cancelled = sum(1 for t in tasks if t.get("status") == "cancelled")
        return {
            "date": date_str,
            "total": total,
            "done": done,
            "pending": pending,
            "cancelled": cancelled,
            "completion_rate": (done / total) if total else 0.0,
        }

    # ---- 维护 ----

    def _cleanup_old_days(self) -> None:
        """清理超过 MAX_HISTORY_DAYS 的旧数据。"""
        data = self._load()
        cutoff = (datetime.now() - timedelta(days=MAX_HISTORY_DAYS)).strftime("%Y-%m-%d")
        old_keys = [k for k in data["days"].keys() if k < cutoff]
        for k in old_keys:
            data["days"].pop(k, None)
        if old_keys:
            logger.info(f"清理 {len(old_keys)} 个过期日期的待办历史")

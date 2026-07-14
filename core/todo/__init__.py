"""每日任务（todo）模块。

提供用户自定义的每日待办管理：
- 按日期分组的任务列表
- 增删改查 + 优先级 + 备注
- 跨天提示（顺延/归档/逐个询问）
- 历史记录查询（最近 90 天）
"""
from core.todo.manager import TodoItem, TodoManager

__all__ = ["TodoItem", "TodoManager"]

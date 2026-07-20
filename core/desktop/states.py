"""桌面宠物状态枚举（Task 1）。

零侵入约束：
- 本模块属于 ``core/desktop/`` 新增模块，不修改项目任何现有文件。

设计：
- ``PetState`` 12 个状态，与 ``static/cats/cat_<state>.gif`` 一一对应。
- 状态值即 GIF 文件名主体（``PetState.IDLE.value == "idle"``）。
- ``SOUND_*`` 常量与 ``static/sounds/<name>.wav`` 对应，供托盘/桥接触发音效。
"""
from __future__ import annotations

from enum import Enum

__all__ = [
    "PetState",
    "SOUND_COMPLETE",
    "SOUND_CONFIRM",
    "SOUND_ERROR",
    "SOUND_INGEST",
    "STATE_GIF_MAP",
]


class PetState(Enum):
    """桌面宠物 12 状态枚举。

    每个状态的 ``value`` 即对应 GIF 文件名主体：
    ``static/cats/cat_<value>.gif``。
    """

    IDLE = "idle"                # 待机（默认常驻）
    LISTENING = "listening"      # 倾听（接收问题）
    THINKING = "thinking"        # 思考（LLM 准备）
    RETRIEVING = "retrieving"    # 检索（混合检索）
    RANKING = "ranking"          # 排名（LLM 重排）
    ANSWERING = "answering"      # 回答（流式输出）
    CELEBRATING = "celebrating"  # 庆祝（任务完成/入库成功）
    ERROR = "error"              # 报错
    SLEEPING = "sleeping"        # 睡眠（闲置/勿扰）
    INGESTING = "ingesting"      # 入库（解析/分块/保存）
    ANALYZING = "analyzing"      # 分析（深度分析）
    NOTIFYING = "notifying"      # 提醒（通知/待办）

    def __str__(self) -> str:  # 便于日志直接打印
        return self.value


# 状态 → GIF 相对路径映射（供需要直接取路径的场景）
STATE_GIF_MAP = {state: f"cats/cat_{state.value}.gif" for state in PetState}

# 音效常量（对应 static/sounds/<name>.wav）
SOUND_COMPLETE = "complete"
SOUND_CONFIRM = "confirm"
SOUND_ERROR = "error"
SOUND_INGEST = "ingest"

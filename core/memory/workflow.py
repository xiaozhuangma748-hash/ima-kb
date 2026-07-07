"""工作流模式识别：记录命令序列，推荐下一步。"""
from __future__ import annotations

import time
from typing import List, Optional

from core.memory.store import MemoryStore


# 触发推荐的最低次数
MIN_PATTERN_COUNT = 2
# 窗口时间（秒）：30 分钟
WINDOW_SECONDS = 30 * 60
# 最近命令的最大保留条数
RECENT_LIMIT = 10
# 模式列表上限（避免无限累积）
MAX_PATTERNS = 50


class WorkflowTracker:
    """工作流模式识别器。

    通过非重叠 2-gram 检测命令序列模式：
    每积累 2 条命令形成一个 pattern，避免重叠序列污染统计。
    """

    def __init__(self, store: MemoryStore) -> None:
        self.store = store

    def record_command(self, cmd: str, timestamp: Optional[str] = None) -> None:
        """记录命令执行。

        维护最近命令滑动窗口与非重叠 2-gram 模式检测。

        Args:
            cmd: 命令名
            timestamp: ISO 格式时间戳，为 None 时取当前时间
        """
        if timestamp is None:
            timestamp = time.strftime("%Y-%m-%dT%H:%M:%S")

        data = self.store.get_data()
        workflow = data.setdefault("workflow", {})
        patterns = workflow.setdefault("patterns", [])

        # 记录到 recent_commands（用于 detect_pattern 等场景）
        recent = workflow.setdefault("recent_commands", [])
        recent.append({"cmd": cmd, "timestamp": timestamp})
        if len(recent) > RECENT_LIMIT:
            # 原地裁剪，保留引用
            del recent[: len(recent) - RECENT_LIMIT]

        # 非重叠 2-gram 检测：积累 2 条命令后形成 pattern
        pending = workflow.setdefault("pending_pair", [])
        pending.append(cmd)
        if len(pending) >= 2:
            seq = [pending[0], pending[1]]
            self._update_pattern(patterns, seq)
            # 清空，开始下一对
            workflow["pending_pair"] = []
        # pending 已通过 setdefault 引用，update 时直接修改即可

        self.store.save()

    def _update_pattern(self, patterns: List[dict], seq: List[str]) -> None:
        """更新或创建模式。已存在则计数递增。"""
        now = time.strftime("%Y-%m-%dT%H:%M:%S")
        for p in patterns:
            if p["sequence"] == seq:
                p["count"] += 1
                p["last_used"] = now
                return
        patterns.append({
            "sequence": seq,
            "count": 1,
            "last_used": now,
        })
        # 上限保护：超出时淘汰 count 最低且最久未用的
        if len(patterns) > MAX_PATTERNS:
            patterns.sort(key=lambda p: (p.get("count", 0), p.get("last_used", "")))
            del patterns[: len(patterns) - MAX_PATTERNS]

    def clear_patterns(self) -> int:
        """清空所有模式记录。

        Returns:
            被清除的模式数量
        """
        data = self.store.get_data()
        workflow = data.get("workflow", {})
        patterns = workflow.get("patterns", [])
        count = len(patterns)
        workflow["patterns"] = []
        self.store.save()
        return count

    def set_suggestions_enabled(self, enabled: bool) -> None:
        """启用/关闭下一步推荐。"""
        data = self.store.get_data()
        workflow = data.setdefault("workflow", {})
        workflow["suggestions_enabled"] = bool(enabled)
        self.store.save()

    def suggest_next(self, current_cmd: str) -> Optional[str]:
        """根据当前命令推荐下一步。

        Args:
            current_cmd: 当前命令名

        Returns:
            推荐的命令名，或 None
        """
        data = self.store.get_data()
        workflow = data.get("workflow", {})

        # 检查是否启用推荐
        if not workflow.get("suggestions_enabled", True):
            return None

        patterns = workflow.get("patterns", [])
        # 找出以 current_cmd 开头的高频序列
        candidates = []
        for p in patterns:
            seq = p["sequence"]
            if isinstance(seq, list) and len(seq) >= 2 and seq[0] == current_cmd:
                candidates.append((seq[1], p["count"]))

        if not candidates:
            return None

        # 按频次降序，取第一个
        candidates.sort(key=lambda x: x[1], reverse=True)
        next_cmd, count = candidates[0]
        if count >= MIN_PATTERN_COUNT:
            return next_cmd
        return None

    def detect_pattern(self) -> Optional[List[str]]:
        """检测当前是否在常用工作流中。

        Returns:
            当前正在执行的序列，或 None
        """
        data = self.store.get_data()
        workflow = data.get("workflow", {})
        recent = workflow.get("recent_commands", [])
        patterns = workflow.get("patterns", [])

        if len(recent) < 1:
            return None

        # 检查最近命令是否是某个高频序列的开始
        last_cmd = recent[-1]["cmd"]
        for p in patterns:
            seq = p["sequence"]
            if (
                isinstance(seq, list)
                and len(seq) >= 2
                and seq[0] == last_cmd
                and p["count"] >= MIN_PATTERN_COUNT
            ):
                return seq
        return None

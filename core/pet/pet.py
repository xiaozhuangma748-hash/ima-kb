"""Pet 类：虚拟宠物状态 + 升级逻辑。"""
from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from typing import Optional


# 分系类型
BranchType = Optional[str]  # None / "scholar" / "warrior" / "artisan"

# 等级上限
MAX_LEVEL = 10


@dataclass
class Pet:
    """虚拟宠物状态。"""

    # 基本信息
    name: str
    level: int = 1
    exp: int = 0
    branch: BranchType = None

    # 5 维属性（0-100）
    hunger: int = 80
    mood: int = 80
    energy: int = 100
    cleanliness: int = 80
    exp_multi: float = 1.0

    # 行为统计（分系判定用）
    stats: dict = field(default_factory=lambda: {
        "ingest": 0, "qa": 0, "read": 0, "report": 0,
        "agent": 0, "compare": 0,
        "analyze": 0, "smart": 0, "retag": 0,
        "graph_build": 0,
    })

    # 道具栏
    inventory: list = field(default_factory=list)

    # 时间戳（ISO 字符串）
    last_interact: str = ""
    last_decay: str = ""
    created_at: str = ""

    # 每日任务
    daily_tasks: list = field(default_factory=list)
    daily_reset_at: str = ""
    # 任务历史（7 天不重复用）：[{"date": "2026-07-05", "task_ids": [...]}]
    task_history: list = field(default_factory=list)

    # 限时效果
    active_effects: list = field(default_factory=list)

    def exp_needed(self) -> int:
        """当前等级升到下一级所需经验（纯公式，MAX_LEVEL 由 exp_remaining/gain_exp 守卫）。"""
        return math.floor(100 * (self.level ** 1.5))

    def exp_remaining(self) -> int:
        """距离升级还差多少经验。"""
        if self.level >= MAX_LEVEL:
            return 0
        return max(0, self.exp_needed() - self.exp)

    # 分系判定用的行为映射
    SCHOLAR_KEYS = {"ingest", "qa", "read", "report"}
    WARRIOR_KEYS = {"agent", "compare"}
    ARTISAN_KEYS = {"analyze", "smart", "retag"}
    # graph_build 中性，不计入分系

    def _determine_branch(self) -> str:
        """根据 stats 判定分系。平局时随机选择。"""
        scholar_score = sum(self.stats.get(k, 0) for k in self.SCHOLAR_KEYS)
        warrior_score = sum(self.stats.get(k, 0) for k in self.WARRIOR_KEYS)
        artisan_score = sum(self.stats.get(k, 0) for k in self.ARTISAN_KEYS)
        scores = [
            ("scholar", scholar_score),
            ("warrior", warrior_score),
            ("artisan", artisan_score),
        ]
        max_score = max(s for _, s in scores)
        # 平局时随机选一个（避免永远 scholar）
        winners = [name for name, s in scores if s == max_score]
        return random.choice(winners) if len(winners) > 1 else winners[0]

    def gain_exp(self, amount: int, action_type: str) -> dict:
        """获取经验，可能触发升级和分系。

        Args:
            amount: 基础经验值
            action_type: 行为类型（ingest/qa/analyze/agent/...）

        Returns:
            事件信息 dict：
                - leveled_up: bool
                - new_level: int (若升级)
                - branched: bool
                - branch: str (若分系)
        """
        events = {"leveled_up": False, "branched": False}

        # 1. 累计行为统计
        if action_type in self.stats:
            self.stats[action_type] += 1

        # 2. 心情惩罚
        actual_amount = amount
        if self.mood < 30:
            actual_amount = int(actual_amount * 0.7)
        # 3. 清理过期限时效果，再计算实际经验加成倍率
        self.clean_expired_effects()
        actual_amount = int(actual_amount * self.get_active_exp_multi())

        # 4. 累加经验
        self.exp += actual_amount

        # 5. 检查升级（可能连升多级）
        while self.level < MAX_LEVEL and self.exp >= self.exp_needed():
            self.exp -= self.exp_needed()
            self.level += 1
            events["leveled_up"] = True
            events["new_level"] = self.level

            # 6. Lv5 触发分系
            if self.level == 5 and self.branch is None:
                self.branch = self._determine_branch()
                events["branched"] = True
                events["branch"] = self.branch

        # Lv10 满级，经验封顶不再累积（保留溢出经验但不升级）
        if self.level >= MAX_LEVEL:
            # 经验继续累积但不升级，UI 显示"已达最高级"
            pass

        return events

    def clean_expired_effects(self) -> int:
        """清理 active_effects 中已过期的限时效果。

        Returns:
            清理的效果数量
        """
        if not self.active_effects:
            return 0
        from datetime import datetime
        now = datetime.now()
        kept = []
        removed = 0
        for eff in self.active_effects:
            expires_at = eff.get("expires_at", "")
            if not expires_at:
                # 无过期时间的永久效果，保留（如 auto_revive 未触发前）
                kept.append(eff)
                continue
            try:
                exp_time = datetime.fromisoformat(expires_at)
                if exp_time > now:
                    kept.append(eff)
                else:
                    removed += 1
            except (ValueError, TypeError):
                # 时间解析失败，保留以免误删
                kept.append(eff)
        self.active_effects = kept
        return removed

    def get_active_exp_multi(self) -> float:
        """获取当前生效的经验加成倍率（综合 exp_multi 字段和 active_effects 中的限时倍率）。"""
        multi = self.exp_multi
        for eff in self.active_effects:
            if eff.get("effect") == "exp_multi":
                multi *= eff.get("value", 1.0)
        return multi

    def has_auto_revive(self) -> bool:
        """是否持有未触发的凤凰之羽效果。"""
        return any(eff.get("effect") == "auto_revive" for eff in self.active_effects)

    def consume_auto_revive(self) -> bool:
        """消耗一个凤凰之羽效果（用于 hunger=0 时免扣经验）。

        Returns:
            True 表示成功消耗，False 表示没有可用效果
        """
        for i, eff in enumerate(self.active_effects):
            if eff.get("effect") == "auto_revive":
                self.active_effects.pop(i)
                return True
        return False

    def reset_stats(self) -> None:
        """重置行为统计（stats）。

        用于用户希望重新选择分系、或纠正错误行为统计的场景。
        不会重置等级、经验、属性值，只清空 stats 字典。
        """
        self.stats = {
            "ingest": 0, "qa": 0, "read": 0, "report": 0,
            "agent": 0, "compare": 0,
            "analyze": 0, "smart": 0, "retag": 0,
            "graph_build": 0,
        }

    def clear_active_effects(self) -> int:
        """清空所有限时效果（active_effects）。

        Returns:
            被清除的效果数量
        """
        count = len(self.active_effects)
        self.active_effects = []
        return count

    # 衰减速率（每小时）— v2 平衡：周末两天不上线不会触底
    HUNGER_DECAY_PER_HOUR = 1.5
    MOOD_DECAY_PER_HOUR = 0.5
    CLEANLINESS_DECAY_PER_HOUR = 0.3
    MAX_DECAY_CAP = 50  # 单次离线衰减封顶
    HUNGER_ZERO_EXP_PENALTY = 10  # hunger=0 时每小时扣经验

    def apply_decay(self) -> dict:
        """应用离线衰减，返回衰减信息。"""
        from datetime import datetime

        if not self.last_decay:
            self.last_decay = datetime.now().isoformat()
            return {"hours": 0}

        try:
            last = datetime.fromisoformat(self.last_decay)
        except (ValueError, TypeError):
            self.last_decay = datetime.now().isoformat()
            return {"hours": 0}

        now = datetime.now()
        hours = (now - last).total_seconds() / 3600.0
        if hours < 0.1:  # 不到 6 分钟，不衰减
            return {"hours": 0}

        # 计算各项衰减
        hunger_decay = min(self.MAX_DECAY_CAP, hours * self.HUNGER_DECAY_PER_HOUR)
        mood_decay = min(self.MAX_DECAY_CAP, hours * self.MOOD_DECAY_PER_HOUR)
        cleanliness_decay = min(self.MAX_DECAY_CAP, hours * self.CLEANLINESS_DECAY_PER_HOUR)

        # cleanliness 低时心情加速衰减
        if self.cleanliness < 30:
            mood_decay *= 2

        self.hunger = max(0, int(self.hunger - hunger_decay))
        self.mood = max(0, int(self.mood - mood_decay))
        self.cleanliness = max(0, int(self.cleanliness - cleanliness_decay))

        # hunger=0 时扣经验（凤凰之羽可抵扣一次）
        exp_loss = 0
        revived = False
        if self.hunger == 0:
            # 先尝试消耗凤凰之羽
            if self.consume_auto_revive():
                revived = True
                # 凤凰之羽触发：恢复 hunger 到 50，本次不扣经验
                self.hunger = 50
            else:
                exp_loss = int(hours * self.HUNGER_ZERO_EXP_PENALTY)
                self.exp = max(0, self.exp - exp_loss)

        self.last_decay = now.isoformat()

        result = {
            "hours": round(hours, 1),
            "hunger_loss": int(hunger_decay),
            "mood_loss": int(mood_decay),
            "cleanliness_loss": int(cleanliness_decay),
            "exp_loss": exp_loss,
        }
        if revived:
            result["auto_revived"] = True
        return result

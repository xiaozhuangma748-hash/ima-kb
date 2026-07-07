"""宠物互动命令处理。"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from core.pet.pet import Pet


class InteractError(Exception):
    """互动失败（如能量不足）。"""


class PetInteractor:
    """互动命令处理器。"""

    SLEEP_COOLDOWN_SECONDS = 3600  # 1 小时冷却

    def feed(self, pet: "Pet") -> dict:
        """喂食：+30 hunger, +5 mood, -10 energy, -5 exp。"""
        if pet.energy < 10:
            raise InteractError(f"{pet.name} 累坏了，让它睡会儿吧～")
        pet.hunger = min(100, pet.hunger + 30)
        pet.mood = min(100, pet.mood + 5)
        pet.energy -= 10
        pet.exp = max(0, pet.exp - 5)
        self._touch(pet)
        return {"message": f"{pet.name} 吃饱了 ❤️+30"}

    def play(self, pet: "Pet") -> dict:
        """玩耍：+40 mood, -10 hunger, -15 energy, +10 exp。"""
        if pet.energy < 15:
            raise InteractError(f"{pet.name} 累坏了，让它睡会儿吧～")
        pet.mood = min(100, pet.mood + 40)
        pet.hunger = max(0, pet.hunger - 10)
        pet.energy -= 15
        events = pet.gain_exp(10, "play")
        self._touch(pet)
        return {"message": f"{pet.name} 玩得很开心 😊+40"}

    def train(self, pet: "Pet") -> dict:
        """训练：-25 energy, -10 mood, +50 exp（高效升级）。"""
        if pet.energy < 10:
            raise InteractError(f"{pet.name} 累坏了，让它睡会儿吧～")
        if pet.hunger < 20:
            raise InteractError(f"{pet.name} 饿了，先喂点东西吧～")
        # 心情低时训练效果减半（在扣 mood 之前判定，配合 gain_exp 的 mood<30 全局惩罚形成双层惩罚）
        exp_gain = 25 if pet.mood < 20 else 50
        pet.energy -= 25
        pet.mood = max(0, pet.mood - 10)
        events = pet.gain_exp(exp_gain, "train")
        self._touch(pet)
        msg = f"{pet.name} 学到了新东西 ✨+{exp_gain}"
        if events.get("leveled_up"):
            msg += f"  🎉 升到 Lv{events['new_level']}！"
        return {"message": msg, "events": events}

    def wash(self, pet: "Pet") -> dict:
        """清洁：+50 cleanliness, +5 mood, -5 energy。"""
        pet.cleanliness = min(100, pet.cleanliness + 50)
        pet.mood = min(100, pet.mood + 5)
        pet.energy = max(0, pet.energy - 5)
        self._touch(pet)
        return {"message": f"{pet.name} 洗得干干净净 🛁+50"}

    def sleep(self, pet: "Pet") -> dict:
        """睡觉：+50 energy, +10 mood（1 小时冷却）。"""
        now = datetime.now()
        if pet.last_interact:
            last = datetime.fromisoformat(pet.last_interact)
            if (now - last).total_seconds() < self.SLEEP_COOLDOWN_SECONDS:
                remaining = self.SLEEP_COOLDOWN_SECONDS - int((now - last).total_seconds())
                mins = remaining // 60
                raise InteractError(f"{pet.name} 刚睡过，{mins} 分钟后再试～")
        pet.energy = min(100, pet.energy + 50)
        pet.mood = min(100, pet.mood + 10)
        self._touch(pet)
        return {"message": f"{pet.name} 睡了个好觉 ⚡+50"}

    def _touch(self, pet: "Pet") -> None:
        """更新 last_interact 时间戳。"""
        pet.last_interact = datetime.now().isoformat()

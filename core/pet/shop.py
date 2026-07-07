"""道具商店。"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from core.pet.pet import Pet


class ShopError(Exception):
    """商店操作失败。"""


# 道具定义
ITEMS = [
    {"id": "fish", "name": "小鱼干", "price": 50, "effect": {"hunger": 30}},
    {"id": "ball", "name": "玩具球", "price": 80, "effect": {"mood": 40}},
    {"id": "soap", "name": "洗浴套装", "price": 60, "effect": {"cleanliness": 50}},
    {"id": "energy_drink", "name": "能量饮料", "price": 100, "effect": {"energy": 50}},
    {"id": "exp_potion", "name": "经验药水", "price": 150, "effect": {"exp_multi": 2.0, "duration_sec": 7200}},
    {"id": "super_food", "name": "顶级饲料", "price": 150, "effect": {"hunger": 50, "mood": 20}},
    {"id": "phoenix_down", "name": "凤凰之羽", "price": 500, "effect": {"auto_revive": True}},
    {"id": "rename_card", "name": "重置卡", "price": 100, "effect": {"reset_stats": True}},
]


class Shop:
    """道具商店。"""

    def list_items(self) -> list:
        """列出所有道具。"""
        return [{"id": i["id"], "name": i["name"], "price": i["price"], "effect": i["effect"]} for i in ITEMS]

    def _find_item(self, item_id: str) -> dict:
        for item in ITEMS:
            if item["id"] == item_id:
                return item
        raise ShopError(f"未知道具: {item_id}")

    def buy(self, pet: "Pet", item_id: str) -> dict:
        """购买道具。"""
        item = self._find_item(item_id)
        if pet.exp < item["price"]:
            raise ShopError(f"经验不足，需要 {item['price']}，当前 {pet.exp}")
        pet.exp -= item["price"]
        # 加入库存
        for inv in pet.inventory:
            if inv["item_id"] == item_id:
                inv["count"] += 1
                break
        else:
            pet.inventory.append({"item_id": item_id, "count": 1})
        return {"message": f"✓ 购买成功 {item['name']}，剩余经验 {pet.exp}"}

    def use(self, pet: "Pet", item_id: str) -> dict:
        """使用道具。"""
        item = self._find_item(item_id)
        # 查找库存
        inv_idx = -1
        for i, inv in enumerate(pet.inventory):
            if inv["item_id"] == item_id and inv["count"] > 0:
                inv_idx = i
                break
        if inv_idx < 0:
            raise ShopError(f"没有 {item['name']}，先去 /pet buy 吧")

        # 应用效果
        effect = item["effect"]
        if "hunger" in effect:
            pet.hunger = min(100, pet.hunger + effect["hunger"])
        if "mood" in effect:
            pet.mood = min(100, pet.mood + effect["mood"])
        if "cleanliness" in effect:
            pet.cleanliness = min(100, pet.cleanliness + effect["cleanliness"])
        if "energy" in effect:
            pet.energy = min(100, pet.energy + effect["energy"])
        if "exp_multi" in effect:
            # 限时效果
            expires = datetime.now() + timedelta(seconds=effect.get("duration_sec", 3600))
            pet.active_effects.append({
                "effect": "exp_multi",
                "value": effect["exp_multi"],
                "expires_at": expires.isoformat(),
            })
        if "auto_revive" in effect:
            # 凤凰之羽：注册一个 auto_revive 效果（无过期时间，触发后消耗）
            pet.active_effects.append({
                "effect": "auto_revive",
                "value": True,
            })
        if "reset_stats" in effect:
            # 重置卡：把属性都恢复到 80
            pet.hunger = max(pet.hunger, 80)
            pet.mood = max(pet.mood, 80)
            pet.cleanliness = max(pet.cleanliness, 80)
            pet.energy = max(pet.energy, 80)

        # 扣库存
        pet.inventory[inv_idx]["count"] -= 1
        # 清理 count=0 的库存项，避免列表残留
        if pet.inventory[inv_idx]["count"] <= 0:
            pet.inventory.pop(inv_idx)

        return {"message": f"{pet.name} 用了 {item['name']}"}

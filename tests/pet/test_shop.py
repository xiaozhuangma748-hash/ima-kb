"""道具商店测试。"""
import pytest
from core.pet.pet import Pet
from core.pet.shop import Shop, ShopError


def test_list_items_returns_all():
    shop = Shop()
    items = shop.list_items()
    assert len(items) == 8  # 8 种道具
    ids = [i["id"] for i in items]
    assert "fish" in ids
    assert "exp_potion" in ids


def test_buy_success():
    p = Pet(name="小白", exp=500)
    shop = Shop()
    result = shop.buy(p, "fish")
    assert p.exp == 450  # 500 - 50
    assert len(p.inventory) == 1
    assert p.inventory[0]["item_id"] == "fish"
    assert p.inventory[0]["count"] == 1
    assert "购买成功" in result["message"]


def test_buy_insufficient_exp():
    p = Pet(name="小白", exp=30)
    shop = Shop()
    with pytest.raises(ShopError) as exc:
        shop.buy(p, "fish")  # 需要 50 经验
    assert "经验不足" in str(exc.value)
    assert p.exp == 30  # 未扣


def test_buy_stacks_inventory():
    p = Pet(name="小白", exp=500, inventory=[{"item_id": "fish", "count": 2}])
    shop = Shop()
    shop.buy(p, "fish")
    assert p.inventory[0]["count"] == 3


def test_use_fish():
    p = Pet(name="小白", hunger=50, inventory=[{"item_id": "fish", "count": 1}])
    shop = Shop()
    result = shop.use(p, "fish")
    assert p.hunger == 80  # 50 + 30
    # count=0 的库存项应被清理（避免列表残留）
    assert len(p.inventory) == 0


def test_use_fish_keeps_when_count_gt_1():
    """count > 1 时使用一个，应保留并 count - 1。"""
    p = Pet(name="小白", hunger=50, inventory=[{"item_id": "fish", "count": 2}])
    shop = Shop()
    shop.use(p, "fish")
    assert p.hunger == 80
    assert p.inventory[0]["count"] == 1
    assert len(p.inventory) == 1


def test_use_not_in_inventory():
    p = Pet(name="小白")
    shop = Shop()
    with pytest.raises(ShopError) as exc:
        shop.use(p, "fish")
    assert "没有" in str(exc.value)


def test_use_exp_potion_activates_effect():
    p = Pet(name="小白", inventory=[{"item_id": "exp_potion", "count": 1}])
    shop = Shop()
    shop.use(p, "exp_potion")
    # 应该激活限时效果
    assert len(p.active_effects) == 1
    assert p.active_effects[0]["effect"] == "exp_multi"
    assert p.active_effects[0]["value"] == 2.0


def test_use_phoenix_down_registers_effect():
    """凤凰之羽使用后应在 active_effects 中注册 auto_revive。"""
    p = Pet(name="小白", exp=500, inventory=[{"item_id": "phoenix_down", "count": 1}])
    shop = Shop()
    shop.use(p, "phoenix_down")
    assert any(eff.get("effect") == "auto_revive" for eff in p.active_effects)
    # 库存应清空（count=0 被弹出）
    assert len(p.inventory) == 0


def test_phoenix_down_revives_on_hunger_zero():
    """hunger=0 时应消耗凤凰之羽，避免扣经验并恢复 hunger。"""
    from datetime import datetime, timedelta
    p = Pet(name="小白", hunger=0, exp=100, active_effects=[
        {"effect": "auto_revive", "value": True}
    ])
    # 设置 last_decay 为 2 小时前，让 apply_decay 触发 hunger=0 扣经验逻辑
    p.last_decay = (datetime.now() - timedelta(hours=2)).isoformat()
    result = p.apply_decay()
    assert result.get("auto_revived") is True
    assert p.hunger == 50  # 凤凰之羽恢复 hunger 到 50
    assert p.exp == 100  # 没扣经验
    # auto_revive 效果应被消耗
    assert not p.has_auto_revive()


def test_no_phoenix_down_loses_exp_on_hunger_zero():
    """没有凤凰之羽时，hunger=0 应正常扣经验。"""
    from datetime import datetime, timedelta
    p = Pet(name="小白", hunger=0, exp=100)
    p.last_decay = (datetime.now() - timedelta(hours=2)).isoformat()
    result = p.apply_decay()
    assert "auto_revived" not in result
    assert p.exp < 100  # 扣了经验


def test_clean_expired_effects():
    """过期的限时效果应被清理。"""
    from datetime import datetime, timedelta
    past = (datetime.now() - timedelta(hours=1)).isoformat()
    future = (datetime.now() + timedelta(hours=1)).isoformat()
    p = Pet(name="小白", active_effects=[
        {"effect": "exp_multi", "value": 2.0, "expires_at": past},   # 已过期
        {"effect": "exp_multi", "value": 1.5, "expires_at": future}, # 未过期
        {"effect": "auto_revive", "value": True},                     # 无过期时间，保留
    ])
    removed = p.clean_expired_effects()
    assert removed == 1
    assert len(p.active_effects) == 2
    assert p.active_effects[0]["value"] == 1.5
    assert p.active_effects[1]["effect"] == "auto_revive"


def test_get_active_exp_multi_combines_effects():
    """get_active_exp_multi 应综合 exp_multi 字段和 active_effects。"""
    from datetime import datetime, timedelta
    future = (datetime.now() + timedelta(hours=1)).isoformat()
    p = Pet(name="小白", exp_multi=1.0, active_effects=[
        {"effect": "exp_multi", "value": 2.0, "expires_at": future},
    ])
    assert p.get_active_exp_multi() == 2.0
    # 两个倍率叠加
    p.active_effects.append({"effect": "exp_multi", "value": 1.5, "expires_at": future})
    assert p.get_active_exp_multi() == 3.0


def test_gain_exp_uses_active_exp_multi():
    """gain_exp 应动态读取 active_effects 中的经验加成。"""
    from datetime import datetime, timedelta
    future = (datetime.now() + timedelta(hours=1)).isoformat()
    p = Pet(name="小白", level=1, exp=0, active_effects=[
        {"effect": "exp_multi", "value": 2.0, "expires_at": future},
    ])
    p.gain_exp(50, "ingest")
    # 50 * 2.0 = 100，正好触发升级（Lv1→Lv2 需要 100），消耗后 exp=0
    # 所以验证 stats["ingest"] 和 total earned（通过 level + exp 重算）
    assert p.stats["ingest"] == 1
    # 用 30 避免触发升级：30 * 2.0 = 60
    p2 = Pet(name="小白", level=1, exp=0, active_effects=[
        {"effect": "exp_multi", "value": 2.0, "expires_at": future},
    ])
    p2.gain_exp(30, "ingest")
    assert p2.exp == 60


def test_gain_exp_cleans_expired_first():
    """gain_exp 应先清理过期效果再计算倍率。"""
    from datetime import datetime, timedelta
    past = (datetime.now() - timedelta(hours=1)).isoformat()
    p = Pet(name="小白", level=1, exp=0, active_effects=[
        {"effect": "exp_multi", "value": 2.0, "expires_at": past},  # 已过期
    ])
    p.gain_exp(50, "ingest")
    # 过期效果已清理，倍率回到 1.0
    assert p.exp == 50
    assert len(p.active_effects) == 0


def test_has_auto_revive_and_consume():
    """has_auto_revive / consume_auto_revive 基本逻辑。"""
    p = Pet(name="小白")
    assert p.has_auto_revive() is False
    assert p.consume_auto_revive() is False

    p.active_effects.append({"effect": "auto_revive", "value": True})
    assert p.has_auto_revive() is True
    assert p.consume_auto_revive() is True
    assert p.has_auto_revive() is False

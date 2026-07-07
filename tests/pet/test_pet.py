"""Pet 类单元测试。"""
import pytest
from core.pet.pet import Pet


def test_new_pet_has_default_values():
    p = Pet(name="小白")
    assert p.name == "小白"
    assert p.level == 1
    assert p.exp == 0
    assert p.branch is None
    assert p.hunger == 80
    assert p.mood == 80
    assert p.energy == 100
    assert p.cleanliness == 80
    assert p.exp_multi == 1.0


def test_exp_needed_lv1():
    p = Pet(name="小白", level=1)
    assert p.exp_needed() == 100  # 100 * 1^1.5 = 100


def test_exp_needed_lv5():
    p = Pet(name="小白", level=5)
    assert p.exp_needed() == 1118  # floor(100 * 5^1.5) = floor(1118.03) = 1118


def test_exp_needed_lv10():
    p = Pet(name="小白", level=10)
    assert p.exp_needed() == 3162  # floor(100 * 10^1.5)


def test_exp_remaining_lv1_with_50_exp():
    p = Pet(name="小白", level=1, exp=50)
    assert p.exp_remaining() == 50  # 100 - 50


def test_exp_remaining_max_level():
    p = Pet(name="小白", level=10, exp=5000)
    assert p.exp_remaining() == 0  # 已达最高级


def test_gain_exp_increases_exp():
    p = Pet(name="小白", level=1, exp=0)
    events = p.gain_exp(50, "ingest")
    assert p.exp == 50
    assert p.stats["ingest"] == 1
    assert events["leveled_up"] is False


def test_gain_exp_triggers_level_up():
    p = Pet(name="小白", level=1, exp=50)
    events = p.gain_exp(60, "ingest")  # 50+60=110 > 100
    assert p.level == 2
    assert p.exp == 10  # 110 - 100 = 10
    assert events["leveled_up"] is True
    assert events["new_level"] == 2


def test_gain_exp_multi_level_up():
    p = Pet(name="小白", level=1, exp=0)
    # 一次给 2000 经验，应该连升多级
    events = p.gain_exp(2000, "ingest")
    assert p.level > 2
    assert events["leveled_up"] is True


def test_gain_exp_mood_penalty():
    p = Pet(name="小白", level=1, exp=0, mood=20)  # mood < 30
    p.gain_exp(100, "qa")
    # 经验应该是 100 * 0.7 = 70
    assert p.exp == 70


def test_gain_exp_branch_trigger_at_lv5():
    p = Pet(name="小白", level=4, exp=780, stats={
        "ingest": 10, "qa": 50, "read": 5, "report": 2,
        "agent": 0, "compare": 0,
        "analyze": 0, "smart": 0, "retag": 0,
        "graph_build": 0,
    })
    events = p.gain_exp(50, "qa")  # 升到 Lv5
    assert p.level == 5
    assert p.branch == "scholar"  # scholar 系行为最多
    assert events["branched"] is True
    assert events["branch"] == "scholar"


def test_apply_decay_reduces_attributes():
    from datetime import datetime, timedelta
    p = Pet(name="小白", hunger=90, mood=90, cleanliness=90)
    # 模拟 5 小时前
    p.last_decay = (datetime.now() - timedelta(hours=5)).isoformat()
    decay = p.apply_decay()
    # hunger: -1.5/h * 5h = -7.5 → int(90-7.5) = int(82.5) = 82
    assert p.hunger == 82
    # mood: -0.5/h * 5h = -2.5 → int(90-2.5) = int(87.5) = 87
    assert p.mood == 87
    # cleanliness: -0.3/h * 5h = -1.5 → int(90-1.5) = int(88.5) = 88
    assert p.cleanliness == 88


def test_apply_decay_capped_at_50():
    from datetime import datetime, timedelta
    p = Pet(name="小白", hunger=100, mood=100, cleanliness=100)
    # 模拟 100 小时前
    p.last_decay = (datetime.now() - timedelta(hours=100)).isoformat()
    p.apply_decay()
    # 总衰减封顶 -50
    assert p.hunger >= 50
    assert p.mood >= 50
    assert p.cleanliness >= 50


def test_apply_decay_zero_hunger_deducts_exp():
    from datetime import datetime, timedelta
    p = Pet(name="小白", hunger=0, exp=100)
    p.last_decay = (datetime.now() - timedelta(hours=2)).isoformat()
    p.apply_decay()
    # hunger=0 时每小时扣 10 经验，2 小时扣 20
    assert p.exp == 80


# ---- Group 1: reset_stats / clear_active_effects ----

def test_reset_stats_clears_stats():
    """reset_stats 清空行为统计。"""
    p = Pet(name="小白", stats={
        "ingest": 10, "qa": 50, "read": 5, "report": 2,
        "agent": 0, "compare": 0,
        "analyze": 0, "smart": 0, "retag": 0,
        "graph_build": 0,
    })
    p.reset_stats()
    assert all(v == 0 for v in p.stats.values())
    # 所有 key 仍存在
    assert set(p.stats.keys()) == {
        "ingest", "qa", "read", "report",
        "agent", "compare",
        "analyze", "smart", "retag",
        "graph_build",
    }


def test_reset_stats_preserves_level_exp():
    """reset_stats 不影响等级和经验。"""
    p = Pet(name="小白", level=5, exp=200, stats={
        "ingest": 10, "qa": 50, "read": 5, "report": 2,
        "agent": 0, "compare": 0,
        "analyze": 0, "smart": 0, "retag": 0,
        "graph_build": 0,
    })
    p.reset_stats()
    assert p.level == 5
    assert p.exp == 200


def test_clear_active_effects():
    """clear_active_effects 清空所有限时效果。"""
    p = Pet(name="小白", active_effects=[
        {"effect": "auto_revive", "value": True},
        {"effect": "exp_multi", "value": 2.0, "expires_at": "2026-12-31T23:59:59"},
    ])
    count = p.clear_active_effects()
    assert count == 2
    assert p.active_effects == []


def test_clear_active_effects_empty():
    """空效果列表清空返回 0。"""
    p = Pet(name="小白")
    count = p.clear_active_effects()
    assert count == 0
    assert p.active_effects == []

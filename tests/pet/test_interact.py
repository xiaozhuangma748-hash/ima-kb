"""互动命令测试。"""
import pytest
from core.pet.pet import Pet
from core.pet.interact import PetInteractor, InteractError


def test_feed_increases_hunger():
    p = Pet(name="小白", hunger=50, energy=80, exp=100)
    interactor = PetInteractor()
    result = interactor.feed(p)
    assert p.hunger == 80  # 50 + 30
    assert p.energy == 70  # 80 - 10
    assert p.exp == 95  # 100 - 5
    assert p.mood == 85  # 80 + 5
    assert "吃饱了" in result["message"]


def test_play_increases_mood():
    p = Pet(name="小白", mood=50, energy=80, hunger=80)
    interactor = PetInteractor()
    result = interactor.play(p)
    assert p.mood == 90  # 50 + 40
    assert p.energy == 65  # 80 - 15
    assert p.hunger == 70  # 80 - 10
    assert p.exp == 10  # 0 + 10
    assert "开心" in result["message"]


def test_train_gives_exp():
    p = Pet(name="小白", energy=80, mood=80)
    interactor = PetInteractor()
    result = interactor.train(p)
    assert p.energy == 55  # 80 - 25
    assert p.mood == 70  # 80 - 10
    assert p.exp == 50
    assert "学到" in result["message"]


def test_train_blocked_by_low_energy():
    p = Pet(name="小白", energy=5)  # < 10
    interactor = PetInteractor()
    with pytest.raises(InteractError) as exc:
        interactor.train(p)
    assert "累" in str(exc.value)


def test_train_blocked_by_low_hunger():
    p = Pet(name="小白", energy=80, hunger=10)  # < 20
    interactor = PetInteractor()
    with pytest.raises(InteractError) as exc:
        interactor.train(p)
    assert "饿" in str(exc.value)


def test_train_mood_penalty_halves_exp():
    """train 内 mood<20 时经验减半（25），再经 gain_exp 的 mood<30 全局惩罚 ×0.7 = 17。

    双层惩罚设计：train 主动检查 + gain_exp 全局检查。
    """
    p = Pet(name="小白", energy=80, mood=20)  # mood=20 不算 <20，train 给 50
    interactor = PetInteractor()
    interactor.train(p)
    # mood=20 ≥ 20，train 给 50；但 mood=20 < 30，gain_exp 再 ×0.7 = 35
    assert p.exp == 35

    p2 = Pet(name="小白", energy=80, mood=19)  # < 20，train 给 25
    interactor.train(p2)
    # mood=19 < 20，train 给 25；mood=19 < 30，gain_exp 再 ×0.7 = 17
    assert p2.exp == 17


def test_wash_increases_cleanliness():
    p = Pet(name="小白", cleanliness=30, energy=80)
    interactor = PetInteractor()
    result = interactor.wash(p)
    assert p.cleanliness == 80  # 30 + 50
    assert p.energy == 75  # 80 - 5
    assert p.mood == 85  # 80 + 5


def test_sleep_restores_energy():
    p = Pet(name="小白", energy=30)
    interactor = PetInteractor()
    result = interactor.sleep(p)
    assert p.energy == 80  # 30 + 50
    assert p.mood == 90  # 80 + 10

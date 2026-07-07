"""集成测试：模拟完整使用流程。"""
from core.pet.pet import Pet
from core.pet.storage import PetStorage
from core.pet.interact import PetInteractor
from core.pet.tasks import DailyTaskManager
from core.pet.shop import Shop


def test_full_lifecycle(tmp_path):
    """完整生命周期：领养 → 入库 → 升级 → 重新加载。"""
    storage = PetStorage(storage_path=tmp_path)
    pet = storage.create("小白")
    assert pet.level == 1

    # 模拟入库 2 个文档（每次 50 经验，共 100 经验升 Lv2）
    pet.gain_exp(50, "ingest")
    pet.gain_exp(50, "ingest")
    assert pet.level == 2  # 100 经验升 Lv2

    storage.save(pet)

    # 重新加载
    loaded = storage.load()
    assert loaded is not None
    assert loaded.name == "小白"
    assert loaded.level == 2


def test_branch_determination_after_lv5(tmp_path):
    """Lv5 时根据行为统计自动分系。

    大量 qa 行为（scholar 系）占绝对多数，确保分到 scholar 系而非随机平局。
    """
    pet = Pet(name="小白", level=4, exp=780)
    # 大量 qa 行为（scholar 系行为）
    for _ in range(20):
        pet.gain_exp(5, "qa")
    # 升到 Lv5 应该触发分系
    assert pet.level >= 5
    assert pet.branch == "scholar"  # qa 行为占绝对多数


def test_daily_task_completes_on_qa(tmp_path):
    """每日任务在问答时完成。"""
    pet = Pet(name="小白")
    mgr = DailyTaskManager()
    mgr.refresh(pet=pet)
    # 强制设置 qa5 任务（progress=4，再触发 1 次即完成）
    pet.daily_tasks = [{
        "task_id": "qa5",
        "description": "问 5 个问题",
        "target": 5,
        "reward": 80,
        "progress": 4,
        "completed": False,
        "action": "qa",
    }]
    completed = mgr.check_progress(pet, "qa")
    assert len(completed) == 1
    assert completed[0]["reward"] == 80


def test_shop_buy_and_use_flow(tmp_path):
    """购买并使用道具。"""
    pet = Pet(name="小白", exp=500, hunger=50)
    shop = Shop()
    shop.buy(pet, "fish")
    assert pet.exp == 450  # 500 - 50
    shop.use(pet, "fish")
    assert pet.hunger == 80  # 50 + 30


def test_decay_applied_on_load(tmp_path):
    """加载时应用衰减。"""
    from datetime import datetime, timedelta
    storage = PetStorage(storage_path=tmp_path)
    pet = storage.create("小白")
    pet.hunger = 100
    pet.last_decay = (datetime.now() - timedelta(hours=10)).isoformat()
    storage.save(pet)

    loaded = storage.load()
    assert loaded is not None
    decay = loaded.apply_decay()
    assert decay["hours"] >= 10
    assert loaded.hunger < 100  # 衰减了

"""宠物互动意图短路测试。

验证两个入口都能真正更新宠物状态（而非 LLM "嘴上喂"）：
1. 直接对话入口（_handle_chat）经 _detect_pet_intent 短路到 _pet_interact
2. Agent 工具入口（PetInteractTool）经 ToolContext 调 PetInteractor 真正更新状态
3. 宠物状态查询：_is_pet_query + PetStatusTool 返回真实数据
4. 宠物改名：_extract_rename_target + PetManageTool
5. 宠物商店：PetShopTool 购买/使用道具
"""
from unittest.mock import MagicMock

import pytest

from core.pet.pet import Pet
from core.pet.interact import PetInteractor
from core.pet.shop import Shop
from core.agent.tools.builtin import (
    PetInteractTool,
    PetStatusTool,
    PetManageTool,
    PetShopTool,
)
from core.agent.tools.base import ToolContext
from core.cli.chat import (
    _detect_pet_intent,
    _is_pet_query,
    _extract_rename_target,
)


# ============================================================
# 1. 意图识别（_detect_pet_intent）
# ============================================================

class TestDetectPetIntent:
    """自然语言 → 互动动作 识别。"""

    @pytest.mark.parametrize("text,expected", [
        ("帮我喂一下宠物", "feed"),
        ("帮我喂食", "feed"),
        ("给宠物吃的", "feed"),
        ("投喂一下", "feed"),
        ("陪我宠物玩一会", "play"),
        ("逗一下宠物", "play"),
        ("帮我清理一下宠物活动区域", "wash"),
        ("给宠物洗个澡", "wash"),
        ("打扫宠物区域", "wash"),
        ("让宠物睡一会儿", "sleep"),
        ("让宠物休息", "sleep"),
        ("训练宠物", "train"),
    ])
    def test_hit(self, text, expected):
        assert _detect_pet_intent(text) == expected

    @pytest.mark.parametrize("text", [
        "",                          # 空
        "x" * 100,                   # 过长，不走短路
        "骨灰撒江的政策是什么？",     # 正经问答，无宠物关键词
        "今天天气怎么样",             # 无关
        "帮我查一下海葬文件",         # "查" 不在宠物词表
    ])
    def test_miss(self, text):
        assert _detect_pet_intent(text) is None

    def test_strips_leading_polite_words(self):
        """前导"帮我/请/给"等口语词不干扰识别。"""
        assert _detect_pet_intent("请喂宠物") == "feed"
        assert _detect_pet_intent("能不能陪宠物玩") == "play"


# ============================================================
# 2. 直接对话入口短路（_handle_chat → _pet_interact）
# ============================================================

class _DummyChatREPL:
    """只暴露 _handle_chat 依赖的属性的极简 stub。"""

    def __init__(self, pet):
        self.pet = pet
        self.pet_interactor = PetInteractor()
        self.pet_storage = MagicMock()
        # 记录 _pet_interact 是否被调用
        self.interacted = []

    # 从 ChatMixin 借用 _handle_chat
    from core.cli.chat import ChatMixin as _ChatMixin

    def _pet_interact(self, action):
        """复刻 PetMixin._pet_interact 的核心逻辑（避免继承整套 Mixin）。"""
        self.interacted.append(action)
        method = getattr(self.pet_interactor, action)
        result = method(self.pet)
        self.pet_storage.save(self.pet)
        return result

    _handle_chat = _ChatMixin._handle_chat


class TestHandleChatShortcut:
    """_handle_chat 入口应短路到 _pet_interact，不调 LLM。"""

    def test_feed_intent_triggers_real_interact(self):
        """说"帮我喂一下宠物"应真正更新 hunger，不调 LLM。"""
        pet = Pet(name="小白", hunger=10, energy=80)
        repl = _DummyChatREPL(pet=pet)

        # llm_available=True 但不应被用到；若短路失败会因无 LLM 配置报错
        repl.llm_available = True
        repl.administrator = None
        repl._admin_init_failed = False

        repl._handle_chat("帮我喂一下宠物")

        # 验证：真正调了 feed，hunger 增加
        assert repl.interacted == ["feed"]
        assert pet.hunger == 40  # 10 + 30
        # pet_storage.save 应被调用（状态已持久化）
        assert repl.pet_storage.save.called

    def test_no_pet_no_crash(self):
        """无宠物时不应短路，也不应崩溃（走 LLM 降级路径）。"""
        repl = _DummyChatREPL(pet=None)
        repl.llm_available = False  # 让 LLM 检查直接 return
        repl.administrator = None
        repl._admin_init_failed = False

        # 不应抛异常，且不应调用 _pet_interact
        repl._handle_chat("帮我喂一下宠物")
        assert repl.interacted == []


# ============================================================
# 3. Agent 工具入口（PetInteractTool）
# ============================================================

class TestPetInteractTool:
    """PetInteractTool 应真正更新宠物状态。"""

    def test_feed_really_updates_hunger(self):
        pet = Pet(name="小白", hunger=10, energy=80)
        pet_storage = MagicMock()
        ctx = ToolContext(
            pet=pet,
            pet_interactor=PetInteractor(),
            pet_storage=pet_storage,
        )
        tool = PetInteractTool()

        result = tool.execute_from_str("feed", context=ctx)

        # 状态真正更新
        assert pet.hunger == 40  # 10 + 30
        # 持久化保存
        assert pet_storage.save.called
        # 返回内容包含真实状态
        assert "饱食 40/100" in result

    def test_wash_really_updates_cleanliness(self):
        pet = Pet(name="小白", cleanliness=10, energy=80)
        ctx = ToolContext(
            pet=pet,
            pet_interactor=PetInteractor(),
            pet_storage=MagicMock(),
        )
        tool = PetInteractTool()

        result = tool.execute_from_str("wash", context=ctx)

        assert pet.cleanliness == 60  # 10 + 50
        assert "清洁 60/100" in result

    def test_invalid_action_returns_error(self):
        pet = Pet(name="小白")
        ctx = ToolContext(pet=pet, pet_interactor=PetInteractor())
        tool = PetInteractTool()

        result = tool.execute_from_str("dance", context=ctx)

        assert "[错误]" in result
        assert "dance" in result

    def test_no_pet_returns_disabled_hint(self):
        """未注入 pet 时返回明确提示，避免 LLM 误以为已执行。"""
        ctx = ToolContext()  # 全部依赖为 None
        tool = PetInteractTool()

        result = tool.execute_from_str("feed", context=ctx)

        assert "[未启用]" in result
        assert "领养" in result

    def test_blocked_by_low_energy_returns_failure(self):
        """能量不足时返回失败提示，状态不变。"""
        pet = Pet(name="小白", energy=5, hunger=10)  # energy<10 会阻断 feed
        ctx = ToolContext(
            pet=pet,
            pet_interactor=PetInteractor(),
            pet_storage=MagicMock(),
        )
        tool = PetInteractTool()

        result = tool.execute_from_str("feed", context=ctx)

        assert "[互动失败]" in result
        # 状态未变
        assert pet.hunger == 10
        # 不应保存
        assert not ctx.pet_storage.save.called


# ============================================================
# 4. 端到端：状态变化持久化到 pet_storage
# ============================================================

class TestEndToEndPersistence:
    """验证两个入口的状态变化都被持久化。"""

    def test_chat_shortcut_persists(self):
        pet = Pet(name="小白", hunger=10, energy=80)
        repl = _DummyChatREPL(pet=pet)
        repl.llm_available = True
        repl.administrator = None
        repl._admin_init_failed = False

        repl._handle_chat("帮我喂一下宠物")

        # pet_storage.save 被调用且参数是更新后的 pet
        save_call_args = repl.pet_storage.save.call_args
        saved_pet = save_call_args.args[0]
        assert saved_pet.hunger == 40

    def test_agent_tool_persists(self):
        pet = Pet(name="小白", hunger=10, energy=80)
        pet_storage = MagicMock()
        ctx = ToolContext(
            pet=pet,
            pet_interactor=PetInteractor(),
            pet_storage=pet_storage,
        )

        PetInteractTool().execute_from_str("feed", context=ctx)

        saved_pet = pet_storage.save.call_args.args[0]
        assert saved_pet.hunger == 40


# ============================================================
# 5. 宠物状态查询（_is_pet_query + PetStatusTool）
# ============================================================

class TestPetQueryDetection:
    """查询意图识别。"""

    @pytest.mark.parametrize("text", [
        "宠物能量还有吗",
        "宠物状态怎么样",
        "宠物饱食多少",
        "宠物心情还好吗",
        "宠物等级多少",
        "宠物有什么道具",
        "宠物道具栏",
        "宠物任务进度",
    ])
    def test_query_hit(self, text):
        assert _is_pet_query(text) is True

    @pytest.mark.parametrize("text", [
        "",                          # 空
        "x" * 100,                   # 过长
        "骨灰撒江的政策是什么",       # 无宠物上下文
        "今天天气怎么样",             # 无宠物
        "海葬文件有哪些",             # 无宠物
    ])
    def test_query_miss(self, text):
        assert _is_pet_query(text) is False


class TestPetStatusTool:
    """PetStatusTool 应返回真实状态数据。"""

    def test_returns_real_attributes(self):
        """查询状态返回的应是 pet 的真实属性。"""
        pet = Pet(name="小白", hunger=42, mood=67, energy=88, cleanliness=15, level=3, exp=100)
        ctx = ToolContext(pet=pet)
        tool = PetStatusTool()

        result = tool.execute_from_str("", context=ctx)

        assert "小白" in result
        assert "Lv3" in result
        assert "饱食 42/100" in result
        assert "心情 67/100" in result
        assert "能量 88/100" in result
        assert "清洁 15/100" in result
        assert "100/519" in result  # exp/exp_needed

    def test_shows_inventory(self):
        pet = Pet(name="小白")
        pet.inventory = [{"item_id": "fish", "count": 2}, {"item_id": "ball", "count": 1}]
        ctx = ToolContext(pet=pet)

        result = PetStatusTool().execute_from_str("", context=ctx)

        assert "fish×2" in result
        assert "ball×1" in result

    def test_shows_empty_inventory(self):
        pet = Pet(name="小白")
        ctx = ToolContext(pet=pet)

        result = PetStatusTool().execute_from_str("", context=ctx)

        assert "道具栏：空" in result

    def test_shows_daily_tasks(self):
        """注入 task_manager 且有任务时显示任务进度。"""
        pet = Pet(name="小白")
        pet.daily_tasks = [
            {"description": "问 5 个问题", "target": 5, "progress": 2, "reward": 80, "completed": False},
            {"description": "入库 1 个文档", "target": 1, "progress": 1, "reward": 100, "completed": True},
        ]
        task_mgr = MagicMock()
        ctx = ToolContext(pet=pet, pet_task_manager=task_mgr)

        result = PetStatusTool().execute_from_str("", context=ctx)

        assert "问 5 个问题" in result
        assert "2/5" in result
        assert "入库 1 个文档" in result
        assert "✓" in result

    def test_no_pet_returns_disabled_hint(self):
        ctx = ToolContext()
        result = PetStatusTool().execute_from_str("", context=ctx)
        assert "[未启用]" in result


# ============================================================
# 6. 宠物改名（_extract_rename_target + PetManageTool）
# ============================================================

class TestRenameExtraction:
    """改名意图识别。"""

    @pytest.mark.parametrize("text,expected", [
        ("给宠物改名叫小黑", "小黑"),
        ("宠物改名小白", "小白"),
        ("宠物名字改成阿黄", "阿黄"),
        ("宠物名字改为大黄", "大黄"),
        ("帮宠物重新命名为小花", "小花"),
        ("帮宠物重新命名小绿", "小绿"),
    ])
    def test_extract_hit(self, text, expected):
        assert _extract_rename_target(text) == expected

    @pytest.mark.parametrize("text", [
        "",                                  # 空
        "我叫张三",                          # 无宠物上下文
        "宠物状态怎么样",                    # 不是改名
        "帮我喂一下宠物",                    # 互动意图
        "x" * 100,                           # 过长
    ])
    def test_extract_miss(self, text):
        assert _extract_rename_target(text) is None


class TestPetManageTool:
    """PetManageTool 改名/重置操作。"""

    def test_rename_really_changes_name(self):
        pet = Pet(name="小白")
        pet_storage = MagicMock()
        ctx = ToolContext(pet=pet, pet_storage=pet_storage)

        result = PetManageTool().execute_from_str("rename 小黑", context=ctx)

        assert pet.name == "小黑"
        assert "小白" in result and "小黑" in result
        assert pet_storage.save.called

    def test_rename_empty_value_returns_error(self):
        pet = Pet(name="小白")
        ctx = ToolContext(pet=pet)

        result = PetManageTool().execute_from_str("rename", context=ctx)

        assert "[错误]" in result
        assert pet.name == "小白"  # 未改变

    def test_reset_stats_clears_stats(self):
        pet = Pet(name="小白")
        pet.stats["qa"] = 10
        pet.stats["ingest"] = 5
        ctx = ToolContext(pet=pet, pet_storage=MagicMock())

        result = PetManageTool().execute_from_str("reset_stats", context=ctx)

        assert "✓" in result
        assert pet.stats["qa"] == 0
        assert pet.stats["ingest"] == 0

    def test_reset_effects_clears_active_effects(self):
        pet = Pet(name="小白")
        pet.active_effects = [{"effect": "exp_multi", "value": 2.0}]
        ctx = ToolContext(pet=pet, pet_storage=MagicMock())

        result = PetManageTool().execute_from_str("reset_effects", context=ctx)

        assert "✓" in result
        assert "1" in result
        assert pet.active_effects == []

    def test_invalid_action_returns_error(self):
        pet = Pet(name="小白")
        ctx = ToolContext(pet=pet)

        result = PetManageTool().execute_from_str("dance", context=ctx)

        assert "[错误]" in result

    def test_no_pet_returns_disabled(self):
        ctx = ToolContext()
        result = PetManageTool().execute_from_str("rename 小黑", context=ctx)
        assert "[未启用]" in result


# ============================================================
# 7. 宠物商店（PetShopTool）
# ============================================================

class TestPetShopTool:
    """PetShopTool 查看/购买/使用道具。"""

    def test_list_shows_all_items(self):
        """list 不需要 pet 也能返回商店道具列表。"""
        ctx = ToolContext(pet_shop=Shop())

        result = PetShopTool().execute_from_str("list", context=ctx)

        assert "道具商店" in result
        assert "fish" in result
        assert "能量饮料" in result or "energy_drink" in result

    def test_list_works_without_shop(self):
        """未注入 shop 时降级读静态 ITEMS。"""
        ctx = ToolContext()

        result = PetShopTool().execute_from_str("list", context=ctx)

        assert "道具商店" in result
        assert "fish" in result

    def test_buy_really_deducts_exp(self):
        """购买道具应真正扣除经验。"""
        pet = Pet(name="小白", exp=200)
        pet_storage = MagicMock()
        ctx = ToolContext(
            pet=pet,
            pet_shop=Shop(),
            pet_storage=pet_storage,
        )

        result = PetShopTool().execute_from_str("buy fish", context=ctx)

        # fish 价格 50
        assert pet.exp == 150
        assert "购买成功" in result
        assert pet_storage.save.called
        # 道具应入库
        assert any(slot["item_id"] == "fish" for slot in pet.inventory)

    def test_buy_insufficient_exp_returns_error(self):
        """经验不足应返回失败，不扣经验。"""
        pet = Pet(name="小白", exp=10)  # 不够买 fish (50)
        ctx = ToolContext(pet=pet, pet_shop=Shop(), pet_storage=MagicMock())

        result = PetShopTool().execute_from_str("buy fish", context=ctx)

        assert "失败" in result or "经验不足" in result
        assert pet.exp == 10  # 未扣

    def test_use_really_applies_effect(self):
        """使用道具应真正应用效果到 pet 属性。"""
        pet = Pet(name="小白", hunger=10, energy=80)
        pet.inventory = [{"item_id": "fish", "count": 2}]
        pet_storage = MagicMock()
        ctx = ToolContext(
            pet=pet,
            pet_shop=Shop(),
            pet_storage=pet_storage,
        )

        result = PetShopTool().execute_from_str("use fish", context=ctx)

        # fish: hunger+30
        assert pet.hunger == 40
        # 库存 -1
        assert pet.inventory[0]["count"] == 1
        assert pet_storage.save.called

    def test_use_nonexistent_item_returns_error(self):
        """使用没有的道具应失败。"""
        pet = Pet(name="小白")
        ctx = ToolContext(pet=pet, pet_shop=Shop(), pet_storage=MagicMock())

        result = PetShopTool().execute_from_str("use fish", context=ctx)

        assert "失败" in result or "没有" in result

    def test_buy_without_pet_returns_disabled(self):
        ctx = ToolContext()  # 无 pet/shop
        # buy 路径需要 pet
        result = PetShopTool().execute_from_str("buy fish", context=ctx)
        assert "[未启用]" in result


# ============================================================
# 8. 直接对话查询意图短路（_handle_chat → _pet_answer_query）
# ============================================================

class _DummyChatREPLWithQuery:
    """扩展 stub：支持 _pet_answer_query 验证。"""

    def __init__(self, pet):
        self.pet = pet
        self.pet_interactor = PetInteractor()
        self.pet_storage = MagicMock()
        self.pet_shop = Shop()
        self.task_manager = MagicMock()
        self.art_lib = MagicMock()
        self.interacted = []
        self.renamed_to = None
        self.query_answered = False

    from core.cli.chat import ChatMixin as _ChatMixin
    from core.cli.commands.pet import PetMixin as _PetMixin

    def _pet_interact(self, action):
        self.interacted.append(action)
        method = getattr(self.pet_interactor, action)
        result = method(self.pet)
        self.pet_storage.save(self.pet)
        return result

    def _pet_rename(self, new_name):
        self.renamed_to = new_name
        old = self.pet.name
        self.pet.name = new_name
        self.pet_storage.save(self.pet)

    def _pet_answer_query(self):
        self.query_answered = True
        # 复用 PetMixin 的实现
        return self._PetMixin._pet_answer_query(self)

    _handle_chat = _ChatMixin._handle_chat


class TestHandleChatQueryShortcut:
    """_handle_chat 入口应短路到 _pet_answer_query。"""

    def test_query_intent_triggers_real_status(self):
        """问"宠物能量还有吗"应返回真实能量，不调 LLM。"""
        pet = Pet(name="小白", energy=35, hunger=42)
        repl = _DummyChatREPLWithQuery(pet=pet)
        repl.llm_available = True
        repl.administrator = None
        repl._admin_init_failed = False

        repl._handle_chat("宠物能量还有吗")

        # 验证：走了查询短路，没走 LLM
        assert repl.query_answered is True
        assert repl.interacted == []
        assert repl.renamed_to is None

    def test_rename_intent_triggers_real_rename(self):
        """说"给宠物改名叫小黑"应真正改名。"""
        pet = Pet(name="小白")
        repl = _DummyChatREPLWithQuery(pet=pet)
        repl.llm_available = True
        repl.administrator = None
        repl._admin_init_failed = False

        repl._handle_chat("给宠物改名叫小黑")

        assert repl.renamed_to == "小黑"
        assert pet.name == "小黑"
        assert repl.pet_storage.save.called


# ============================================================
# 9. 恢复能量智能路由（restore_energy）
# ============================================================

class TestRestoreEnergyDetection:
    """加能量意图识别。"""

    @pytest.mark.parametrize("text", [
        "帮我把能量加一下",
        "加能量",
        "补充能量",
        "恢复能量",
        "能量加一下",
        "充能",
        "回能",
        "补能量",
        "回血",
    ])
    def test_restore_energy_hit(self, text):
        assert _detect_pet_intent(text) == "restore_energy"

    @pytest.mark.parametrize("text", [
        "宠物能量还有吗",  # 这是查询，不是恢复
        "帮我喂一下",      # 这是喂食
    ])
    def test_restore_energy_miss(self, text):
        # 查询类不应被识别为 restore_energy
        assert _detect_pet_intent(text) != "restore_energy"


class TestPetInteractToolRestoreEnergy:
    """PetInteractTool 的 restore_energy 智能路由。"""

    def test_restore_energy_uses_drink_first(self):
        """有 energy_drink 时优先用道具（无冷却）。"""
        pet = Pet(name="小白", energy=10)
        pet.inventory = [{"item_id": "energy_drink", "count": 2}]
        ctx = ToolContext(
            pet=pet,
            pet_interactor=PetInteractor(),
            pet_shop=Shop(),
            pet_storage=MagicMock(),
        )

        result = PetInteractTool().execute_from_str("restore_energy", context=ctx)

        # 能量饮料 +50
        assert pet.energy == 60
        # 库存 -1
        assert pet.inventory[0]["count"] == 1
        assert "能量饮料" in result
        assert "60/100" in result

    def test_restore_energy_falls_back_to_sleep(self):
        """无道具时降级到 sleep。"""
        pet = Pet(name="小白", energy=10)
        # 无道具，无 last_interact（sleep 不会冷却）
        ctx = ToolContext(
            pet=pet,
            pet_interactor=PetInteractor(),
            pet_shop=Shop(),
            pet_storage=MagicMock(),
        )

        result = PetInteractTool().execute_from_str("restore_energy", context=ctx)

        # sleep +50
        assert pet.energy == 60
        assert "60/100" in result

    def test_restore_energy_sleep_cooldown_suggests_shop(self):
        """sleep 冷却中应提示去商店购买。"""
        from datetime import datetime, timedelta
        pet = Pet(name="小白", energy=10)
        # 设置 last_interact 为 1 分钟前，触发 1h 冷却
        pet.last_interact = (datetime.now() - timedelta(minutes=1)).isoformat()
        ctx = ToolContext(
            pet=pet,
            pet_interactor=PetInteractor(),
            pet_shop=Shop(),
            pet_storage=MagicMock(),
        )

        result = PetInteractTool().execute_from_str("restore_energy", context=ctx)

        # 能量未变
        assert pet.energy == 10
        # 提示购买能量饮料
        assert "恢复失败" in result or "冷却" in result
        assert "energy_drink" in result or "商店" in result or "pet_shop" in result

    def test_restore_energy_full_returns_noop(self):
        """能量已满无需恢复。"""
        pet = Pet(name="小白", energy=100)
        ctx = ToolContext(
            pet=pet,
            pet_interactor=PetInteractor(),
            pet_shop=Shop(),
            pet_storage=MagicMock(),
        )

        result = PetInteractTool().execute_from_str("restore_energy", context=ctx)

        assert "已满" in result
        assert pet.energy == 100

    def test_restore_energy_no_shop_no_drink_uses_sleep(self):
        """无 shop 注入但有 interactor，仍能走 sleep 路径。"""
        pet = Pet(name="小白", energy=10)
        ctx = ToolContext(
            pet=pet,
            pet_interactor=PetInteractor(),
            pet_storage=MagicMock(),
            # pet_shop=None
        )

        result = PetInteractTool().execute_from_str("restore_energy", context=ctx)

        # 走 sleep（无道具可用）
        assert pet.energy == 60
        assert "60/100" in result


class TestHandleChatRestoreEnergyShortcut:
    """_handle_chat 入口应短路到 _pet_restore_energy。"""

    def test_restore_energy_intent_triggers_smart_route(self):
        """说"帮我把能量加一下"应走智能路由，不调 LLM。"""
        pet = Pet(name="小白", energy=10)
        repl = _DummyChatREPLWithQuery(pet=pet)
        repl.llm_available = True
        repl.administrator = None
        repl._admin_init_failed = False
        repl.restore_energy_called = False

        # 覆盖 _pet_restore_energy 记录调用
        def _pet_restore_energy():
            repl.restore_energy_called = True
            # 真正执行：用 sleep 恢复
            result = repl.pet_interactor.sleep(pet)
            repl.pet_storage.save(pet)
            return result
        repl._pet_restore_energy = _pet_restore_energy

        repl._handle_chat("帮我把能量加一下")

        # 验证：走了智能路由，能量真正恢复
        assert repl.restore_energy_called is True
        assert pet.energy == 60  # 10 + 50
        assert repl.pet_storage.save.called
        # 没走 LLM
        assert repl.interacted == []
        assert repl.query_answered is False

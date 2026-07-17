"""领养宠物后记忆模块初始化测试。

回归场景：用户启动 REPL 时无宠物，self.memory_store 为 None；
之后执行 /pet adopt 领养宠物，memory_store 应被同步初始化，
否则 /memory show 会报"记忆模块未初始化（需要先领养宠物）"。
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from core.pet.pet import Pet
from core.cli.commands.pet import PetMixin


class _DummyRePL(PetMixin):
    """只暴露 _pet_adopt 依赖的属性的极简 stub。"""

    def __init__(self):
        self.pet = None
        self.pet_storage = MagicMock()
        self.memory_store = None
        self.workflow_tracker = None
        self.pet_interactor = MagicMock()

    def _pet_show_status(self):
        """领养成功后会调用，这里空实现避免依赖 Rich console。"""
        pass


class TestPetAdoptInitializesMemory:
    """_pet_adopt 领养后应同步初始化 memory_store 和 workflow_tracker。"""

    def test_adopt_initializes_memory_store(self):
        """领养前 memory_store=None，领养后应为 MemoryStore 实例。"""
        repl = _DummyRePL()
        assert repl.memory_store is None
        assert repl.workflow_tracker is None

        # pet_storage.create 返回一个真实 Pet 对象
        repl.pet_storage.create.return_value = Pet(name="小林同学")

        repl._pet_adopt("小林同学")

        assert repl.pet is not None
        assert repl.pet.name == "小林同学"
        from core.memory.store import MemoryStore
        from core.memory.workflow import WorkflowTracker
        assert isinstance(repl.memory_store, MemoryStore), \
            "领养后 memory_store 应为 MemoryStore 实例"
        assert isinstance(repl.workflow_tracker, WorkflowTracker), \
            "领养后 workflow_tracker 应为 WorkflowTracker 实例"

    def test_adopt_calls_pet_storage_create(self):
        """领养应调用 pet_storage.create。"""
        repl = _DummyRePL()
        repl.pet_storage.create.return_value = Pet(name="TestPet")

        repl._pet_adopt("TestPet")

        repl.pet_storage.create.assert_called_once_with("TestPet")

    def test_adopt_refuses_when_pet_exists(self):
        """已有宠物时应拒绝重复领养，且不影响 memory_store。"""
        repl = _DummyRePL()
        repl.pet = Pet(name="ExistingPet")
        # 手动设置 memory_store 模拟已初始化
        from core.memory.store import MemoryStore
        original_store = MemoryStore()
        repl.memory_store = original_store

        repl._pet_adopt("NewPet")

        # 不应调用 create
        repl.pet_storage.create.assert_not_called()
        # memory_store 应保持原样（不被替换）
        assert repl.memory_store is original_store
        # pet 应保持原样
        assert repl.pet.name == "ExistingPet"

    def test_adopt_refuses_empty_name(self):
        """名字为空时应拒绝。"""
        repl = _DummyRePL()

        repl._pet_adopt("")

        assert repl.pet is None
        assert repl.memory_store is None
        repl.pet_storage.create.assert_not_called()

    def test_adopt_preserves_existing_memory_store(self):
        """若 memory_store 已存在（如重启 REPL 时 pet 已加载），领养新宠物不应重建。"""
        repl = _DummyRePL()
        from core.memory.store import MemoryStore
        original_store = MemoryStore()
        repl.memory_store = original_store
        repl.pet_storage.create.return_value = Pet(name="NewPet")

        # 模拟已有宠物但用户想领养新宠物的场景（实际会被拒绝，但验证 memory_store 不被重建）
        # 这里直接测试 memory_store 已存在时不重新初始化的逻辑
        # 通过 _pet_adopt 的拒绝路径验证
        repl.pet = Pet(name="OldPet")
        repl._pet_adopt("NewPet")
        assert repl.memory_store is original_store

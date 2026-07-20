"""桌面宠物位置记忆与勿扰模式测试（Task 9）。

验证 ``core.desktop.settings`` 模块的核心契约：
1. ``DesktopPetSettings`` 默认构造所有字段为默认值。
2. 自定义参数构造字段正确赋值。
3. ``to_dict`` / ``from_dict`` 字典序列化往返一致。
4. ``load`` 在配置文件缺失时返回默认实例。
5. ``save`` + ``load`` 往返：字段一致、文件实际生成。
6. ``update_position`` / ``update_size``（合法/非法）/ ``toggle_*`` 行为正确。
7. ``DndFilter`` 在 dnd 关闭时不静默；dnd 开启时静默自动触发，不静默手动触发。
8. ``DndFilter.should_play_sound`` 综合 sound / dnd / is_manual 判断正确。

测试不依赖实际 storage 目录：通过 ``tmp_path`` + ``monkeypatch`` 替换
``get_storage_path`` 返回临时路径，确保测试隔离。
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from core.desktop.settings import DesktopPetSettings, DndFilter
from core.desktop.states import PetState


# ------------------------------------------------------------------
# 默认构造与自定义构造
# ------------------------------------------------------------------

def test_settings_defaults():
    """默认构造时所有字段应为默认值。"""
    s = DesktopPetSettings()
    assert s.x == DesktopPetSettings.DEFAULT_X == 100
    assert s.y == DesktopPetSettings.DEFAULT_Y == 100
    assert s.size == DesktopPetSettings.DEFAULT_SIZE == "M"
    assert s.mini_mode is DesktopPetSettings.DEFAULT_MINI is False
    assert s.dnd is DesktopPetSettings.DEFAULT_DND is False
    assert s.sound is DesktopPetSettings.DEFAULT_SOUND is True


def test_settings_custom_init():
    """自定义参数构造：所有字段应被正确赋值。"""
    s = DesktopPetSettings(
        x=250,
        y=350,
        size="L",
        mini_mode=True,
        dnd=True,
        sound=False,
    )
    assert s.x == 250
    assert s.y == 350
    assert s.size == "L"
    assert s.mini_mode is True
    assert s.dnd is True
    assert s.sound is False


# ------------------------------------------------------------------
# 字典序列化
# ------------------------------------------------------------------

def test_settings_to_dict():
    """``to_dict`` 应返回包含所有字段的字典。"""
    s = DesktopPetSettings(x=10, y=20, size="S", mini_mode=True, dnd=True, sound=False)
    d = s.to_dict()
    assert d == {
        "x": 10,
        "y": 20,
        "size": "S",
        "mini_mode": True,
        "dnd": True,
        "sound": False,
    }


def test_settings_from_dict():
    """``from_dict`` 应正确构造实例，缺省字段回退到默认值。"""
    # 完整字典
    s1 = DesktopPetSettings.from_dict({
        "x": 1, "y": 2, "size": "L",
        "mini_mode": True, "dnd": True, "sound": False,
    })
    assert s1.x == 1 and s1.y == 2 and s1.size == "L"
    assert s1.mini_mode is True and s1.dnd is True and s1.sound is False

    # 空字典：所有字段使用默认值
    s2 = DesktopPetSettings.from_dict({})
    assert s2.x == 100 and s2.y == 100 and s2.size == "M"
    assert s2.mini_mode is False and s2.dnd is False and s2.sound is True


# ------------------------------------------------------------------
# load / save 持久化
# ------------------------------------------------------------------

def test_settings_load_missing_file(tmp_path, monkeypatch):
    """``load`` 在配置文件不存在时应返回默认实例。"""
    missing = tmp_path / "nonexistent.json"
    monkeypatch.setattr(
        DesktopPetSettings, "get_storage_path",
        classmethod(lambda cls: missing),
    )

    s = DesktopPetSettings.load()
    assert isinstance(s, DesktopPetSettings)
    assert s.x == 100 and s.y == 100 and s.size == "M"
    assert s.mini_mode is False and s.dnd is False and s.sound is True
    assert not missing.exists(), "load 不应创建文件"


def test_settings_save_and_load(tmp_path, monkeypatch):
    """``save`` 写入文件，``load`` 读回后字段应一致。"""
    config_path = tmp_path / "desktop_pet.json"
    monkeypatch.setattr(
        DesktopPetSettings, "get_storage_path",
        classmethod(lambda cls: config_path),
    )

    s = DesktopPetSettings(x=200, y=300, size="L", mini_mode=True, dnd=True, sound=False)
    assert s.save() is True
    assert config_path.exists(), "save 后配置文件应存在"

    # 文件内容应为合法 JSON
    data = json.loads(config_path.read_text(encoding="utf-8"))
    assert data["x"] == 200 and data["y"] == 300 and data["size"] == "L"
    assert data["mini_mode"] is True and data["dnd"] is True and data["sound"] is False

    # load 回来字段一致
    loaded = DesktopPetSettings.load()
    assert loaded.x == 200
    assert loaded.y == 300
    assert loaded.size == "L"
    assert loaded.mini_mode is True
    assert loaded.dnd is True
    assert loaded.sound is False


# ------------------------------------------------------------------
# 更新方法（update_position / update_size）
# ------------------------------------------------------------------

def test_settings_update_position(tmp_path, monkeypatch):
    """``update_position`` 应更新 x,y 并持久化到文件。"""
    config_path = tmp_path / "desktop_pet.json"
    monkeypatch.setattr(
        DesktopPetSettings, "get_storage_path",
        classmethod(lambda cls: config_path),
    )

    s = DesktopPetSettings()
    s.update_position(400, 500)

    assert s.x == 400 and s.y == 500
    assert config_path.exists(), "update_position 后应持久化"
    data = json.loads(config_path.read_text(encoding="utf-8"))
    assert data["x"] == 400 and data["y"] == 500


def test_settings_update_size_valid(tmp_path, monkeypatch):
    """``update_size('L')`` 合法值应更新成功并持久化。"""
    config_path = tmp_path / "desktop_pet.json"
    monkeypatch.setattr(
        DesktopPetSettings, "get_storage_path",
        classmethod(lambda cls: config_path),
    )

    s = DesktopPetSettings()  # 默认 size = "M"
    assert s.size == "M"
    s.update_size("L")
    assert s.size == "L", "update_size('L') 后 size 应为 'L'"
    assert config_path.exists(), "应已持久化"
    data = json.loads(config_path.read_text(encoding="utf-8"))
    assert data["size"] == "L"


def test_settings_update_size_invalid(tmp_path, monkeypatch):
    """``update_size('XL')`` 非法值应被忽略，size 保持原值。"""
    config_path = tmp_path / "desktop_pet.json"
    monkeypatch.setattr(
        DesktopPetSettings, "get_storage_path",
        classmethod(lambda cls: config_path),
    )

    s = DesktopPetSettings()  # 默认 size = "M"
    original_size = s.size
    s.update_size("XL")  # 非法值
    assert s.size == original_size, "非法 size 不应更新"
    # 文件不应被写入（非法值时 save 不被调用）
    # 注：允许文件存在（如果之前已 save），但当前 size 不变
    # 这里只验证 size 字段不变即可


# ------------------------------------------------------------------
# toggle_* 方法
# ------------------------------------------------------------------

def test_settings_toggle_dnd(tmp_path, monkeypatch):
    """``toggle_dnd`` 应翻转 dnd 并返回新状态。"""
    config_path = tmp_path / "desktop_pet.json"
    monkeypatch.setattr(
        DesktopPetSettings, "get_storage_path",
        classmethod(lambda cls: config_path),
    )

    s = DesktopPetSettings()
    assert s.dnd is False, "初始 dnd 应为 False"

    new_state = s.toggle_dnd()
    assert new_state is True, "第一次 toggle 应返回 True"
    assert s.dnd is True

    new_state = s.toggle_dnd()
    assert new_state is False, "第二次 toggle 应返回 False"
    assert s.dnd is False


def test_settings_toggle_sound(tmp_path, monkeypatch):
    """``toggle_sound`` 应翻转 sound 并返回新状态。"""
    config_path = tmp_path / "desktop_pet.json"
    monkeypatch.setattr(
        DesktopPetSettings, "get_storage_path",
        classmethod(lambda cls: config_path),
    )

    s = DesktopPetSettings()
    assert s.sound is True, "初始 sound 应为 True"

    new_state = s.toggle_sound()
    assert new_state is False
    assert s.sound is False

    new_state = s.toggle_sound()
    assert new_state is True
    assert s.sound is True


def test_settings_toggle_mini_mode(tmp_path, monkeypatch):
    """``toggle_mini_mode`` 应翻转 mini_mode 并返回新状态。"""
    config_path = tmp_path / "desktop_pet.json"
    monkeypatch.setattr(
        DesktopPetSettings, "get_storage_path",
        classmethod(lambda cls: config_path),
    )

    s = DesktopPetSettings()
    assert s.mini_mode is False, "初始 mini_mode 应为 False"

    new_state = s.toggle_mini_mode()
    assert new_state is True
    assert s.mini_mode is True

    new_state = s.toggle_mini_mode()
    assert new_state is False
    assert s.mini_mode is False


# ------------------------------------------------------------------
# DndFilter — should_silence
# ------------------------------------------------------------------

def test_dnd_filter_no_dnd():
    """dnd=False 时 ``should_silence`` 总是返回 False（无论手动/自动）。"""
    settings = DesktopPetSettings(dnd=False)
    f = DndFilter(settings)

    # 自动触发
    assert f.should_silence(PetState.RETRIEVING, is_manual=False) is False
    # 手动触发
    assert f.should_silence(PetState.LISTENING, is_manual=True) is False
    # 任意状态
    for state in PetState:
        assert f.should_silence(state, is_manual=False) is False
        assert f.should_silence(state, is_manual=True) is False


def test_dnd_filter_dnd_auto_state():
    """dnd=True 时自动触发应返回 True（静默）。"""
    settings = DesktopPetSettings(dnd=True)
    f = DndFilter(settings)

    # 自动触发：所有状态都应静默
    assert f.should_silence(PetState.RETRIEVING, is_manual=False) is True
    assert f.should_silence(PetState.THINKING, is_manual=False) is True
    assert f.should_silence(PetState.NOTIFYING, is_manual=False) is True
    assert f.should_silence(PetState.SLEEPING, is_manual=False) is True


def test_dnd_filter_dnd_manual_state():
    """dnd=True 时手动触发应返回 False（不静默）。"""
    settings = DesktopPetSettings(dnd=True)
    f = DndFilter(settings)

    # 手动触发：所有状态都不应静默
    assert f.should_silence(PetState.LISTENING, is_manual=True) is False
    assert f.should_silence(PetState.ANSWERING, is_manual=True) is False
    assert f.should_silence(PetState.INGESTING, is_manual=True) is False


# ------------------------------------------------------------------
# DndFilter — should_play_sound
# ------------------------------------------------------------------

def test_dnd_filter_should_play_sound_disabled():
    """sound=False 时 ``should_play_sound`` 总是返回 False。"""
    settings = DesktopPetSettings(sound=False)
    f = DndFilter(settings)

    assert f.should_play_sound(is_manual=False) is False
    assert f.should_play_sound(is_manual=True) is False

    # 即便 dnd 关闭，sound 关仍静音
    settings2 = DesktopPetSettings(sound=False, dnd=False)
    f2 = DndFilter(settings2)
    assert f2.should_play_sound(is_manual=True) is False


def test_dnd_filter_should_play_sound_dnd_auto():
    """dnd=True + 自动触发：``should_play_sound`` 返回 False（静音）。"""
    settings = DesktopPetSettings(dnd=True, sound=True)
    f = DndFilter(settings)

    assert f.should_play_sound(is_manual=False) is False


def test_dnd_filter_should_play_sound_dnd_manual():
    """dnd=True + 手动触发：``should_play_sound`` 返回 True（允许发声）。"""
    settings = DesktopPetSettings(dnd=True, sound=True)
    f = DndFilter(settings)

    assert f.should_play_sound(is_manual=True) is True

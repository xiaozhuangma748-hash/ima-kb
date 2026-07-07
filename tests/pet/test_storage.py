"""PetStorage 持久化测试。"""
import json
from pathlib import Path
import pytest
from core.pet.pet import Pet
from core.pet.storage import PetStorage


def test_load_returns_none_when_file_missing(tmp_path):
    storage = PetStorage(storage_path=tmp_path)
    assert storage.load() is None


def test_save_and_load_roundtrip(tmp_path):
    storage = PetStorage(storage_path=tmp_path)
    pet = Pet(name="小白", level=5, exp=300, branch="scholar")
    storage.save(pet)

    loaded = storage.load()
    assert loaded is not None
    assert loaded.name == "小白"
    assert loaded.level == 5
    assert loaded.exp == 300
    assert loaded.branch == "scholar"


def test_create_new_pet(tmp_path):
    storage = PetStorage(storage_path=tmp_path)
    pet = storage.create("小白")
    assert pet.name == "小白"
    assert pet.level == 1
    assert pet.exp == 0
    # 已保存到磁盘
    assert (tmp_path / "pet.json").exists()


def test_load_corrupted_json_returns_none_and_backups(tmp_path):
    # 写入损坏的 JSON
    (tmp_path / "pet.json").write_text("{invalid json", encoding="utf-8")
    storage = PetStorage(storage_path=tmp_path)
    loaded = storage.load()
    assert loaded is None
    # 备份文件存在
    backups = list(tmp_path.glob("pet.json.bak.*"))
    assert len(backups) == 1

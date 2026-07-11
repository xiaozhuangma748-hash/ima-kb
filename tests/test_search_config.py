"""搜索配置测试。"""
import json
import pytest
from pathlib import Path
from core.search.config import SearchConfig


def test_load_default_config(tmp_path):
    """文件不存在时返回默认值。"""
    config = SearchConfig(storage_path=tmp_path)
    assert config.get_default_tag() is None
    assert config.get_default_limit() == 10


def test_set_and_get_defaults(tmp_path):
    """设置后能正确读取。"""
    config = SearchConfig(storage_path=tmp_path)
    config.set_defaults(tag="政策", limit=20)

    # 重新加载验证持久化
    config2 = SearchConfig(storage_path=tmp_path)
    assert config2.get_default_tag() == "政策"
    assert config2.get_default_limit() == 20


def test_reset_config(tmp_path):
    """重置为默认值。"""
    config = SearchConfig(storage_path=tmp_path)
    config.set_defaults(tag="殡葬", limit=5)
    assert config.get_default_tag() == "殡葬"
    assert config.get_default_limit() == 5

    config.reset()
    assert config.get_default_tag() is None
    assert config.get_default_limit() == 10

    # 验证持久化
    config2 = SearchConfig(storage_path=tmp_path)
    assert config2.get_default_tag() is None
    assert config2.get_default_limit() == 10

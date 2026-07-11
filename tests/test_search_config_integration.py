"""搜索默认配置集成测试。

测试 _cmd_search 与 SearchConfig 的集成：
- 无参数时显示默认配置
- config 子命令设置/重置配置
- 搜索时自动应用默认配置
"""
from __future__ import annotations

import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch
from io import StringIO


@pytest.fixture
def mock_storage():
    """模拟 storage 对象。"""
    storage = MagicMock()
    storage.bm25_search.return_value = []
    storage.list_documents_by_tag.return_value = []
    return storage


@pytest.fixture
def mock_console():
    """模拟 console 输出。"""
    with patch("core.cli.commands.docs.console") as mock:
        yield mock


@pytest.fixture
def temp_storage_path(tmp_path):
    """临时存储路径。"""
    return tmp_path


class TestSearchConfigIntegration:
    """测试 _cmd_search 与 SearchConfig 集成。"""

    def test_search_no_args_shows_config(self, mock_storage, mock_console, temp_storage_path):
        """测试 /search 无参数时显示默认配置。"""
        from core.cli.commands.docs import DocsMixin
        from core.search.config import SearchConfig

        # 设置默认配置
        cfg = SearchConfig(storage_path=temp_storage_path)
        cfg.set_defaults(tag="政策", limit=20)

        # 创建 DocsMixin 实例
        mixin = DocsMixin()
        mixin.storage = mock_storage

        # Mock SearchConfig 使用临时路径
        with patch("core.search.config.SearchConfig", return_value=cfg):
            mixin._cmd_search("")

        # 验证输出了用法提示和当前配置
        calls = [str(call) for call in mock_console.print.call_args_list]
        assert any("用法" in call for call in calls)
        assert any("政策" in call for call in calls)

    def test_search_config_tag_sets_default(self, mock_storage, mock_console, temp_storage_path):
        """测试 /search config tag 政策 设置默认标签。"""
        from core.cli.commands.docs import DocsMixin
        from core.search.config import SearchConfig

        mixin = DocsMixin()
        mixin.storage = mock_storage

        cfg = SearchConfig(storage_path=temp_storage_path)

        with patch("core.search.config.SearchConfig", return_value=cfg):
            mixin._cmd_search("config tag 政策")

        # 验证配置已保存
        assert cfg.get_default_tag() == "政策"
        # 验证输出了确认信息
        calls = [str(call) for call in mock_console.print.call_args_list]
        assert any("默认标签已设置" in call for call in calls)

    def test_search_config_limit_sets_default(self, mock_storage, mock_console, temp_storage_path):
        """测试 /search config limit 20 设置默认数量。"""
        from core.cli.commands.docs import DocsMixin
        from core.search.config import SearchConfig

        mixin = DocsMixin()
        mixin.storage = mock_storage

        cfg = SearchConfig(storage_path=temp_storage_path)

        with patch("core.search.config.SearchConfig", return_value=cfg):
            mixin._cmd_search("config limit 20")

        # 验证配置已保存
        assert cfg.get_default_limit() == 20
        # 验证输出了确认信息
        calls = [str(call) for call in mock_console.print.call_args_list]
        assert any("默认数量已设置" in call for call in calls)

    def test_search_config_reset(self, mock_storage, mock_console, temp_storage_path):
        """测试 /search config reset 重置配置。"""
        from core.cli.commands.docs import DocsMixin
        from core.search.config import SearchConfig

        mixin = DocsMixin()
        mixin.storage = mock_storage

        cfg = SearchConfig(storage_path=temp_storage_path)
        cfg.set_defaults(tag="政策", limit=20)

        with patch("core.search.config.SearchConfig", return_value=cfg):
            mixin._cmd_search("config reset")

        # 验证配置已重置
        assert cfg.get_default_tag() is None
        assert cfg.get_default_limit() == 10
        # 验证输出了确认信息
        calls = [str(call) for call in mock_console.print.call_args_list]
        assert any("已重置" in call for call in calls)

    def test_search_applies_default_tag(self, mock_storage, mock_console, temp_storage_path):
        """测试搜索时自动应用默认标签。"""
        from core.cli.commands.docs import DocsMixin
        from core.search.config import SearchConfig

        # 设置默认标签
        cfg = SearchConfig(storage_path=temp_storage_path)
        cfg.set_defaults(tag="政策")

        mixin = DocsMixin()
        mixin.storage = mock_storage

        # 模拟搜索结果
        mock_result = MagicMock()
        mock_result.doc_id = "doc1"
        mock_result.score = 0.8
        mock_result.doc_title = "测试文档"
        mock_result.content = "测试内容" * 50
        mock_storage.bm25_search.return_value = [mock_result]
        mock_storage.list_documents_by_tag.return_value = [MagicMock(id="doc1")]

        with patch("core.search.config.SearchConfig", return_value=cfg):
            mixin._cmd_search("骨灰")

        # 验证使用了默认标签进行筛选
        mock_storage.list_documents_by_tag.assert_called_with("政策")
        # 验证输出了使用默认标签的提示
        calls = [str(call) for call in mock_console.print.call_args_list]
        assert any("使用默认标签" in call for call in calls)

    def test_search_explicit_tag_overrides_default(self, mock_storage, mock_console, temp_storage_path):
        """测试用户指定的 --tag 覆盖默认标签。"""
        from core.cli.commands.docs import DocsMixin
        from core.search.config import SearchConfig

        # 设置默认标签
        cfg = SearchConfig(storage_path=temp_storage_path)
        cfg.set_defaults(tag="政策")

        mixin = DocsMixin()
        mixin.storage = mock_storage

        # 模拟搜索结果
        mock_result = MagicMock()
        mock_result.doc_id = "doc1"
        mock_result.score = 0.8
        mock_result.doc_title = "测试文档"
        mock_result.content = "测试内容" * 50
        mock_storage.bm25_search.return_value = [mock_result]
        mock_storage.list_documents_by_tag.return_value = [MagicMock(id="doc1")]

        with patch("core.search.config.SearchConfig", return_value=cfg):
            mixin._cmd_search("骨灰 --tag 流程")

        # 验证使用了用户指定的标签
        mock_storage.list_documents_by_tag.assert_called_with("流程")
        # 验证输出了用户指定的标签筛选提示
        calls = [str(call) for call in mock_console.print.call_args_list]
        assert any("标签筛选: 流程" in call for call in calls)

    def test_search_applies_default_limit(self, mock_storage, mock_console, temp_storage_path):
        """测试搜索时自动应用默认数量。"""
        from core.cli.commands.docs import DocsMixin
        from core.search.config import SearchConfig

        # 设置默认数量
        cfg = SearchConfig(storage_path=temp_storage_path)
        cfg.set_defaults(limit=5)

        mixin = DocsMixin()
        mixin.storage = mock_storage

        # 模拟多个搜索结果
        mock_results = []
        for i in range(10):
            mock_result = MagicMock()
            mock_result.doc_id = f"doc{i}"
            mock_result.score = 0.8 - i * 0.05
            mock_result.doc_title = f"测试文档{i}"
            mock_result.content = f"测试内容{i}" * 50
            mock_results.append(mock_result)
        mock_storage.bm25_search.return_value = mock_results

        with patch("core.search.config.SearchConfig", return_value=cfg):
            mixin._cmd_search("骨灰")

        # 验证 bm25_search 使用了默认数量 * 3 作为 fetch_k
        mock_storage.bm25_search.assert_called_with("骨灰", top_k=15)

    def test_search_config_show(self, mock_storage, mock_console, temp_storage_path):
        """测试 /search config 显示当前配置。"""
        from core.cli.commands.docs import DocsMixin
        from core.search.config import SearchConfig

        cfg = SearchConfig(storage_path=temp_storage_path)
        cfg.set_defaults(tag="政策", limit=20)

        mixin = DocsMixin()
        mixin.storage = mock_storage

        with patch("core.search.config.SearchConfig", return_value=cfg):
            mixin._cmd_search("config")

        # 验证输出了配置信息
        calls = [str(call) for call in mock_console.print.call_args_list]
        assert any("搜索默认配置" in call for call in calls)
        assert any("政策" in call for call in calls)
        assert any("20" in call for call in calls)

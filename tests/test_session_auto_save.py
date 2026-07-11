"""会话自动持久化测试。"""
import json
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock


def _make_repl():
    """创建一个最小化的 REPL 实例（跳过 __init__ 中的重组件初始化）。"""
    from core.cli.repl import REPL
    obj = REPL.__new__(REPL)
    obj.history = []
    obj.active_session_name = None
    obj.pet = None
    obj.pet_storage = MagicMock()
    obj.llm_available = False
    obj.running = True
    obj.conversation_summary = None
    obj.administrator = None
    obj.memory_store = None
    obj.workflow_tracker = None
    obj._admin_init_failed = False
    obj._vector_available = None
    obj.current_analysis = None
    obj.reader = None
    obj._web_server = None
    obj._web_thread = None
    obj.storage = MagicMock()
    obj.rag = None
    return obj


class TestAutoSaveSession:
    """_auto_save_session 方法测试。"""

    def test_no_active_session_no_error(self, tmp_path):
        """无活跃会话时不报错，不保存任何内容。"""
        repl = _make_repl()
        repl.active_session_name = None
        repl.history = [{"role": "user", "content": "hello"}]

        # 不应抛出异常
        repl._auto_save_session()

    def test_empty_history_no_save(self, tmp_path):
        """history 为空时不保存。"""
        repl = _make_repl()
        repl.active_session_name = "test_session"
        repl.history = []

        with patch("core.session.store.SessionStore") as mock_cls:
            mock_ss = MagicMock()
            mock_cls.return_value = mock_ss
            repl._auto_save_session()
            # save 不应被调用
            mock_ss.save.assert_not_called()

    def test_active_session_with_history_saves(self, tmp_path):
        """有活跃会话且有 history 时正确保存。"""
        repl = _make_repl()
        repl.active_session_name = "my_session"
        repl.history = [
            {"role": "user", "content": "你好"},
            {"role": "assistant", "content": "你好！"},
        ]

        with patch("core.session.store.SessionStore") as mock_cls:
            mock_ss = MagicMock()
            mock_cls.return_value = mock_ss
            repl._auto_save_session()
            mock_ss.save.assert_called_once_with(
                "my_session",
                [
                    {"role": "user", "content": "你好"},
                    {"role": "assistant", "content": "你好！"},
                ],
            )

    def test_save_exception_does_not_propagate(self):
        """保存异常时不向外抛出。"""
        repl = _make_repl()
        repl.active_session_name = "test_session"
        repl.history = [{"role": "user", "content": "hello"}]

        with patch("core.session.store.SessionStore") as mock_cls:
            mock_cls.side_effect = RuntimeError("disk full")
            # 不应抛出异常
            repl._auto_save_session()

    def test_integration_with_session_store(self, tmp_path):
        """集成测试：使用真实 SessionStore 验证保存结果。"""
        from core.session.store import SessionStore

        repl = _make_repl()
        repl.active_session_name = "integration_test"
        repl.history = [
            {"role": "user", "content": "问题1"},
            {"role": "assistant", "content": "回答1"},
        ]

        # 使用 tmp_path 作为存储目录
        with patch("core.session.store.SessionStore") as mock_cls:
            real_ss = SessionStore(storage_dir=tmp_path)
            mock_cls.return_value = real_ss
            repl._auto_save_session()

        # 验证文件已写入
        loaded = SessionStore(storage_dir=tmp_path).load("integration_test")
        assert loaded is not None
        assert len(loaded) == 2
        assert loaded[0]["role"] == "user"
        assert loaded[0]["content"] == "问题1"
        assert loaded[1]["role"] == "assistant"
        assert loaded[1]["content"] == "回答1"

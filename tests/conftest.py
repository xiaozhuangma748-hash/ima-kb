"""pytest 全局配置。

MemoryStore 单例化改造后，每个测试运行前需 reset 单例，
避免上一个测试的内存状态泄漏到下一个测试。
"""
import pytest


@pytest.fixture(autouse=True)
def _reset_memory_store_singleton():
    """每个测试前 reset MemoryStore 单例，保证测试隔离。"""
    try:
        from core.memory.store import reset_default_memory_store
        reset_default_memory_store()
    except ImportError:
        pass
    yield
    # 测试结束后也 reset，避免影响后续测试
    try:
        from core.memory.store import reset_default_memory_store
        reset_default_memory_store()
    except ImportError:
        pass

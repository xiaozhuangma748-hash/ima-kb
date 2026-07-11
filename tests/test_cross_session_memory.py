"""跨会话记忆测试。"""
import json
import pytest
from pathlib import Path
from core.memory.cross_session import CrossSessionMemory


def test_load_default_memory(tmp_path):
    """文件不存在时返回空上下文。"""
    memory = CrossSessionMemory(storage_path=tmp_path)
    context = memory.get_context()
    # 空上下文应包含四个标题但无内容项
    assert "【用户偏好】" in context
    assert "【关注主题】" in context
    assert "【未解决问题】" in context
    assert "【关键事实】" in context
    # 不应有任何列表项
    assert "- " not in context


def test_add_and_get_context(tmp_path):
    """添加记忆后 get_context() 包含内容。"""
    memory = CrossSessionMemory(storage_path=tmp_path)
    memory.save_preference("format", "table")
    memory.add_topic("殡葬政策")
    memory.add_unresolved_question("什么是知识库？")
    memory.add_key_fact("用户关注殡葬领域")

    context = memory.get_context()
    assert "- format: table" in context
    assert "- 殡葬政策" in context
    assert "- 什么是知识库？" in context
    assert "- 用户关注殡葬领域" in context


def test_clear_all(tmp_path):
    """清空后上下文为空（无列表项）。"""
    memory = CrossSessionMemory(storage_path=tmp_path)
    memory.add_topic("殡葬政策")
    memory.add_key_fact("用户关注殡葬领域")
    memory.clear_all()

    context = memory.get_context()
    assert "- " not in context
    assert "【用户偏好】" in context
    assert "【关注主题】" in context


def test_duplicate_topic(tmp_path):
    """重复添加同一主题不重复。"""
    memory = CrossSessionMemory(storage_path=tmp_path)
    memory.add_topic("殡葬政策")
    memory.add_topic("殡葬政策")
    memory.add_topic("殡葬政策")

    context = memory.get_context()
    # 只应出现一次
    assert context.count("- 殡葬政策") == 1


def test_remove_topic(tmp_path):
    """移除主题后上下文不再包含。"""
    memory = CrossSessionMemory(storage_path=tmp_path)
    memory.add_topic("殡葬政策")
    memory.add_topic("骨灰安置")
    memory.remove_topic("殡葬政策")

    context = memory.get_context()
    assert "- 殡葬政策" not in context
    assert "- 骨灰安置" in context


def test_empty_input_validation(tmp_path):
    """空字符串和空白输入应被忽略。"""
    memory = CrossSessionMemory(storage_path=tmp_path)
    
    # 空字符串不应被添加
    memory.add_topic("")
    memory.add_topic("   ")
    memory.add_unresolved_question("")
    memory.add_key_fact("")
    memory.save_preference("", "value")
    memory.save_preference("   ", "value")
    
    context = memory.get_context()
    assert "- " not in context  # 不应有任何列表项


def test_corrupted_json_wrong_type(tmp_path):
    """JSON 合法但数据类型错误时应返回默认值。"""
    # 写入一个顶层为列表的 JSON
    (tmp_path / "cross_session.json").write_text("[]", encoding="utf-8")
    memory = CrossSessionMemory(storage_path=tmp_path)
    context = memory.get_context()
    # 应返回默认空结构
    assert "【用户偏好】" in context
    assert "- " not in context


def test_corrupted_json_wrong_field_type(tmp_path):
    """字段类型错误时应修正为正确类型。"""
    # preferences 应该是 dict，topics 应该是 list
    wrong_data = {
        "preferences": "not a dict",
        "topics": "not a list",
        "unresolved_questions": {},
        "key_facts": 123,
    }
    (tmp_path / "cross_session.json").write_text(
        json.dumps(wrong_data), encoding="utf-8"
    )
    memory = CrossSessionMemory(storage_path=tmp_path)
    
    # 应能正常添加数据
    memory.add_topic("测试主题")
    memory.save_preference("key", "value")
    
    context = memory.get_context()
    assert "- 测试主题" in context
    assert "- key: value" in context


def test_whitespace_stripping(tmp_path):
    """输入应自动去除首尾空白。"""
    memory = CrossSessionMemory(storage_path=tmp_path)
    memory.add_topic("  殡葬政策  ")
    memory.add_topic("殡葬政策")  # 去空白后应重复
    
    context = memory.get_context()
    # 只应出现一次，且无多余空白
    assert context.count("- 殡葬政策") == 1
    assert "  殡葬政策  " not in context


def test_persistence_across_instances(tmp_path):
    """多个实例应共享同一份持久化数据。"""
    memory1 = CrossSessionMemory(storage_path=tmp_path)
    memory1.add_topic("殡葬政策")
    memory1.save_preference("format", "table")
    
    # 创建新实例
    memory2 = CrossSessionMemory(storage_path=tmp_path)
    context = memory2.get_context()
    
    assert "- 殡葬政策" in context
    assert "- format: table" in context

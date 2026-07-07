"""人格 prompt 模板测试。"""
import pytest
from core.persona.prompts import build_system_prompt, SCHOLAR_SYSTEM, WARRIOR_SYSTEM, ARTISAN_SYSTEM, NEUTRAL_SYSTEM
from core.persona.styles import STYLE_DESCRIPTIONS
from core.pet.pet import Pet


def test_style_descriptions_has_three():
    """三种人格风格描述都存在。"""
    assert "scholar" in STYLE_DESCRIPTIONS
    assert "warrior" in STYLE_DESCRIPTIONS
    assert "artisan" in STYLE_DESCRIPTIONS


def test_build_scholar_prompt():
    """构建 scholar 风格 prompt。"""
    pet = Pet(name="小白", level=5, branch="scholar")
    profile = {"preferred_format": "table", "focus_topics": ["骨灰安置"]}
    tasks = [{"description": "整理政策", "status": "in_progress"}]
    sources = [{"doc_id": "d1", "title": "条例", "paragraph_num": 1, "content": "内容"}]

    prompt = build_system_prompt("scholar", pet, profile, tasks, sources)

    assert "小白" in prompt
    assert "Lv5" in prompt or "Lv 5" in prompt or "level 5" in prompt.lower()
    assert "骨灰安置" in prompt
    assert "整理政策" in prompt
    assert "条例" in prompt


def test_build_warrior_prompt():
    """构建 warrior 风格 prompt。"""
    pet = Pet(name="小狼", level=6, branch="warrior")
    prompt = build_system_prompt("warrior", pet, {}, [], [])
    assert "小狼" in prompt
    assert "warrior" in prompt.lower() or "战士" in prompt


def test_build_artisan_prompt():
    """构建 artisan 风格 prompt。"""
    pet = Pet(name="小匠", level=7, branch="artisan")
    prompt = build_system_prompt("artisan", pet, {}, [], [])
    assert "小匠" in prompt


def test_build_neutral_prompt_for_unbranched():
    """未分系时用中性风格。"""
    pet = Pet(name="小白", level=3, branch=None)
    prompt = build_system_prompt("neutral", pet, {}, [], [])
    assert "小白" in prompt
    # 中性 prompt 较短
    assert len(prompt) < len(SCHOLAR_SYSTEM)


def test_build_prompt_with_empty_sources():
    """无检索结果时 prompt 仍能构建。"""
    pet = Pet(name="小白", level=1)
    prompt = build_system_prompt("scholar", pet, {}, [], [])
    assert "小白" in prompt


def test_build_prompt_includes_pet_state_warnings():
    """宠物状态低时 prompt 包含警告。"""
    pet = Pet(name="小白", level=5, mood=20, hunger=20)
    prompt = build_system_prompt("scholar", pet, {}, [], [])
    # mood < 30 应有提示
    assert "心情" in prompt or "mood" in prompt.lower()

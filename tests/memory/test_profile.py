"""用户偏好测试。"""
import pytest
from core.memory.profile import (
    Profile, ProfileManager, _extract_topic,
    VALID_FORMATS, VALID_STYLES,
)
from core.memory.store import MemoryStore


def test_default_profile(tmp_path):
    """默认 profile 为空值。"""
    store = MemoryStore(storage_path=tmp_path)
    mgr = ProfileManager(store)
    p = mgr.get_profile()
    assert p.preferred_format == ""
    assert p.preferred_style == "auto"
    assert p.focus_topics == []
    assert p.focus_regions == []
    assert p.interaction_count == 0


def test_update_format_preference(tmp_path):
    """更新格式偏好。"""
    store = MemoryStore(storage_path=tmp_path)
    mgr = ProfileManager(store)
    mgr.update_format_preference("table")
    assert mgr.get_profile().preferred_format == "table"


def test_update_format_preference_invalid(tmp_path):
    """无效格式应抛出 ValueError。"""
    store = MemoryStore(storage_path=tmp_path)
    mgr = ProfileManager(store)
    with pytest.raises(ValueError):
        mgr.update_format_preference("invalid_format")
    with pytest.raises(ValueError):
        mgr.update_format_preference("TABLE")  # 大小写敏感


def test_update_format_preference_empty(tmp_path):
    """空字符串应该合法（表示清除）。"""
    store = MemoryStore(storage_path=tmp_path)
    mgr = ProfileManager(store)
    mgr.update_format_preference("table")
    mgr.update_format_preference("")  # 清除
    assert mgr.get_profile().preferred_format == ""


def test_update_style_preference(tmp_path):
    """更新风格偏好。"""
    store = MemoryStore(storage_path=tmp_path)
    mgr = ProfileManager(store)
    mgr.update_style_preference("scholar")
    assert mgr.get_profile().preferred_style == "scholar"


def test_update_style_preference_invalid(tmp_path):
    """无效风格应抛出 ValueError。"""
    store = MemoryStore(storage_path=tmp_path)
    mgr = ProfileManager(store)
    with pytest.raises(ValueError):
        mgr.update_style_preference("invalid_style")


def test_update_from_query_adds_topic(tmp_path):
    """从查询中提取主题。"""
    store = MemoryStore(storage_path=tmp_path)
    mgr = ProfileManager(store)
    mgr.update_from_query("骨灰安置政策", "回答")
    p = mgr.get_profile()
    assert "骨灰安置" in p.focus_topics


def test_update_from_query_adds_region(tmp_path):
    """从查询中提取地区。"""
    store = MemoryStore(storage_path=tmp_path)
    mgr = ProfileManager(store)
    mgr.update_from_query("杭州市骨灰安置", "回答")
    p = mgr.get_profile()
    assert "杭州市" in p.focus_regions


def test_update_from_query_increments_count(tmp_path):
    """每次更新增加 interaction_count。"""
    store = MemoryStore(storage_path=tmp_path)
    mgr = ProfileManager(store)
    mgr.update_from_query("查询1", "回答1")
    mgr.update_from_query("查询2", "回答2")
    assert mgr.get_profile().interaction_count == 2


def test_focus_topics_dedup(tmp_path):
    """重复主题不重复添加。"""
    store = MemoryStore(storage_path=tmp_path)
    mgr = ProfileManager(store)
    mgr.update_from_query("骨灰安置", "回答")
    mgr.update_from_query("骨灰安置政策", "回答")
    p = mgr.get_profile()
    # "骨灰安置" 只出现一次
    assert p.focus_topics.count("骨灰安置") == 1


def test_persistence_across_instances(tmp_path):
    """偏好跨实例持久化。"""
    store = MemoryStore(storage_path=tmp_path)
    mgr1 = ProfileManager(store)
    mgr1.update_format_preference("table")
    store.save()

    store2 = MemoryStore(storage_path=tmp_path)
    mgr2 = ProfileManager(store2)
    assert mgr2.get_profile().preferred_format == "table"


# ============================================================
# 新增：停用词过滤测试
# ============================================================

def test_extract_topic_filters_stopwords_help():
    """'帮我' 应被过滤，不作为主题。"""
    assert _extract_topic("帮我查一下骨灰安置") == "骨灰安置"


def test_extract_topic_filters_stopwords_you():
    """'你是' 应被过滤。"""
    # '你是谁' 全是停用词，应返回空
    assert _extract_topic("你是谁") == ""


def test_extract_topic_filters_stopwords_please():
    """'请问' 应被过滤。"""
    assert _extract_topic("请问骨灰安置政策") == "骨灰安置"


def test_extract_topic_normal_query():
    """正常查询应保留有意义词。"""
    assert _extract_topic("骨灰安置政策") == "骨灰安置"


def test_extract_topic_empty():
    """空查询返回空。"""
    assert _extract_topic("") == ""
    assert _extract_topic("   ") == ""


def test_extract_topic_all_stopwords():
    """全是停用词返回空。"""
    assert _extract_topic("你的我的") == ""
    assert _extract_topic("什么怎么样") == ""


def test_update_from_query_no_garbage_topics(tmp_path):
    """对话开场白不应被记录为主题。"""
    store = MemoryStore(storage_path=tmp_path)
    mgr = ProfileManager(store)
    # 这些都是常见的对话开场白
    mgr.update_from_query("帮我看看骨灰安置", "回答")
    mgr.update_from_query("你是谁", "回答")
    mgr.update_from_query("请问骨灰安置政策", "回答")
    p = mgr.get_profile()
    # 不应包含 "帮我"、"你是"、"请问" 等垃圾词
    assert "帮我" not in p.focus_topics
    assert "你是" not in p.focus_topics
    assert "请问" not in p.focus_topics
    # 但应包含真实主题
    assert "骨灰安置" in p.focus_topics


# ============================================================
# 新增：手动主题管理测试
# ============================================================

def test_add_topic(tmp_path):
    """手动添加主题。"""
    store = MemoryStore(storage_path=tmp_path)
    mgr = ProfileManager(store)
    assert mgr.add_topic("骨灰安置") is True
    assert "骨灰安置" in mgr.get_profile().focus_topics


def test_add_topic_dedup(tmp_path):
    """添加重复主题返回 False。"""
    store = MemoryStore(storage_path=tmp_path)
    mgr = ProfileManager(store)
    mgr.add_topic("骨灰安置")
    # 重复添加（包含关系）
    assert mgr.add_topic("骨灰安置") is False
    assert mgr.add_topic("骨灰") is False  # 被包含
    assert mgr.add_topic("骨灰安置政策") is False  # 包含


def test_add_topic_empty_raises(tmp_path):
    """空主题应抛出 ValueError。"""
    store = MemoryStore(storage_path=tmp_path)
    mgr = ProfileManager(store)
    with pytest.raises(ValueError):
        mgr.add_topic("")
    with pytest.raises(ValueError):
        mgr.add_topic("   ")


def test_remove_topic(tmp_path):
    """删除主题。"""
    store = MemoryStore(storage_path=tmp_path)
    mgr = ProfileManager(store)
    mgr.add_topic("骨灰安置")
    assert mgr.remove_topic("骨灰安置") is True
    assert "骨灰安置" not in mgr.get_profile().focus_topics


def test_remove_topic_not_found(tmp_path):
    """删除不存在的主题返回 False。"""
    store = MemoryStore(storage_path=tmp_path)
    mgr = ProfileManager(store)
    assert mgr.remove_topic("不存在") is False


def test_clear_topics(tmp_path):
    """清空所有主题。"""
    store = MemoryStore(storage_path=tmp_path)
    mgr = ProfileManager(store)
    mgr.add_topic("骨灰安置")
    mgr.add_topic("墓地政策")
    count = mgr.clear_topics()
    assert count == 2
    assert mgr.get_profile().focus_topics == []


def test_clear_topics_empty(tmp_path):
    """空主题列表清空返回 0。"""
    store = MemoryStore(storage_path=tmp_path)
    mgr = ProfileManager(store)
    assert mgr.clear_topics() == 0


def test_valid_formats_constant():
    """VALID_FORMATS 包含所有合法值。"""
    assert "table" in VALID_FORMATS
    assert "list" in VALID_FORMATS
    assert "prose" in VALID_FORMATS
    assert "auto" in VALID_FORMATS
    assert "" in VALID_FORMATS  # 空字符串合法（清除）


def test_valid_styles_constant():
    """VALID_STYLES 包含所有合法值。"""
    assert "auto" in VALID_STYLES
    assert "scholar" in VALID_STYLES
    assert "warrior" in VALID_STYLES
    assert "artisan" in VALID_STYLES


# ============================================================
# Group 1: 地区管理测试（与主题对称）
# ============================================================

def test_add_region(tmp_path):
    """手动添加地区。"""
    store = MemoryStore(storage_path=tmp_path)
    mgr = ProfileManager(store)
    assert mgr.add_region("杭州市") is True
    assert "杭州市" in mgr.get_profile().focus_regions


def test_add_region_dedup(tmp_path):
    """重复地区返回 False。"""
    store = MemoryStore(storage_path=tmp_path)
    mgr = ProfileManager(store)
    mgr.add_region("杭州市")
    assert mgr.add_region("杭州市") is False


def test_add_region_empty_raises(tmp_path):
    """空地区应抛出 ValueError。"""
    store = MemoryStore(storage_path=tmp_path)
    mgr = ProfileManager(store)
    with pytest.raises(ValueError):
        mgr.add_region("")
    with pytest.raises(ValueError):
        mgr.add_region("   ")


def test_remove_region(tmp_path):
    """删除地区。"""
    store = MemoryStore(storage_path=tmp_path)
    mgr = ProfileManager(store)
    mgr.add_region("杭州市")
    assert mgr.remove_region("杭州市") is True
    assert "杭州市" not in mgr.get_profile().focus_regions


def test_remove_region_not_found(tmp_path):
    """删除不存在的地区返回 False。"""
    store = MemoryStore(storage_path=tmp_path)
    mgr = ProfileManager(store)
    assert mgr.remove_region("不存在") is False


def test_clear_regions(tmp_path):
    """清空所有地区。"""
    store = MemoryStore(storage_path=tmp_path)
    mgr = ProfileManager(store)
    mgr.add_region("杭州市")
    mgr.add_region("拱墅区")
    count = mgr.clear_regions()
    assert count == 2
    assert mgr.get_profile().focus_regions == []


def test_clear_regions_empty(tmp_path):
    """空地区列表清空返回 0。"""
    store = MemoryStore(storage_path=tmp_path)
    mgr = ProfileManager(store)
    assert mgr.clear_regions() == 0


def test_add_region_upper_limit(tmp_path):
    """地区超过 10 个时自动淘汰最旧的。"""
    store = MemoryStore(storage_path=tmp_path)
    mgr = ProfileManager(store)
    for i in range(12):
        mgr.add_region(f"地区{i}")
    regions = mgr.get_profile().focus_regions
    assert len(regions) == 10
    # 最旧的 "地区0" / "地区1" 应被淘汰
    assert "地区0" not in regions
    assert "地区1" not in regions
    assert "地区11" in regions

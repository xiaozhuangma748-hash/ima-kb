"""ASCII 艺术加载器测试。"""
from core.pet.art import ArtLibrary


def test_get_none_branch_lv1():
    lib = ArtLibrary()
    art = lib.get(None, 1)
    assert isinstance(art, str)
    assert len(art) > 0


def test_get_scholar_lv6():
    lib = ArtLibrary()
    art = lib.get("scholar", 6)
    assert isinstance(art, str)
    assert len(art) > 0


def test_get_missing_file_returns_fallback():
    lib = ArtLibrary()
    # Lv99 不存在，应该返回占位符
    art = lib.get("scholar", 99)
    assert "Lv99" in art or "?" in art


def test_get_small_variant():
    lib = ArtLibrary()
    art = lib.get("scholar", 6, small=True)
    assert isinstance(art, str)
    # 小尺寸应该比大尺寸短，且行数 ≤ 6
    full_art = lib.get("scholar", 6, small=False)
    assert len(art) < len(full_art)  # 严格小于
    assert art.count("\n") <= 6      # 小尺寸最多 6 行

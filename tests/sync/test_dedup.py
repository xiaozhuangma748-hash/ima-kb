"""SimHash 近似去重测试。"""
import pytest
from core.sync.dedup import SimHash, DedupResult, DedupScanner


def test_simhash_similar_texts_close():
    """相似文本的 SimHash 汉明距离小。"""
    h1 = SimHash.compute("骨灰安置是指将骨灰安放在骨灰堂的过程")
    h2 = SimHash.compute("骨灰安置是指将骨灰安放在骨灰堂中的过程")
    distance = SimHash.hamming_distance(h1, h2)
    assert distance <= 5  # 相似文本距离小


def test_simhash_different_texts_far():
    """完全不同文本的 SimHash 汉明距离大。"""
    h1 = SimHash.compute("骨灰安置政策条例")
    h2 = SimHash.compute(" JavaScript编程入门教程")
    distance = SimHash.hamming_distance(h1, h2)
    assert distance > 10  # 不同文本距离大


def test_simhash_empty_text():
    """空文本返回 0。"""
    h = SimHash.compute("")
    assert h == 0


def test_dedup_result_dataclass():
    """DedupResult 包含必要字段。"""
    r = DedupResult(
        chunk_id="c1",
        doc_id="d1",
        duplicate_of="c2",
        similarity=0.92,
        hamming_distance=2,
    )
    assert r.duplicate_of == "c2"
    assert r.similarity == 0.92
    assert r.is_duplicate  # similarity > 0.85


def test_dedup_scan_finds_duplicates():
    """扫描能发现近似重复。"""
    scanner = DedupScanner(threshold=0.85)

    # 添加原始 chunk
    scanner.add_chunk("c1", "d1", "骨灰安置是指将骨灰安放在骨灰堂、骨灰墙等设施中的过程")

    # 添加近似重复（只改了几个字）
    scanner.add_chunk("c2", "d2", "骨灰安置是指将骨灰安放在骨灰堂、骨灰墙等设施中的流程")

    # 添加完全不同的
    scanner.add_chunk("c3", "d3", " JavaScript是一种动态编程语言")

    results = scanner.scan()
    duplicates = [r for r in results if r.is_duplicate]
    assert len(duplicates) >= 1
    # c2 应该是 c1 的近似重复
    dup = next(r for r in duplicates if r.chunk_id == "c2")
    assert dup.duplicate_of == "c1"


def test_dedup_scan_no_false_positive():
    """不相似的不应被判定为重复。"""
    scanner = DedupScanner(threshold=0.85)
    scanner.add_chunk("c1", "d1", "骨灰安置政策条例全文内容")
    scanner.add_chunk("c2", "d2", "数据结构算法导论笔记")

    results = scanner.scan()
    duplicates = [r for r in results if r.is_duplicate]
    assert len(duplicates) == 0

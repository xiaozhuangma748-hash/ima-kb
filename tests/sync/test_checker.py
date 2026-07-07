"""数据质量检查测试。"""
import pytest
from core.sync.checker import QualityChecker, QualityReport, ChunkQuality


def test_chunk_quality_dataclass():
    """ChunkQuality 包含必要字段。"""
    q = ChunkQuality(
        chunk_id="c1",
        doc_id="d1",
        score=0.85,
        issues=["too_short"],
        is_low_quality=False,
    )
    assert q.score == 0.85
    assert "too_short" in q.issues
    assert q.is_low_quality is False


def test_check_normal_chunk():
    """正常文本质量分高。"""
    checker = QualityChecker()
    result = checker.check_chunk("c1", "d1", "骨灰安置是指将骨灰安放在骨灰堂、骨灰墙、骨灰塔等设施中的过程。")
    assert result.score > 0.7
    assert not result.is_low_quality
    assert len(result.issues) == 0


def test_check_short_chunk():
    """过短文本标记 low_quality。"""
    checker = QualityChecker()
    result = checker.check_chunk("c1", "d1", "详见附件")
    assert result.is_low_quality
    assert "too_short" in result.issues


def test_check_ocr_garbage():
    """OCR 乱码标记 low_quality。"""
    checker = QualityChecker()
    garbled = "□□□□◇◇◇◇△△△△☆☆☆☆□□□□◇◇◇◇" * 3
    result = checker.check_chunk("c1", "d1", garbled)
    assert result.is_low_quality
    assert "ocr_garbage" in result.issues


def test_check_pure_numbers():
    """纯数字/符号标记 low_quality。"""
    checker = QualityChecker()
    result = checker.check_chunk("c1", "d1", "12345678901234567890")
    assert result.is_low_quality
    assert "no_text_content" in result.issues


def test_quality_report_summary():
    """质量报告汇总。"""
    report = QualityReport(
        total_chunks=100,
        normal=92,
        low_quality=6,
        ocr_poor=2,
        issues_detail={"too_short": 4, "ocr_garbage": 2},
    )
    assert report.normal_pct == 92.0
    assert report.health_score > 90

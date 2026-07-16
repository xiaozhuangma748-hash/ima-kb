"""P5: 引用验证增强测试。"""
import pytest

from core.qa.citation_validator import (
    extract_citation_indices,
    filter_valid_citations,
    find_invalid_citations,
    has_substantive_content,
    missing_citation_warning,
    validate_answer,
)


# ============================================================
# extract_citation_indices
# ============================================================

class TestExtractCitations:
    def test_single_citation(self):
        assert extract_citation_indices("答案 [1] 内容") == [1]

    def test_multiple_citations(self):
        assert extract_citation_indices("[1] [3] [2]") == [1, 3, 2]

    def test_dedup_preserves_order(self):
        assert extract_citation_indices("[2] [1] [2] [1]") == [2, 1]

    def test_no_citation(self):
        assert extract_citation_indices("没有任何引用") == []

    def test_empty_content(self):
        assert extract_citation_indices("") == []

    def test_three_digit_number(self):
        """支持 3 位数字引用（最多 999）。"""
        assert extract_citation_indices("[100] [999]") == [100, 999]

    def test_bracket_without_number_not_matched(self):
        """[文字] 不应被匹配。"""
        assert extract_citation_indices("[文字] [1]") == [1]


# ============================================================
# filter_valid_citations
# ============================================================

class TestFilterValidCitations:
    def test_all_valid(self):
        assert filter_valid_citations("[1] [2] [3]", 3) == [1, 2, 3]

    def test_filter_out_of_range(self):
        """[9] 当只有 3 个来源时被过滤。"""
        assert filter_valid_citations("[1] [9] [3]", 3) == [1, 3]

    def test_filter_zero_and_negative(self):
        """[0] 不是合法引用（1-based）。"""
        # 注意：正则 \d{1,3} 不匹配 [0]（实际上是会匹配 0 的）
        # 0 应被过滤因为 < 1
        result = filter_valid_citations("[0] [1]", 3)
        assert 0 not in result
        assert 1 in result

    def test_zero_sources(self):
        assert filter_valid_citations("[1] [2]", 0) == []

    def test_dedup(self):
        assert filter_valid_citations("[1] [1] [2]", 3) == [1, 2]


# ============================================================
# find_invalid_citations
# ============================================================

class TestFindInvalidCitations:
    def test_all_valid_no_invalid(self):
        assert find_invalid_citations("[1] [2]", 5) == []

    def test_find_out_of_range(self):
        assert find_invalid_citations("[1] [9]", 5) == [9]

    def test_zero_is_invalid(self):
        """[0] 应视为越界（1-based）。"""
        result = find_invalid_citations("[0]", 5)
        assert 0 in result

    def test_all_invalid_when_zero_sources(self):
        assert find_invalid_citations("[1] [2]", 0) == [1, 2]


# ============================================================
# has_substantive_content
# ============================================================

class TestHasSubstantiveContent:
    def test_normal_content(self):
        assert has_substantive_content("生态安葬是一种环保的安葬方式，采用可降解材料制成") is True

    def test_empty_string(self):
        assert has_substantive_content("") is False

    def test_only_punctuation(self):
        assert has_substantive_content("，。！？") is False

    def test_only_whitespace(self):
        assert has_substantive_content("   \n  \t  ") is False

    def test_only_citations(self):
        assert has_substantive_content("[1] [2] [3]") is False

    def test_short_content_below_min(self):
        assert has_substantive_content("短") is False

    def test_citation_with_content(self):
        assert has_substantive_content("生态安葬是一种环保的安葬方式 [1]，它采用可降解材料制成 [2]") is True


# ============================================================
# missing_citation_warning
# ============================================================

class TestMissingCitationWarning:
    def test_no_warning_when_cited(self):
        assert missing_citation_warning("生态安葬 [1] 是环保方式，它采用可降解材料", 3) is None

    def test_warning_when_no_citation(self):
        warning = missing_citation_warning("生态安葬是一种环保的安葬方式，采用可降解材料制成", 3)
        assert warning is not None
        assert "引用" in warning or "来源" in warning

    def test_no_warning_when_no_sources(self):
        assert missing_citation_warning("有内容但无来源，这是一段足够长的文本", 0) is None

    def test_no_warning_when_no_content(self):
        assert missing_citation_warning("", 3) is None
        assert missing_citation_warning("[1] [2]", 3) is None


# ============================================================
# validate_answer
# ============================================================

class TestValidateAnswer:
    def test_all_valid(self):
        valid, invalid, warning = validate_answer("[1] [2] 生态安葬是一种环保方式", 3)
        assert valid == [1, 2]
        assert invalid == []
        assert warning is None

    def test_mixed_valid_invalid(self):
        valid, invalid, warning = validate_answer("[1] [9] 生态安葬是一种环保方式", 3)
        assert valid == [1]
        assert invalid == [9]
        assert warning is None  # 有合法引用，不警告

    def test_all_invalid(self):
        valid, invalid, warning = validate_answer("[8] [9] 生态安葬是一种环保的安葬方式，采用可降解材料", 3)
        assert valid == []
        assert invalid == [8, 9]
        # 没有合法引用但有内容 → 警告
        assert warning is not None

    def test_no_content_no_warning(self):
        valid, invalid, warning = validate_answer("[1] [2]", 3)
        assert valid == [1, 2]
        assert invalid == []
        assert warning is None  # 无实质内容，不警告

    def test_zero_sources(self):
        valid, invalid, warning = validate_answer("生态安葬 [1]", 0)
        assert valid == []
        assert invalid == [1]

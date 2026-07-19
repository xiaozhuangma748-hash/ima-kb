"""越界引用标记清理测试。

验证 LLM 幻觉生成的越界 [n] 标记会被正确删除，
保证正文编号与引用列表一致。
"""
import pytest

from core.retrieval.citation import (
    extract_citations,
    sanitize_outbound_citations,
)


class TestSanitizeOutboundCitations:
    """越界引用清理函数测试。"""

    def test_no_sources_returns_unchanged(self):
        """无参考资料时，文本应保持不变。"""
        text = "答案 [1] [2] [3]"
        assert sanitize_outbound_citations(text, 0) == text

    def test_empty_text_returns_empty(self):
        """空文本返回空。"""
        assert sanitize_outbound_citations("", 5) == ""

    def test_all_valid_citations_preserved(self):
        """所有合法引用保留不变。"""
        text = "杭州市是浙江省省会 [1]，详见 [2]。"
        assert sanitize_outbound_citations(text, 2) == text

    def test_outbound_citation_removed(self):
        """越界引用标记被删除（用户反馈的核心 bug）。"""
        # 只有 1 条资料，但 LLM 生成了 [3]
        text = "杭州市是浙江省的省会城市 [3]。"
        result = sanitize_outbound_citations(text, 1)
        assert "[3]" not in result
        assert "杭州市是浙江省的省会城市" in result

    def test_mixed_valid_and_invalid(self):
        """混合合法与越界引用，只删除越界部分。"""
        text = "结论 [1] 详见 [3]，再参考 [2]。"
        result = sanitize_outbound_citations(text, 2)
        assert "[1]" in result
        assert "[2]" in result
        assert "[3]" not in result

    def test_zero_index_removed(self):
        """[0] 是非法编号（合法范围 1..N），应被删除。"""
        text = "答案 [0] [1]"
        result = sanitize_outbound_citations(text, 1)
        assert "[0]" not in result
        assert "[1]" in result

    def test_three_digit_citation_removed(self):
        """3 位数字引用编号（如 [100]）超出合法范围时被删除。"""
        text = "答案 [100]"
        result = sanitize_outbound_citations(text, 3)
        assert "[100]" not in result

    def test_consecutive_brackets(self):
        """连续的引用标记 [1][3] 中只删除越界部分。"""
        text = "多资料支撑 [1][3]"
        result = sanitize_outbound_citations(text, 2)
        assert "[1]" in result
        assert "[3]" not in result

    def test_preserves_non_citation_brackets(self):
        """非引用格式的方括号（如 [备注]）不被删除。"""
        text = "这是 [备注] 内容 [1]"
        result = sanitize_outbound_citations(text, 1)
        assert "[备注]" in result
        assert "[1]" in result

    def test_real_scenario_from_user_feedback(self):
        """复现用户反馈的真实场景：1 条资料 + LLM 输出 [3]。"""
        # 用户问"杭州属于哪个省？"，检索只返回 1 条资料
        # 但 LLM 输出了"杭州市是浙江省的省会城市 [3]"
        text = (
            "行政归属\n\n"
            "杭州市是浙江省的省会城市 [3]。\n\n"
            "关联背景\n\n"
            "在殡葬改革及民生实事项目中，杭州市作为省会，"
            "常与浙江省整体政策联动 [3]。\n\n"
            "小结： 杭州属于浙江省。"
        )
        result = sanitize_outbound_citations(text, 1)
        # 越界 [3] 被全部删除
        assert "[3]" not in result
        # 正文内容保留
        assert "杭州市是浙江省的省会城市" in result
        assert "杭州属于浙江省" in result


class TestExtractCitationsAfterSanitize:
    """先清理越界标记，再提取引用，保证正文与列表一致。"""

    def test_citations_match_after_sanitize(self):
        """清理后，extract_citations 不会再遇到越界标记。"""
        text = "答案 [1] 和 [3]"
        sources = [
            {"doc_id": "d1", "title": "文档1", "paragraph_num": 1, "snippet": "内容1"},
        ]
        # 先清理
        clean = sanitize_outbound_citations(text, len(sources))
        # 再提取
        citations = extract_citations(clean, sources)
        # 只应提取到 [1]，不会有 [3]（因为已被清理）
        assert len(citations) == 1
        assert citations[0].marker == "[1]"

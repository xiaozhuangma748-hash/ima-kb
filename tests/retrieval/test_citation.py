"""引用结构化测试。"""
import pytest
from core.retrieval.citation import Citation, extract_citations


def test_extract_single_citation():
    """回答中有 [1] 时提取为引用。"""
    answer = "骨灰安置分为四类[1]。"
    sources = [
        {"doc_id": "abc123", "title": "殡葬管理条例", "paragraph_num": 3, "snippet": "骨灰安置分为四类"}
    ]
    citations = extract_citations(answer, sources)
    assert len(citations) == 1
    assert citations[0].marker == "[1]"
    assert citations[0].doc_id == "abc123"
    assert citations[0].title == "殡葬管理条例"
    assert citations[0].paragraph_num == 3


def test_extract_multiple_citations():
    """回答中有 [1][2] 时提取多个引用。"""
    answer = "生态安置包括树葬[1]和海葬[2]。"
    sources = [
        {"doc_id": "abc", "title": "条例A", "paragraph_num": 1, "snippet": "树葬"},
        {"doc_id": "def", "title": "条例B", "paragraph_num": 2, "snippet": "海葬"},
    ]
    citations = extract_citations(answer, sources)
    assert len(citations) == 2
    assert citations[0].doc_id == "abc"
    assert citations[1].doc_id == "def"


def test_extract_merged_citation():
    """[1][2] 合并引用时都提取。"""
    answer = "骨灰安置方式[1][2]多样。"
    sources = [
        {"doc_id": "abc", "title": "条例A", "paragraph_num": 1, "snippet": "方式"},
        {"doc_id": "def", "title": "条例B", "paragraph_num": 2, "snippet": "多样"},
    ]
    citations = extract_citations(answer, sources)
    assert len(citations) == 2


def test_no_citation_in_answer():
    """回答中无引用标记时返回空列表。"""
    answer = "骨灰安置方式多样。"
    sources = [{"doc_id": "abc", "title": "条例A", "paragraph_num": 1, "snippet": "骨灰"}]
    citations = extract_citations(answer, sources)
    assert citations == []


def test_citation_index_out_of_range():
    """引用编号超出 sources 范围时跳过。"""
    answer = "骨灰安置[5]。"
    sources = [{"doc_id": "abc", "title": "条例A", "paragraph_num": 1, "snippet": "骨灰"}]
    citations = extract_citations(answer, sources)
    assert citations == []


def test_citation_snippet_extraction():
    """Citation 包含 snippet 字段。"""
    answer = "安置[1]。"
    sources = [{"doc_id": "abc", "title": "条例A", "paragraph_num": 1, "snippet": "安置方式"}]
    citations = extract_citations(answer, sources)
    assert citations[0].snippet == "安置方式"

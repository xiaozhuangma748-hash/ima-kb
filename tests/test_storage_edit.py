"""Storage 文档属性编辑测试（Group 2: 展示但没设置入口）。"""
import pytest
from pathlib import Path

from core.storage import Storage
from core.ingestion.parser import ParsedDocument
from core.ingestion.chunker import Chunk


def _make_parsed(tmp_path: Path, title="测试文档", text="测试内容") -> ParsedDocument:
    file_path = tmp_path / "test.txt"
    file_path.write_text(text, encoding="utf-8")
    return ParsedDocument(
        title=title,
        text=text,
        file_path=file_path,
        file_type=".txt",
        language="zh",
        meta={},
    )


def _make_chunks(text="测试内容"):
    return [Chunk(index=0, content=text, token_count=10, start_char=0, end_char=len(text))]


def test_update_document_title(tmp_path):
    """update_document_title 修改标题。"""
    storage = Storage(storage_path=tmp_path)
    parsed = _make_parsed(tmp_path, "原标题")
    chunks = _make_chunks()
    record = storage.save_document(parsed, chunks, copy_file=False)
    doc_id = record.id

    ok = storage.update_document_title(doc_id, "新标题")
    assert ok is True
    doc = storage.get_document(doc_id)
    assert doc.title == "新标题"


def test_update_document_title_strips_whitespace(tmp_path):
    """update_document_title 去除首尾空白。"""
    storage = Storage(storage_path=tmp_path)
    parsed = _make_parsed(tmp_path, "原标题")
    chunks = _make_chunks()
    record = storage.save_document(parsed, chunks, copy_file=False)
    doc_id = record.id

    ok = storage.update_document_title(doc_id, "  新标题  ")
    assert ok is True
    doc = storage.get_document(doc_id)
    assert doc.title == "新标题"


def test_update_document_title_empty_returns_false(tmp_path):
    """空标题应返回 False。"""
    storage = Storage(storage_path=tmp_path)
    parsed = _make_parsed(tmp_path, "原标题")
    chunks = _make_chunks()
    record = storage.save_document(parsed, chunks, copy_file=False)
    doc_id = record.id

    assert storage.update_document_title(doc_id, "") is False
    assert storage.update_document_title(doc_id, "   ") is False
    # 原标题不变
    doc = storage.get_document(doc_id)
    assert doc.title == "原标题"


def test_update_document_title_nonexistent(tmp_path):
    """不存在的文档返回 False。"""
    storage = Storage(storage_path=tmp_path)
    assert storage.update_document_title("nonexistent_id", "新标题") is False


# ---- 标签管理 ----

def test_rename_tag(tmp_path):
    """rename_tag 替换所有文档中的旧标签。"""
    storage = Storage(storage_path=tmp_path)
    parsed1 = _make_parsed(tmp_path, "文档1", "内容1")
    parsed2 = _make_parsed(tmp_path, "文档2", "内容2")
    chunks = _make_chunks()
    storage.save_document(parsed1, chunks, copy_file=False, tags=["殡葬", "政策"])
    storage.save_document(parsed2, chunks, copy_file=False, tags=["殡葬", "补贴"])

    affected = storage.rename_tag("殡葬", "身后事")
    assert affected == 2
    # 检查所有文档标签
    docs = storage.list_documents()
    for doc in docs:
        assert "殡葬" not in doc.tags
        assert "身后事" in doc.tags


def test_rename_tag_to_existing_keeps_no_duplicate(tmp_path):
    """rename_tag 目标标签已存在时不重复。"""
    storage = Storage(storage_path=tmp_path)
    parsed = _make_parsed(tmp_path, "文档", "内容")
    chunks = _make_chunks()
    storage.save_document(parsed, chunks, copy_file=False, tags=["政策", "骨灰"])

    # 把 "骨灰" 重命名为 "政策"（目标已存在）
    affected = storage.rename_tag("骨灰", "政策")
    assert affected == 1
    doc = storage.list_documents()[0]
    # 应该只有一个 "政策"，没有 "骨灰"
    assert doc.tags.count("政策") == 1
    assert "骨灰" not in doc.tags


def test_rename_tag_empty_returns_zero(tmp_path):
    """空标签返回 0。"""
    storage = Storage(storage_path=tmp_path)
    assert storage.rename_tag("", "新") == 0
    assert storage.rename_tag("旧", "") == 0
    assert storage.rename_tag("   ", "新") == 0


def test_rename_tag_not_found_returns_zero(tmp_path):
    """标签不存在时返回 0。"""
    storage = Storage(storage_path=tmp_path)
    parsed = _make_parsed(tmp_path, "文档", "内容")
    chunks = _make_chunks()
    storage.save_document(parsed, chunks, copy_file=False, tags=["现有"])

    assert storage.rename_tag("不存在", "新") == 0


def test_merge_tag(tmp_path):
    """merge_tag 合并源标签到目标标签。"""
    storage = Storage(storage_path=tmp_path)
    parsed1 = _make_parsed(tmp_path, "文档1", "内容1")
    parsed2 = _make_parsed(tmp_path, "文档2", "内容2")
    chunks = _make_chunks()
    storage.save_document(parsed1, chunks, copy_file=False, tags=["骨灰", "政策"])
    storage.save_document(parsed2, chunks, copy_file=False, tags=["补贴"])

    # 合并 "骨灰" → "政策"
    affected = storage.merge_tag("骨灰", "政策")
    assert affected == 1
    docs = storage.list_documents()
    for doc in docs:
        assert "骨灰" not in doc.tags


def test_merge_tag_same_tag_returns_zero(tmp_path):
    """合并到自身返回 0。"""
    storage = Storage(storage_path=tmp_path)
    assert storage.merge_tag("政策", "政策") == 0


def test_merge_tag_empty_returns_zero(tmp_path):
    """空标签返回 0。"""
    storage = Storage(storage_path=tmp_path)
    assert storage.merge_tag("", "目标") == 0
    assert storage.merge_tag("源", "") == 0


def test_delete_chunk(tmp_path):
    """delete_chunk 删除单个分块。"""
    storage = Storage(storage_path=tmp_path)
    parsed = _make_parsed(tmp_path, "文档", "内容")
    chunks = [
        Chunk(index=0, content="分块0", token_count=5, start_char=0, end_char=3),
        Chunk(index=1, content="分块1", token_count=5, start_char=3, end_char=6),
    ]
    record = storage.save_document(parsed, chunks, copy_file=False)
    chunk_id = f"{record.id}_0"

    # 删除前有 2 个 chunk
    assert len(storage.get_chunks(record.id)) == 2
    ok = storage.delete_chunk(chunk_id)
    assert ok is True
    # 删除后剩 1 个
    assert len(storage.get_chunks(record.id)) == 1


def test_delete_chunk_nonexistent_returns_false(tmp_path):
    """删除不存在的 chunk 返回 False。"""
    storage = Storage(storage_path=tmp_path)
    assert storage.delete_chunk("nonexistent_chunk") is False

"""Storage 与 VectorIndex 的同步闭环测试。

覆盖：
- save_document 自动同步向量索引
- delete_document 自动清理向量索引
- attach/detach vector_index
- rebuild_vector_index 全量重建
"""
import pytest
from pathlib import Path
from unittest.mock import MagicMock

from core.storage import Storage
from core.ingestion.parser import ParsedDocument
from core.ingestion.chunker import Chunk


def _make_parsed(tmp_path: Path, text: str = "测试内容", title: str = "测试文档") -> ParsedDocument:
    """构造一个 ParsedDocument 用于测试。"""
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


def _make_chunks(text: str = "测试内容") -> list:
    """构造单个 chunk。"""
    return [Chunk(index=0, content=text, token_count=10, start_char=0, end_char=len(text))]


def test_save_document_calls_vector_index_when_attached(tmp_path):
    """save_document 在注入 vector_index 后应调用 add_chunks_batch。"""
    storage = Storage(storage_path=tmp_path)
    mock_vi = MagicMock()
    mock_vi.is_available.return_value = True

    storage.attach_vector_index(mock_vi)
    parsed = _make_parsed(tmp_path, "骨灰安置政策", "测试")
    chunks = _make_chunks("骨灰安置政策")

    storage.save_document(parsed, chunks, copy_file=False)

    # 应该调用 add_chunks_batch
    mock_vi.add_chunks_batch.assert_called_once()
    call_args = mock_vi.add_chunks_batch.call_args[0][0]
    assert len(call_args) == 1
    assert call_args[0]["content"] == "骨灰安置政策"


def test_save_document_no_vector_index_no_error(tmp_path):
    """未注入 vector_index 时 save_document 不应报错。"""
    storage = Storage(storage_path=tmp_path)
    parsed = _make_parsed(tmp_path, "内容", "标题")
    chunks = _make_chunks("内容")
    # 不注入 vector_index
    record = storage.save_document(parsed, chunks, copy_file=False)
    assert record is not None


def test_save_document_vector_index_failure_does_not_block(tmp_path):
    """向量索引同步失败不应阻塞入库。"""
    storage = Storage(storage_path=tmp_path)
    mock_vi = MagicMock()
    mock_vi.is_available.return_value = True
    mock_vi.add_chunks_batch.side_effect = Exception("向量索引爆炸了")

    storage.attach_vector_index(mock_vi)
    parsed = _make_parsed(tmp_path, "内容", "标题")
    chunks = _make_chunks("内容")

    # 不应抛异常
    record = storage.save_document(parsed, chunks, copy_file=False)
    assert record is not None
    # 数据库应该有记录
    assert storage.get_document(record.id) is not None


def test_delete_document_calls_vector_delete(tmp_path):
    """delete_document 在注入 vector_index 后应调用 delete_document。"""
    storage = Storage(storage_path=tmp_path)
    mock_vi = MagicMock()
    mock_vi.is_available.return_value = True
    mock_vi.delete_document.return_value = 1

    storage.attach_vector_index(mock_vi)
    parsed = _make_parsed(tmp_path, "内容", "标题")
    chunks = _make_chunks("内容")
    record = storage.save_document(parsed, chunks, copy_file=False)

    result = storage.delete_document(record.id)
    assert result is True
    mock_vi.delete_document.assert_called_once_with(record.id)


def test_delete_document_vector_failure_does_not_block(tmp_path):
    """向量索引删除失败不应阻塞文档删除。"""
    storage = Storage(storage_path=tmp_path)
    mock_vi = MagicMock()
    mock_vi.is_available.return_value = True
    mock_vi.delete_document.side_effect = Exception("删除失败")

    storage.attach_vector_index(mock_vi)
    parsed = _make_parsed(tmp_path, "内容", "标题")
    chunks = _make_chunks("内容")
    record = storage.save_document(parsed, chunks, copy_file=False)

    result = storage.delete_document(record.id)
    assert result is True
    # 数据库记录应已删除
    assert storage.get_document(record.id) is None


def test_detach_vector_index(tmp_path):
    """detach 后 save/delete 不应再调用 vector_index。"""
    storage = Storage(storage_path=tmp_path)
    mock_vi = MagicMock()
    mock_vi.is_available.return_value = True

    storage.attach_vector_index(mock_vi)
    storage.detach_vector_index()

    parsed = _make_parsed(tmp_path, "内容", "标题")
    chunks = _make_chunks("内容")
    storage.save_document(parsed, chunks, copy_file=False)

    # 不应调用 add_chunks_batch
    mock_vi.add_chunks_batch.assert_not_called()


def test_rebuild_vector_index(tmp_path):
    """rebuild_vector_index 应从数据库全量重建向量索引。"""
    storage = Storage(storage_path=tmp_path)
    mock_vi = MagicMock()
    mock_vi.is_available.return_value = True

    # 先入库 2 个文档
    for i in range(2):
        parsed = _make_parsed(tmp_path, f"内容{i}", f"标题{i}")
        chunks = _make_chunks(f"内容{i}")
        storage.save_document(parsed, chunks, copy_file=False)

    count = storage.rebuild_vector_index(mock_vi)
    assert count == 2
    # 应该调用 build_index
    mock_vi.build_index.assert_called_once()
    call_args = mock_vi.build_index.call_args[0][0]
    assert len(call_args) == 2


def test_rebuild_vector_index_unavailable_returns_minus_one(tmp_path):
    """向量索引不可用时 rebuild_vector_index 应返回 -1。"""
    storage = Storage(storage_path=tmp_path)
    mock_vi = MagicMock()
    mock_vi.is_available.return_value = False

    count = storage.rebuild_vector_index(mock_vi)
    assert count == -1
    mock_vi.build_index.assert_not_called()


def test_rebuild_vector_index_empty_db(tmp_path):
    """空数据库重建应返回 0。"""
    storage = Storage(storage_path=tmp_path)
    mock_vi = MagicMock()
    mock_vi.is_available.return_value = True

    count = storage.rebuild_vector_index(mock_vi)
    assert count == 0
    mock_vi.build_index.assert_called_once()
    # 传入空列表
    call_args = mock_vi.build_index.call_args[0][0]
    assert call_args == []

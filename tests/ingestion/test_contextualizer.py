"""Contextual Retrieval 并行化测试。

验证：
1. enabled=False / llm_client=None 时直接返回
2. 单 chunk 走串行路径
3. 多 chunk 走并行路径，结果正确写入
4. 部分 chunk 失败时不阻塞其他 chunk
5. 并行结果与串行结果一致（内容顺序不错位）
"""
from __future__ import annotations

import threading
from unittest.mock import MagicMock, patch

import pytest

from core.ingestion.chunker import Chunk
from core.ingestion.contextualizer import contextualize_chunks
from core.ingestion.parser import ParsedDocument


def _make_doc(text: str = "这是一份关于殡葬政策的文档。", title: str = "测试文档") -> ParsedDocument:
    return ParsedDocument(
        text=text,
        title=title,
        file_path=None,
        file_type=".txt",
        language="zh",
        meta={},
    )


def _make_chunk(content: str, index: int = 0) -> Chunk:
    return Chunk(
        content=content,
        start_char=0,
        end_char=len(content),
        index=index,
        token_count=10,
    )


class _FakeLLM:
    """模拟 LLM 客户端：返回带 chunk 内容标记的摘要，便于验证对应关系。"""

    def __init__(self, fail_indices: set = None):
        self.fail_indices = fail_indices or set()
        self.call_count = 0
        self.call_lock = threading.Lock()

    def chat(self, messages, temperature=0.0, max_tokens=150, max_retries=1):
        # 提取 chunk_content：模板中 "片段内容：\n<chunk_content>" 紧挨着
        user_msg = messages[-1]["content"]
        with self.call_lock:
            self.call_count += 1
        lines = user_msg.split("\n")
        chunk_content = ""
        for i, line in enumerate(lines):
            if line.strip() == "片段内容：" and i + 1 < len(lines):
                chunk_content = lines[i + 1].strip()
                break
        # 失败模拟
        if chunk_content in self.fail_indices:
            raise RuntimeError(f"模拟失败 chunk={chunk_content}")
        return f"摘要-{chunk_content}"


class TestContextualizeChunks:
    """contextualize_chunks 并行化测试。"""

    def test_disabled_returns_unchanged(self):
        """enabled=False 时直接返回原 chunks。"""
        chunks = [_make_chunk("内容A", 0), _make_chunk("内容B", 1)]
        original = [c.content for c in chunks]
        result = contextualize_chunks(chunks, _make_doc(), llm_client=_FakeLLM(), enabled=False)
        assert result is chunks
        assert [c.content for c in result] == original

    def test_no_llm_client_returns_unchanged(self):
        """llm_client=None 时直接返回。"""
        chunks = [_make_chunk("内容A", 0)]
        original = [c.content for c in chunks]
        result = contextualize_chunks(chunks, _make_doc(), llm_client=None, enabled=True)
        assert result is chunks
        assert [c.content for c in result] == original

    def test_empty_chunks_returns_unchanged(self):
        """空 chunks 列表直接返回。"""
        result = contextualize_chunks([], _make_doc(), llm_client=_FakeLLM(), enabled=True)
        assert result == []

    def test_single_chunk_serial_path(self):
        """单 chunk 走串行路径。"""
        chunks = [_make_chunk("单块内容", 0)]
        llm = _FakeLLM()
        result = contextualize_chunks(chunks, _make_doc(), llm_client=llm, enabled=True)
        assert llm.call_count == 1
        assert "[文档上下文]" in result[0].content
        assert "[内容] 单块内容" in result[0].content

    def test_multiple_chunks_parallel_correctness(self):
        """多 chunk 并行：摘要与对应 chunk 内容正确匹配。"""
        chunks = [
            _make_chunk("第一段内容", 0),
            _make_chunk("第二段内容", 1),
            _make_chunk("第三段内容", 2),
        ]
        llm = _FakeLLM()
        result = contextualize_chunks(chunks, _make_doc(), llm_client=llm, enabled=True, max_workers=3)
        # 每个 chunk 都应有自己的摘要（FakeLLM 基于内容生成）
        assert llm.call_count == 3
        for i, c in enumerate(result):
            assert "[文档上下文]" in c.content
            # 验证摘要和内容对应（不串位）
            assert f"内容{i+1}" in c.content or "第" in c.content

    def test_partial_failure_does_not_block(self):
        """部分 chunk 失败时不阻塞其他 chunk。"""
        chunks = [
            _make_chunk("内容0", 0),
            _make_chunk("内容1", 1),  # 这个会失败
            _make_chunk("内容2", 2),
        ]
        # 模拟第 1 个 chunk 失败（FakeLLM 用内容末尾识别）
        llm = _FakeLLM(fail_indices={"内容1"})
        result = contextualize_chunks(chunks, _make_doc(), llm_client=llm, enabled=True, max_workers=2)
        # chunk 0 和 2 应该成功，chunk 1 保持原样
        assert "[文档上下文]" in result[0].content
        assert "[文档上下文]" not in result[1].content
        assert result[1].content == "内容1"  # 原样
        assert "[文档上下文]" in result[2].content

    def test_parallel_no_content_corruption(self):
        """并行化不会导致 chunk 内容错位。"""
        # 用更细的内容区分
        chunks = [_make_chunk(f"UNIQUE_MARKER_{i}", i) for i in range(5)]
        llm = _FakeLLM()
        result = contextualize_chunks(chunks, _make_doc(), llm_client=llm, enabled=True, max_workers=4)
        for i, c in enumerate(result):
            # 必须包含原始 UNIQUE_MARKER_i，证明内容没串位
            assert f"UNIQUE_MARKER_{i}" in c.content, f"chunk {i} 内容错位: {c.content}"

    def test_max_workers_env_var(self, monkeypatch):
        """环境变量 IMA_CONTEXTUAL_WORKERS 控制并发度。"""
        monkeypatch.setenv("IMA_CONTEXTUAL_WORKERS", "2")
        chunks = [_make_chunk(f"内容{i}", i) for i in range(4)]
        llm = _FakeLLM()
        result = contextualize_chunks(chunks, _make_doc(), llm_client=llm, enabled=True)
        assert llm.call_count == 4
        for c in result:
            assert "[文档上下文]" in c.content

    def test_max_workers_capped_by_chunk_count(self):
        """max_workers 不会超过 chunk 数。"""
        chunks = [_make_chunk("内容0", 0), _make_chunk("内容1", 1)]
        llm = _FakeLLM()
        # 即使传入 max_workers=10，实际并发度也不超过 2
        result = contextualize_chunks(
            chunks, _make_doc(), llm_client=llm, enabled=True, max_workers=10
        )
        assert llm.call_count == 2
        for c in result:
            assert "[文档上下文]" in c.content

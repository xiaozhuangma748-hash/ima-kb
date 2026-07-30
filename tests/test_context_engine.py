"""上下文工程 P0 单元测试：TokenBudget + chain.py 上下文组装。"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from core.context.token_budget import TokenBudget, count_tokens, truncate_to_tokens


# ============================================================
# TokenBudget 单元测试
# ============================================================

class TestCountTokens:
    """token 计数测试。"""

    def test_empty_string(self):
        assert count_tokens("") == 0
        assert count_tokens(None) == 0  # type: ignore

    def test_english_text(self):
        # 英文文本应该返回正数
        tokens = count_tokens("hello world")
        assert tokens > 0

    def test_chinese_text(self):
        # 中文文本应该返回正数
        tokens = count_tokens("你好世界")
        assert tokens > 0

    def test_mixed_text(self):
        tokens = count_tokens("Hello 你好 world 世界")
        assert tokens > 0


class TestTruncateToTokens:
    """token 截断测试。"""

    def test_empty_string(self):
        assert truncate_to_tokens("", 100) == ""
        assert truncate_to_tokens(None, 100) is None  # type: ignore

    def test_no_truncation_needed(self):
        text = "short text"
        assert truncate_to_tokens(text, 1000) == text

    def test_truncation(self):
        long_text = "a" * 500
        truncated = truncate_to_tokens(long_text, 50)
        assert len(truncated) < len(long_text)
        assert len(truncated) > 0


class TestTokenBudget:
    """TokenBudget 分配测试。"""

    def _make_result(self, content: str, score: float, chunk_id: str = "c1"):
        """构造模拟检索结果。"""
        r = MagicMock()
        r.content = content
        r.score = score
        r.chunk_id = chunk_id
        return r

    def test_empty_inputs(self):
        """空输入应正常处理。"""
        budget = TokenBudget(total=4096)
        allocation, truncated = budget.allocate(
            system_prompt="系统",
            user_query="问题",
        )
        assert allocation.system_tokens > 0
        assert allocation.user_query_tokens > 0
        assert truncated["retrieval"] == []
        assert truncated["history"] == []
        assert truncated["summary"] == ""
        assert truncated["cross_session"] == ""

    def test_normal_allocation(self):
        """正常预算分配，不触发截断。"""
        budget = TokenBudget(total=4096)
        results = [self._make_result("内容" * 50, 0.9, "c1")]
        history = [
            {"role": "user", "content": "之前的问题"},
            {"role": "assistant", "content": "之前的回答"},
        ]
        allocation, truncated = budget.allocate(
            system_prompt="系统提示",
            user_query="用户问题",
            retrieval_results=results,
            history=history,
            summary="对话摘要",
            cross_session="跨会话记忆",
        )
        assert len(truncated["retrieval"]) == 1
        assert len(truncated["history"]) == 2
        assert truncated["summary"] == "对话摘要"
        assert truncated["cross_session"] == "跨会话记忆"
        assert allocation.total_allocated <= 4096

    def test_retrieval_truncation_by_score(self):
        """检索结果超预算时按 score 保留高分。"""
        # tiktoken 下 "a"*1000 ≈ 125 token，3 条共 375 token
        # total=300 → retrieval_budget ≈ 134，能保留 c1+c2，c3 被截断
        budget = TokenBudget(total=300)  # 小预算触发截断
        results = [
            self._make_result("a" * 1000, 0.9, "c1"),
            self._make_result("b" * 1000, 0.5, "c2"),
            self._make_result("c" * 1000, 0.3, "c3"),
        ]
        _, truncated = budget.allocate(
            system_prompt="系统",
            user_query="问题",
            retrieval_results=results,
        )
        # 高分的 c1 应该被保留
        kept_ids = {getattr(r, "chunk_id") for r in truncated["retrieval"]}
        assert "c1" in kept_ids
        # 不应该所有都保留
        assert len(truncated["retrieval"]) < 3

    def test_history_truncation_from_oldest(self):
        """历史超预算时从最早开始截断。"""
        budget = TokenBudget(total=200)
        history = [
            {"role": "user", "content": "最早的问题" * 20},
            {"role": "assistant", "content": "最早的回答" * 20},
            {"role": "user", "content": "最近的问题"},
            {"role": "assistant", "content": "最近的回答"},
        ]
        _, truncated = budget.allocate(
            system_prompt="系统",
            user_query="问题",
            history=history,
        )
        # 最近的应该保留
        if truncated["history"]:
            last_msg = truncated["history"][-1]
            assert "最近" in last_msg["content"]

    def test_summary_truncation(self):
        """摘要超预算时被截断或丢弃。"""
        budget = TokenBudget(total=200)
        long_summary = "摘要内容" * 100
        _, truncated = budget.allocate(
            system_prompt="系统",
            user_query="问题",
            summary=long_summary,
        )
        # 应该被截断
        assert len(truncated["summary"]) < len(long_summary)

    def test_total_never_exceeds_budget(self):
        """总分配不超过预算。"""
        budget = TokenBudget(total=500)
        results = [self._make_result("内容" * 100, 0.9, f"c{i}") for i in range(10)]
        history = [{"role": "user", "content": "历史" * 50} for _ in range(10)]
        allocation, _ = budget.allocate(
            system_prompt="系统" * 50,
            user_query="问题" * 50,
            retrieval_results=results,
            history=history,
            summary="摘要" * 100,
            cross_session="跨会话" * 100,
        )
        assert allocation.total_allocated <= 500

    def test_extreme_tiny_budget(self):
        """极小预算下不崩溃。"""
        budget = TokenBudget(total=10)
        allocation, truncated = budget.allocate(
            system_prompt="系统提示" * 100,
            user_query="用户问题" * 100,
            retrieval_results=[self._make_result("内容" * 100, 0.9)],
            history=[{"role": "user", "content": "历史" * 50}],
            summary="摘要" * 100,
            cross_session="跨会话" * 100,
        )
        # 不崩溃即可
        assert isinstance(truncated, dict)
        assert "retrieval" in truncated


# ============================================================
# chain.py 上下文组装测试
# ============================================================

def _make_mock_result(content="资料内容", score=0.5, chunk_id="c1", doc_id="d1"):
    """构造完整的 mock HybridResult。

    score 默认 0.5（高于硬拒答阈值 0.15），避免干扰上下文组装测试。
    """
    r = MagicMock()
    r.content = content
    r.score = score
    r.chunk_id = chunk_id
    r.doc_id = doc_id
    r.doc_title = "文档标题"
    r.source = "bm25"
    r.format_tag = ""
    r.paragraph_num = 1
    return r


class TestRAGChainContextAssembly:
    """测试 RAGChain.ask() 是否正确组装上下文消息。"""

    def test_ask_accepts_new_params(self):
        """ask() 方法签名应接受 cross_session_context 和 summary。"""
        import inspect
        from core.qa.chain import RAGChain
        sig = inspect.signature(RAGChain.ask)
        params = sig.parameters
        assert "cross_session_context" in params
        assert "summary" in params
        assert "history" in params

    def test_ask_stream_accepts_new_params(self):
        """ask_stream() 方法签名应接受 cross_session_context 和 summary。"""
        import inspect
        from core.qa.chain import RAGChain
        sig = inspect.signature(RAGChain.ask_stream)
        params = sig.parameters
        assert "cross_session_context" in params
        assert "summary" in params
        assert "history" in params

    def _make_chain(self, tmp_path):
        """构造一个轻量 RAGChain 实例（mock 掉重型组件）。"""
        from core.qa.chain import RAGChain
        from core.storage import Storage

        storage = Storage(storage_path=tmp_path)
        # 关闭 parent_window 避免触发 DB 查询
        import config
        original = config.settings.parent_window
        config.settings.parent_window = 0
        try:
            chain = RAGChain(storage=storage)
        finally:
            config.settings.parent_window = original

        # Mock LLM 捕获 messages
        captured_messages = []

        def mock_chat(messages, temperature=0.2):
            captured_messages.extend(messages)
            return "测试回答 [1]"

        chain.llm.chat = mock_chat
        chain.llm.chat_stream = lambda messages, temperature=0.2: iter(["测试回答 [1]"])
        # Mock 检索返回有结果
        chain.hybrid.search = MagicMock(return_value=[_make_mock_result()])
        chain.reranker = None
        # 关闭缓存
        chain._answer_cache = None
        return chain, captured_messages

    def test_messages_include_cross_session_when_provided(self, tmp_path):
        """传入 cross_session_context 时应出现在 LLM messages 中。"""
        chain, captured = self._make_chain(tmp_path)
        chain.ask("测试问题", cross_session_context="跨会话记忆内容")
        cross_msgs = [m for m in captured if "跨会话记忆" in m.get("content", "")]
        assert len(cross_msgs) > 0

    def test_messages_include_summary_when_provided(self, tmp_path):
        """传入 summary 时应出现在 LLM messages 中。"""
        chain, captured = self._make_chain(tmp_path)
        chain.ask("测试问题", summary="对话摘要内容")
        summary_msgs = [m for m in captured if "对话摘要" in m.get("content", "")]
        assert len(summary_msgs) > 0

    def test_messages_include_history_when_provided(self, tmp_path):
        """传入 history 时应出现在 LLM messages 中。"""
        chain, captured = self._make_chain(tmp_path)
        history = [
            {"role": "user", "content": "之前的问题"},
            {"role": "assistant", "content": "之前的回答"},
        ]
        chain.ask("测试问题", history=history)
        history_contents = [m["content"] for m in captured if m["role"] in ("user", "assistant")]
        assert "之前的问题" in history_contents
        assert "之前的回答" in history_contents

    def test_no_history_no_extra_messages(self, tmp_path):
        """不传 history/summary/cross_session 时只有 system + user 两条消息。"""
        chain, captured = self._make_chain(tmp_path)
        chain.ask("测试问题")
        # 应该只有 system + user 两条
        assert len(captured) == 2
        assert captured[0]["role"] == "system"
        assert captured[1]["role"] == "user"

    def test_all_context_combined(self, tmp_path):
        """同时传入 history/summary/cross_session 时全部出现在 messages 中。"""
        chain, captured = self._make_chain(tmp_path)
        history = [
            {"role": "user", "content": "历史问题"},
            {"role": "assistant", "content": "历史回答"},
        ]
        chain.ask(
            "测试问题",
            history=history,
            summary="摘要内容",
            cross_session_context="跨会话内容",
        )
        all_content = " ".join(m["content"] for m in captured)
        assert "历史问题" in all_content
        assert "摘要内容" in all_content
        assert "跨会话内容" in all_content

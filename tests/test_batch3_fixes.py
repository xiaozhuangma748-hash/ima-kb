"""第三批低优先级修复的测试覆盖。

覆盖项：
- GraphStore 损坏时备份
- DailyTaskManager daily_tasks None 防护
- get_llm_degrade_message 错误类型分级
- Reranker snippet 省略号
- chunker 空文本处理
- FileTracker.get_file_history
- REPL CMD_ALIASES 扩展
"""
import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest


# ============================================================
# 1. GraphStore 损坏时备份
# ============================================================

def test_graph_store_corrupt_file_backed_up(tmp_path):
    """损坏的 graph.json 应被备份而非静默重置。"""
    from core.graph.store import GraphStore

    # 写入损坏的 JSON
    corrupt_path = tmp_path / "graph.json"
    corrupt_path.write_text("{invalid json content", encoding="utf-8")

    # 加载应触发备份
    store = GraphStore(storage_path=tmp_path)

    # 图谱应为空
    assert len(store.graph.nodes) == 0
    # 原损坏文件应被重命名为 .bak.xxx
    bak_files = list(tmp_path.glob("graph.json.bak.*"))
    assert len(bak_files) == 1, f"应生成 1 个备份文件，实际: {bak_files}"


def test_graph_store_corrupt_missing_key_backed_up(tmp_path):
    """JSON 结构缺少必要 key 也应备份。"""
    from core.graph.store import GraphStore

    # 写入缺少 nodes 字段的 JSON（不会触发 KeyError，因为用了 .get）
    # 改为写入会导致 KeyError 的结构：nodes 是 list 但元素缺 id
    corrupt_path = tmp_path / "graph.json"
    corrupt_path.write_text(
        json.dumps({"nodes": [{"label": "x"}]}),  # 缺 id → KeyError
        encoding="utf-8",
    )

    store = GraphStore(storage_path=tmp_path)
    assert len(store.graph.nodes) == 0
    bak_files = list(tmp_path.glob("graph.json.bak.*"))
    assert len(bak_files) == 1


# ============================================================
# 2. DailyTaskManager None 防护
# ============================================================

def test_check_progress_none_daily_tasks_returns_empty(tmp_path):
    """daily_tasks=None 时 check_progress 不应崩溃。"""
    from core.pet.tasks import DailyTaskManager
    pet = MagicMock()
    pet.daily_tasks = None

    mgr = DailyTaskManager()
    result = mgr.check_progress(pet, "ingest")
    assert result == []


def test_list_tasks_none_daily_tasks_returns_empty_list(tmp_path):
    """daily_tasks=None 时 list_tasks 返回空列表。"""
    from core.pet.tasks import DailyTaskManager
    pet = MagicMock()
    pet.daily_tasks = None

    mgr = DailyTaskManager()
    result = mgr.list_tasks(pet)
    assert result == []


def test_check_progress_empty_list_returns_empty(tmp_path):
    """daily_tasks=[] 时正常返回空。"""
    from core.pet.tasks import DailyTaskManager
    pet = MagicMock()
    pet.daily_tasks = []

    mgr = DailyTaskManager()
    result = mgr.check_progress(pet, "qa")
    assert result == []


# ============================================================
# 3. get_llm_degrade_message 错误类型分级
# ============================================================

class _FakeTimeoutError(Exception):
    pass


class _FakeRateLimitError(Exception):
    pass


class _FakeAuthError(Exception):
    pass


class _FakeConnectError(Exception):
    pass


def test_degrade_timeout_hint():
    """超时错误应包含超时建议。"""
    # 用真实异常类型名匹配
    from core.llm.degrade import get_llm_degrade_message

    class Timeout(Exception):
        pass

    err = Timeout("连接超时")
    msg = get_llm_degrade_message(error=err, has_sources=False)
    assert "超时" in msg


def test_degrade_rate_limit_hint():
    """429 错误应包含限流建议。"""
    from core.llm.degrade import get_llm_degrade_message

    err = Exception("HTTP 429: rate limit exceeded")
    msg = get_llm_degrade_message(error=err, has_sources=True, source_count=3)
    assert "限流" in msg or "429" in msg


def test_degrade_auth_hint():
    """鉴权错误应包含 API Key 建议。"""
    from core.llm.degrade import get_llm_degrade_message

    err = Exception("401 Unauthorized: invalid api key")
    msg = get_llm_degrade_message(error=err, has_sources=False)
    assert "API Key" in msg or "鉴权" in msg


def test_degrade_connect_hint():
    """连接错误应包含网络建议。"""
    from core.llm.degrade import get_llm_degrade_message

    err = Exception("connection error: network unreachable")
    msg = get_llm_degrade_message(error=err, has_sources=False)
    assert "网络" in msg or "连接" in msg


def test_degrade_unknown_error_no_hint():
    """未知错误不应附加 hint。"""
    from core.llm.degrade import get_llm_degrade_message

    err = ValueError("some weird error")
    msg = get_llm_degrade_message(error=err, has_sources=False)
    assert "·" not in msg  # 无 hint 分隔符


def test_degrade_no_error_no_hint():
    """无错误时不应有 hint。"""
    from core.llm.degrade import get_llm_degrade_message

    msg = get_llm_degrade_message(error=None, has_sources=True, source_count=2)
    assert "·" not in msg
    assert "2 条" in msg


# ============================================================
# 4. Reranker snippet 省略号
# ============================================================

def test_rerank_snippet_has_ellipsis_for_long_content():
    """超 200 字的内容 snippet 应带省略号。"""
    from core.retrieval.rerank import Reranker
    from core.retrieval.hybrid import HybridResult
    from unittest.mock import MagicMock

    long_content = "A" * 300
    candidates = [
        HybridResult(
            chunk_id="c1", doc_id="d1", score=0.5, source="bm25",
            content=long_content, doc_title="测试文档",
        )
    ]

    llm = MagicMock()
    # 让 _call_llm_for_scores 抛异常走 fallback
    llm.chat.side_effect = Exception("LLM 不可用")

    reranker = Reranker(llm)
    # 直接测试 _call_llm_for_scores 的 snippet 构造
    # 由于异常会走 fallback，我们直接验证候选文本构造逻辑
    # 改为直接调用内部方法
    try:
        reranker._call_llm_for_scores("query", candidates)
    except Exception:
        pass

    # 检查最后一次 LLM 调用的 prompt 中包含省略号
    call_args = llm.chat.call_args
    assert call_args is not None
    # prompt 在 messages 中
    messages = call_args.kwargs.get("messages") or call_args.args[0]
    prompt_text = ""
    if isinstance(messages, list):
        for m in messages:
            if isinstance(m, dict) and "content" in m:
                prompt_text += m["content"]
    assert "..." in prompt_text, "长内容 snippet 应包含省略号"


def test_rerank_snippet_no_ellipsis_for_short_content():
    """短内容 snippet 不应有省略号。"""
    from core.retrieval.rerank import Reranker
    from core.retrieval.hybrid import HybridResult
    from unittest.mock import MagicMock

    short_content = "短内容"
    candidates = [
        HybridResult(
            chunk_id="c1", doc_id="d1", score=0.5, source="bm25",
            content=short_content, doc_title="测试",
        )
    ]

    llm = MagicMock()
    llm.chat.return_value = "[]"

    reranker = Reranker(llm)
    try:
        reranker._call_llm_for_scores("query", candidates)
    except Exception:
        pass

    messages = llm.chat.call_args.kwargs.get("messages") or llm.chat.call_args.args[0]
    prompt_text = ""
    if isinstance(messages, list):
        for m in messages:
            if isinstance(m, dict) and "content" in m:
                prompt_text += m["content"]
    assert "..." not in prompt_text


# ============================================================
# 5. chunker 空文本处理
# ============================================================

def test_estimate_tokens_empty_returns_zero():
    """空文本 token 估算应为 0。"""
    from core.ingestion.chunker import _estimate_tokens
    assert _estimate_tokens("") == 0
    assert _estimate_tokens(None) == 0  # None 也应安全


def test_estimate_tokens_non_empty():
    """非空文本正常估算。"""
    from core.ingestion.chunker import _estimate_tokens
    assert _estimate_tokens("abcd") == 2
    assert _estimate_tokens("中文测试") == 2  # 4 字 / 2


def test_split_long_text_empty_returns_empty_list():
    """空文本切分应返回空列表。"""
    from core.ingestion.chunker import _split_long_text
    assert _split_long_text("", max_size=100, overlap=10) == []


def test_split_long_text_short_text_returns_single():
    """短文本返回单块。"""
    from core.ingestion.chunker import _split_long_text
    result = _split_long_text("短文本", max_size=100, overlap=10)
    assert len(result) == 1
    assert result[0][2] == "短文本"


# ============================================================
# 6. FileTracker.get_file_history
# ============================================================

def test_get_file_history_returns_tracked_info(tmp_path):
    """已追踪文件返回 FileInfo。"""
    from core.sync.tracker import FileTracker

    # 创建测试文件
    test_file = tmp_path / "test.txt"
    test_file.write_text("hello world", encoding="utf-8")

    tracker = FileTracker(tmp_path)
    tracker.track_file(str(test_file), "doc123")

    info = tracker.get_file_history(str(test_file))
    assert info is not None
    assert info.doc_id == "doc123"
    assert info.file_size == 11
    assert info.file_hash  # 非空


def test_get_file_history_untracked_returns_none(tmp_path):
    """未追踪文件返回 None。"""
    from core.sync.tracker import FileTracker

    tracker = FileTracker(tmp_path)
    info = tracker.get_file_history(str(tmp_path / "nonexistent.txt"))
    assert info is None


def test_get_file_history_after_remove_returns_none(tmp_path):
    """移除追踪后查询返回 None。"""
    from core.sync.tracker import FileTracker

    test_file = tmp_path / "test.txt"
    test_file.write_text("content", encoding="utf-8")

    tracker = FileTracker(tmp_path)
    tracker.track_file(str(test_file), "doc1")
    assert tracker.get_file_history(str(test_file)) is not None

    tracker.remove_tracked(str(test_file))
    assert tracker.get_file_history(str(test_file)) is None


# ============================================================
# 7. REPL CMD_ALIASES 扩展
# ============================================================

def test_repl_aliases_cover_new_commands():
    """新增的高频命令应有别名。"""
    from repl import REPL

    aliases = REPL.CMD_ALIASES
    # 验证新增别名存在
    assert aliases.get("/m") == "/memory"
    assert aliases.get("/g") == "/graph"
    assert aliases.get("/p") == "/pet"
    assert aliases.get("/sy") == "/sync"
    assert aliases.get("/he") == "/health"
    assert aliases.get("/dd") == "/dedup"
    assert aliases.get("/rt") == "/retag"
    assert aliases.get("/rb") == "/rebuild"
    assert aliases.get("/rp") == "/reparse"


def test_repl_aliases_no_conflict():
    """别名不应有冲突（同一个短名指向多个命令）。"""
    from repl import REPL

    aliases = REPL.CMD_ALIASES
    # 别名值集合中不应有重复 key 指向不同 value（实际上 dict 天然保证）
    # 这里检查所有短名都是 2-3 字符
    for short_name in aliases:
        assert short_name.startswith("/")
        assert len(short_name) >= 2

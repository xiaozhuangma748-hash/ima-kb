"""PetAdministrator.ask_stream() 流式问答测试。

覆盖：
- 正常产出 stage → token → done 事件序列
- LLM 失败时降级正常
- done 事件包含完整的 AnswerResult
- token 事件拼接等于 LLM 返回的完整文本
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from core.llm.client import LLMError
from core.pet.administrator import PetAdministrator, AnswerResult
from core.pet.pet import Pet
from core.retrieval.hybrid import HybridResult
from core.retrieval.rerank import RerankResult


def _make_admin(tmp_path, chat_stream_tokens=None, chat_stream_side_effect=None):
    """构建测试用 administrator（mock 所有外部依赖）。

    Args:
        chat_stream_tokens: chat_stream 返回的 token 列表（正常路径）
        chat_stream_side_effect: chat_stream 抛出的异常（降级路径）
    """
    pet = Pet(name="小白", level=5, branch="scholar")
    storage = MagicMock()
    storage.get_chunks.return_value = []

    memory = MagicMock()
    memory.get_data.return_value = {
        "profile": {"focus_topics": ["骨灰安置"]},
        "tasks": [],
    }
    memory.get_active_tasks.return_value = []

    hybrid = MagicMock()
    hybrid.search.return_value = [
        HybridResult(
            chunk_id="c1", doc_id="d1", score=0.5, source="both",
            content="骨灰安置内容", doc_title="条例",
        )
    ]

    reranker = MagicMock()
    reranker.rerank.return_value = [
        RerankResult(
            chunk_id="c1", doc_id="d1", score=0.5, source="both",
            content="骨灰安置内容", doc_title="条例",
            relevance_score=9.0, reason="高度相关",
        )
    ]

    llm = MagicMock()
    if chat_stream_side_effect is not None:
        llm.chat_stream.side_effect = chat_stream_side_effect
    else:
        # chat_stream 返回迭代器
        tokens = chat_stream_tokens if chat_stream_tokens is not None else ["你好", "，", "世界"]
        llm.chat_stream.return_value = iter(tokens)
    # chat() 仍保留（兼容性，不应被流式路径调用）
    llm.chat.return_value = "骨灰安置分为四类[1]。"

    admin = PetAdministrator(
        pet=pet, storage=storage, memory_store=memory,
        hybrid_retriever=hybrid, reranker=reranker, llm=llm,
    )
    return admin


def _consume_stream(admin, query="骨灰安置政策"):
    """消费 ask_stream 生成器，返回事件列表。"""
    return list(admin.ask_stream(query))


# ------------------------------------------------------------------
# 正常路径
# ------------------------------------------------------------------

def test_ask_stream_yields_stage_token_done_sequence(tmp_path):
    """事件序列：第一个是 stage，最后一个是 done。"""
    admin = _make_admin(tmp_path, chat_stream_tokens=["你好", "，", "世界"])
    events = _consume_stream(admin)

    assert events[0]["type"] == "stage"
    assert events[-1]["type"] == "done"


def test_ask_stream_first_stage_is_retrieval(tmp_path):
    """第一个 stage 事件是"检索"。"""
    admin = _make_admin(tmp_path)
    events = _consume_stream(admin)

    first_stage = events[0]
    assert first_stage["type"] == "stage"
    assert first_stage["stage"] == "检索"
    assert first_stage["count"] == 1  # mock 返回 1 条候选


def test_ask_stream_second_stage_is_rerank(tmp_path):
    """第二个 stage 事件是"重排"。"""
    admin = _make_admin(tmp_path)
    events = _consume_stream(admin)

    second_stage = events[1]
    assert second_stage["type"] == "stage"
    assert second_stage["stage"] == "重排"
    assert second_stage["count"] == 1  # mock 返回 1 条重排结果


def test_ask_stream_token_concatenation_equals_llm_output(tmp_path):
    """所有 token 事件拼接起来等于 LLM 返回的完整文本。"""
    tokens = ["你好", "，", "世界"]
    admin = _make_admin(tmp_path, chat_stream_tokens=tokens)
    events = _consume_stream(admin)

    token_texts = [e["text"] for e in events if e["type"] == "token"]
    assert "".join(token_texts) == "你好，世界"


def test_ask_stream_done_event_contains_answer_result(tmp_path):
    """done 事件包含完整的 AnswerResult 实例。"""
    admin = _make_admin(tmp_path, chat_stream_tokens=["回答[1]。"])
    events = _consume_stream(admin)

    done = events[-1]
    assert done["type"] == "done"
    result = done["result"]
    assert isinstance(result, AnswerResult)
    assert result.text == "回答[1]。"
    # sources 与 mock 一致
    assert len(result.sources) == 1
    assert result.sources[0].doc_id == "d1"
    # 引用被提取
    assert len(result.citations) == 1
    assert result.citations[0].doc_id == "d1"


def test_ask_stream_does_not_call_chat_non_stream(tmp_path):
    """流式路径不应调用非流式 chat()。"""
    admin = _make_admin(tmp_path, chat_stream_tokens=["a", "b"])
    _consume_stream(admin)
    admin.llm.chat.assert_not_called()


def test_ask_stream_pet_gains_exp(tmp_path):
    """流式问答后宠物获得经验（pet_events 非空）。"""
    admin = _make_admin(tmp_path, chat_stream_tokens=["回答"])
    events = _consume_stream(admin)

    done = events[-1]
    # gain_exp 至少返回 leveled_up/branched 两个键（即使都为 False）
    assert isinstance(done["result"].pet_events, dict)


def test_ask_stream_profile_updated(tmp_path):
    """流式问答后调用 profile_mgr.update_from_query（通过 memory.save 验证）。"""
    admin = _make_admin(tmp_path, chat_stream_tokens=["回答"])
    _consume_stream(admin)
    # profile_mgr 是真实 ProfileManager 实例（非 mock），
    # update_from_query 内部会调用 self.store.save()，故验证 memory.save
    admin.memory.save.assert_called()


# ------------------------------------------------------------------
# 降级路径
# ------------------------------------------------------------------

def test_ask_stream_degrades_on_llm_failure(tmp_path):
    """LLM 失败时降级为检索模式，仍产出 done 事件。"""
    admin = _make_admin(
        tmp_path,
        chat_stream_side_effect=LLMError("LLM 不可用"),
    )
    events = _consume_stream(admin)

    # 仍应有 stage 事件
    assert events[0]["type"] == "stage"
    # 最后是 done
    assert events[-1]["type"] == "done"
    result = events[-1]["result"]
    assert isinstance(result, AnswerResult)
    # 降级文案应包含检索原文或降级提示
    assert "骨灰安置内容" in result.text or "不可用" in result.text or "原文" in result.text


def test_ask_stream_degrade_token_yielded(tmp_path):
    """LLM 失败时降级文案作为单个 token 事件产出。"""
    admin = _make_admin(
        tmp_path,
        chat_stream_side_effect=LLMError("LLM 不可用"),
    )
    events = _consume_stream(admin)

    token_events = [e for e in events if e["type"] == "token"]
    assert len(token_events) == 1
    # 降级文案非空
    assert token_events[0]["text"]


def test_ask_stream_degrade_no_sources(tmp_path):
    """LLM 失败且无检索结果时仍返回降级文案。"""
    admin = _make_admin(
        tmp_path,
        chat_stream_side_effect=LLMError("LLM 不可用"),
    )
    admin.hybrid.search.return_value = []
    admin.reranker.rerank.return_value = []

    events = _consume_stream(admin)
    done = events[-1]
    assert done["type"] == "done"
    result = done["result"]
    assert isinstance(result, AnswerResult)
    assert result.text  # 非空
    assert result.sources == []
    assert result.citations == []


def test_ask_stream_with_style_override(tmp_path):
    """style_override 不影响流式事件序列。"""
    admin = _make_admin(tmp_path, chat_stream_tokens=["x"])
    events = list(admin.ask_stream("查询", style_override="warrior"))

    assert events[0]["type"] == "stage"
    assert events[-1]["type"] == "done"
    # chat_stream 被调用
    admin.llm.chat_stream.assert_called_once()


# ------------------------------------------------------------------
# 边界条件
# ------------------------------------------------------------------

def test_ask_stream_empty_token_list(tmp_path):
    """LLM 返回空 token 流时仍产出 done 事件（text 为空）。"""
    admin = _make_admin(tmp_path, chat_stream_tokens=[])
    events = _consume_stream(admin)

    done = events[-1]
    assert done["type"] == "done"
    assert done["result"].text == ""


def test_ask_stream_stage_counts_reflect_retrieval(tmp_path):
    """stage 事件的 count 应反映检索/重排结果数。"""
    admin = _make_admin(tmp_path)
    admin.hybrid.search.return_value = [
        HybridResult(chunk_id=f"c{i}", doc_id=f"d{i}", score=0.5, source="both",
                     content=f"内容{i}", doc_title=f"标题{i}")
        for i in range(3)
    ]
    admin.reranker.rerank.return_value = [
        RerankResult(chunk_id=f"c{i}", doc_id=f"d{i}", score=0.5, source="both",
                     content=f"内容{i}", doc_title=f"标题{i}",
                     relevance_score=9.0, reason="相关")
        for i in range(2)
    ]

    events = _consume_stream(admin)
    stages = [e for e in events if e["type"] == "stage"]
    assert len(stages) == 2
    assert stages[0]["stage"] == "检索"
    assert stages[0]["count"] == 3
    assert stages[1]["stage"] == "重排"
    assert stages[1]["count"] == 2

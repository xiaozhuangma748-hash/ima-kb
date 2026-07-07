"""编排层测试。"""
import pytest
from unittest.mock import MagicMock, patch
from core.pet.administrator import PetAdministrator, AnswerResult
from core.pet.pet import Pet
from core.retrieval.hybrid import HybridResult
from core.retrieval.rerank import RerankResult
from core.llm.client import LLMError


def _make_admin(tmp_path):
    """构建测试用 administrator（mock 所有外部依赖）。"""
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
        HybridResult(chunk_id="c1", doc_id="d1", score=0.5, source="both", content="骨灰安置内容", doc_title="条例")
    ]

    reranker = MagicMock()
    reranker.rerank.return_value = [
        RerankResult(
            chunk_id="c1", doc_id="d1", score=0.5, source="both",
            content="骨灰安置内容", doc_title="条例",
            relevance_score=9.0, reason="高度相关"
        )
    ]

    llm = MagicMock()
    llm.chat.return_value = "骨灰安置分为四类[1]。"

    admin = PetAdministrator(
        pet=pet, storage=storage, memory_store=memory,
        hybrid_retriever=hybrid, reranker=reranker, llm=llm,
    )
    return admin


def test_ask_returns_answer_result(tmp_path):
    """ask 返回 AnswerResult。"""
    admin = _make_admin(tmp_path)
    result = admin.ask("骨灰安置政策")
    assert isinstance(result, AnswerResult)
    assert result.text == "骨灰安置分为四类[1]。"
    assert len(result.citations) >= 1
    assert result.citations[0].doc_id == "d1"


def test_ask_increments_pet_exp(tmp_path):
    """ask 后宠物获得经验。"""
    admin = _make_admin(tmp_path)
    initial_exp = admin.pet.exp
    admin.ask("查询")
    assert admin.pet.exp > initial_exp


def test_ask_updates_memory(tmp_path):
    """ask 后更新记忆。"""
    admin = _make_admin(tmp_path)
    admin.ask("骨灰安置")
    # memory.update_from_query 被调用（通过 profile manager）
    admin.memory.get_data.assert_called()


def test_ask_with_style_override(tmp_path):
    """style_override 临时覆盖风格。"""
    admin = _make_admin(tmp_path)
    admin.ask("查询", style_override="warrior")
    # 验证 LLM 被调用
    admin.llm.chat.assert_called()


def test_ask_degradation_llm_failure(tmp_path):
    """LLM 失败时返回原文片段。"""
    admin = _make_admin(tmp_path)
    admin.llm.chat.side_effect = LLMError("LLM 不可用")
    result = admin.ask("查询")
    assert "原文" in result.text or "不可用" in result.text or "骨灰安置内容" in result.text


def test_ask_degradation_no_sources(tmp_path):
    """无检索结果时仍返回回答。"""
    admin = _make_admin(tmp_path)
    admin.hybrid.search.return_value = []
    admin.reranker.rerank.return_value = []
    result = admin.ask("查询")
    assert result.text  # 非空


def test_ask_citation_extraction(tmp_path):
    """回答中的 [1] 被提取为引用。"""
    admin = _make_admin(tmp_path)
    admin.llm.chat.return_value = "回答[1]内容[2]。"
    # 添加第二个 source
    admin.reranker.rerank.return_value = [
        RerankResult(chunk_id="c1", doc_id="d1", score=0.5, source="both",
                     content="内容1", doc_title="标题1", relevance_score=9, reason=""),
        RerankResult(chunk_id="c2", doc_id="d2", score=0.4, source="bm25",
                     content="内容2", doc_title="标题2", relevance_score=7, reason=""),
    ]
    result = admin.ask("查询")
    assert len(result.citations) == 2
    assert result.citations[0].doc_id == "d1"
    assert result.citations[1].doc_id == "d2"

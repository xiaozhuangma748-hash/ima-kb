"""端到端流程测试。"""
import pytest
from unittest.mock import MagicMock, patch
from core.pet.administrator import PetAdministrator, AnswerResult
from core.pet.pet import Pet
from core.pet.storage import PetStorage
from core.memory.store import MemoryStore
from core.retrieval.hybrid import HybridResult
from core.retrieval.rerank import RerankResult
from core.llm.client import LLMError


def _build_admin(tmp_path):
    """构建完整 admin（mock LLM 和向量）。"""
    pet = Pet(name="小白", level=5, branch="scholar")
    storage = MagicMock()
    storage.get_chunks.return_value = []

    memory = MemoryStore(storage_path=tmp_path)

    hybrid = MagicMock()
    hybrid.search.return_value = [
        HybridResult(chunk_id="c1", doc_id="d1", score=0.5, source="both",
                     content="骨灰安置分为四类", doc_title="殡葬条例")
    ]

    reranker = MagicMock()
    reranker.rerank.return_value = [
        RerankResult(chunk_id="c1", doc_id="d1", score=0.5, source="both",
                     content="骨灰安置分为四类", doc_title="殡葬条例",
                     relevance_score=9.0, reason="高度相关")
    ]

    llm = MagicMock()
    llm.chat.return_value = "骨灰安置分为四类[1]。"

    admin = PetAdministrator(
        pet=pet, storage=storage, memory_store=memory,
        hybrid_retriever=hybrid, reranker=reranker, llm=llm,
    )
    return admin


def test_full_ask_flow(tmp_path):
    """完整问答流程：检索 → 重排 → 生成 → 引用 → 记忆更新。"""
    admin = _build_admin(tmp_path)
    result = admin.ask("骨灰安置政策")

    assert result.text
    assert len(result.citations) >= 1
    assert result.citations[0].doc_id == "d1"
    assert result.pet_events  # 宠物事件

    # 验证记忆更新
    profile = admin.profile_mgr.get_profile()
    assert "骨灰安置" in profile.focus_topics


def test_degradation_llm_failure(tmp_path):
    """LLM 失败时返回原文片段。"""
    admin = _build_admin(tmp_path)
    admin.llm.chat.side_effect = LLMError("LLM 不可用")
    result = admin.ask("骨灰安置")
    assert "原文" in result.text or "不可用" in result.text or "骨灰安置" in result.text


def test_persona_style_affects_prompt(tmp_path):
    """不同人格调用 LLM 时 prompt 不同。"""
    admin = _build_admin(tmp_path)
    admin.ask("骨灰安置", style_override="scholar")
    scholar_prompt = admin.llm.chat.call_args.kwargs["messages"][0]["content"]

    admin.llm.chat.reset_mock()
    admin.ask("骨灰安置", style_override="warrior")
    warrior_prompt = admin.llm.chat.call_args.kwargs["messages"][0]["content"]

    assert scholar_prompt != warrior_prompt
    assert "scholar" in scholar_prompt.lower() or "学者" in scholar_prompt
    assert "warrior" in warrior_prompt.lower() or "战士" in warrior_prompt


def test_memory_persistence_across_sessions(tmp_path):
    """记忆跨会话持久化。"""
    admin = _build_admin(tmp_path)
    admin.ask("杭州骨灰安置")
    admin.memory.save()

    # 新建 admin 实例模拟重启
    memory2 = MemoryStore(storage_path=tmp_path)
    profile2 = memory2.get_data()["profile"]
    assert "杭州" in profile2.get("focus_regions", [])


def test_pet_gains_exp_on_ask(tmp_path):
    """宠物通过 ask 获得经验。"""
    admin = _build_admin(tmp_path)
    initial_exp = admin.pet.exp
    admin.ask("查询")
    assert admin.pet.exp > initial_exp

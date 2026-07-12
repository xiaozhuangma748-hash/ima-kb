"""宠物知识库管理员：编排检索 + 记忆 + 人格 + LLM。"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import List, Optional, Dict

from core.pet.pet import Pet
from core.storage import Storage
from core.memory.store import MemoryStore
from core.memory.profile import ProfileManager
from core.memory.tasks import TaskManager
from core.memory.workflow import WorkflowTracker
from core.retrieval.hybrid import HybridRetriever, HybridResult
from core.retrieval.rerank import Reranker, RerankResult
from core.retrieval.citation import Citation, extract_citations
from core.persona.prompts import build_system_prompt
from core.llm.client import LLMClient, LLMError
from core.llm.degrade import get_llm_degrade_message

logger = logging.getLogger(__name__)


# 经验值表
EXP_TABLE = {
    "qa": 10,
    "ingest": 30,
    "analyze": 15,
    "agent": 15,
    "report": 20,
    "read": 10,
    "compare": 10,
    "smart": 8,
    "graph_build": 30,
}


@dataclass
class AnswerResult:
    """问答结果。"""
    text: str
    citations: List[Citation] = field(default_factory=list)
    sources: List[RerankResult] = field(default_factory=list)
    pet_events: dict = field(default_factory=dict)
    related_tasks: Optional[List] = None


class PetAdministrator:
    """宠物知识库管理员。"""

    def __init__(
        self,
        pet: Pet,
        storage: Storage,
        memory_store: MemoryStore,
        hybrid_retriever: HybridRetriever,
        reranker: Reranker,
        llm: LLMClient,
    ) -> None:
        self.pet = pet
        self.storage = storage
        self.memory = memory_store
        self.hybrid = hybrid_retriever
        self.reranker = reranker
        self.llm = llm
        self.profile_mgr = ProfileManager(memory_store)
        self.task_mgr = TaskManager(memory_store)
        self.workflow = WorkflowTracker(memory_store)

    def ask(self, query: str, style_override: Optional[str] = None,
            history: Optional[List[Dict]] = None,
            summary: Optional[str] = None,
            cross_session_context: Optional[str] = None) -> AnswerResult:
        """主入口：用户提问 → 带引用的回答。

        Args:
            query: 用户问题
            style_override: 临时覆盖人格风格
            history: 多轮对话历史（[{role, content}, ...]），最多取最近 10 条
            summary: 早期对话的摘要（压缩长期记忆）
            cross_session_context: 跨会话记忆上下文
        """
        # 1. 加载记忆
        profile = self.profile_mgr.get_profile()
        active_tasks = self.task_mgr.get_active_tasks()

        # 2. 混合检索
        candidates = self.hybrid.search(query, top_k=15)

        # 3. LLM 重排
        top_sources = self.reranker.rerank(query, candidates, top_n=5)

        # 4. 确定风格
        if style_override:
            style = style_override
        elif profile.preferred_style and profile.preferred_style != "auto":
            style = profile.preferred_style
        elif self.pet.branch:
            style = self.pet.branch
        else:
            style = "neutral"

        # 5. 组装 system prompt
        # sources_dict 同时为 build_system_prompt（用 content）和 extract_citations（用 snippet）提供数据
        # paragraph_num 来自 enrich_hybrid_results 填充的真实 chunk 段落号
        sources_dict = [
            {
                "doc_id": s.doc_id,
                "title": s.doc_title,
                "paragraph_num": s.paragraph_num or (i + 1),  # 真实段落号，回退到序号
                "content": s.content,
                "snippet": s.content,
            }
            for i, s in enumerate(top_sources)
        ]
        profile_dict = {
            "preferred_format": profile.preferred_format,
            "focus_topics": profile.focus_topics,
            "focus_regions": profile.focus_regions,
        }
        tasks_dict = [
            {"description": t.description, "status": t.status}
            for t in active_tasks
        ]
        system_prompt = build_system_prompt(
            style=style,
            pet=self.pet,
            profile=profile_dict,
            tasks=tasks_dict,
            sources=sources_dict,
        )

        # 6. LLM 生成（带多轮历史 + 早期摘要）
        # 取最近 10 条历史（5 轮对话），避免 token 超限
        recent_history = (history or [])[-10:]
        messages = [{"role": "system", "content": system_prompt}]
        if cross_session_context:
            messages.append({"role": "system", "content": f"## 跨会话记忆\n{cross_session_context}"})
        if summary:
            messages.append({"role": "system", "content": f"## 之前的对话摘要\n{summary}"})
        messages.extend(recent_history)
        messages.append({"role": "user", "content": query})
        try:
            answer_text = self.llm.chat(
                messages=messages,
                temperature=0.3,
                max_tokens=1024,
            )
        except LLMError as e:
            logger.warning(f"LLM 生成失败，降级为检索模式: {e}")
            # 降级：用统一文案 + 检索到的原文片段
            if top_sources:
                answer_text = get_llm_degrade_message(
                    error=e, has_sources=True, source_count=len(top_sources),
                ) + "\n\n"
                for i, s in enumerate(top_sources, 1):
                    answer_text += f"[{i}] {s.doc_title}\n{s.content[:200]}\n\n"
            else:
                answer_text = get_llm_degrade_message(error=e, has_sources=False)

        # 7. 提取引用
        try:
            citations = extract_citations(answer_text, sources_dict)
        except Exception as e:
            logger.warning(f"引用提取失败: {e}")
            citations = []

        # 8. 更新记忆（静默，失败不影响回答）
        try:
            self.profile_mgr.update_from_query(query, answer_text)
        except Exception as e:
            logger.warning(f"记忆更新失败: {e}")

        # 9. 宠物获得经验
        events = {}
        try:
            events = self.pet.gain_exp(EXP_TABLE.get("qa", 10), "qa")
        except Exception as e:
            logger.warning(f"宠物经验更新失败: {e}")

        return AnswerResult(
            text=answer_text,
            citations=citations,
            sources=top_sources,
            pet_events=events,
            related_tasks=active_tasks if active_tasks else None,
        )

    def ask_stream(self, query: str, style_override: Optional[str] = None,
                   history: Optional[List[Dict]] = None,
                   summary: Optional[str] = None,
                   cross_session_context: Optional[str] = None):
        """流式问答生成器。yield 事件 dict:
        - {"type": "stage", "stage": "检索", "count": N}
        - {"type": "stage", "stage": "重排", "count": N}
        - {"type": "token", "text": "..."}  — LLM 逐 token
        - {"type": "done", "result": AnswerResult}  — 最终结果

        步骤 1-5 与 ask() 完全一致；步骤 6 改用 chat_stream()；
        步骤 7-9（引用提取 / 记忆更新 / 宠物经验）在流式结束后执行。
        """
        # 1. 加载记忆
        profile = self.profile_mgr.get_profile()
        active_tasks = self.task_mgr.get_active_tasks()

        # 2. 混合检索
        candidates = self.hybrid.search(query, top_k=15)
        yield {"type": "stage", "stage": "检索", "count": len(candidates)}

        # 3. LLM 重排
        top_sources = self.reranker.rerank(query, candidates, top_n=5)
        yield {"type": "stage", "stage": "重排", "count": len(top_sources)}

        # 4. 确定风格
        if style_override:
            style = style_override
        elif profile.preferred_style and profile.preferred_style != "auto":
            style = profile.preferred_style
        elif self.pet.branch:
            style = self.pet.branch
        else:
            style = "neutral"

        # 5. 组装 system prompt
        # sources_dict 同时为 build_system_prompt（用 content）和 extract_citations（用 snippet）提供数据
        # paragraph_num 来自 enrich_hybrid_results 填充的真实 chunk 段落号
        sources_dict = [
            {
                "doc_id": s.doc_id,
                "title": s.doc_title,
                "paragraph_num": s.paragraph_num or (i + 1),  # 真实段落号，回退到序号
                "content": s.content,
                "snippet": s.content,
            }
            for i, s in enumerate(top_sources)
        ]
        profile_dict = {
            "preferred_format": profile.preferred_format,
            "focus_topics": profile.focus_topics,
            "focus_regions": profile.focus_regions,
        }
        tasks_dict = [
            {"description": t.description, "status": t.status}
            for t in active_tasks
        ]
        system_prompt = build_system_prompt(
            style=style,
            pet=self.pet,
            profile=profile_dict,
            tasks=tasks_dict,
            sources=sources_dict,
        )

        # 6. LLM 流式生成（带多轮历史 + 早期摘要，chat_stream 不支持重试，首帧失败直接降级）
        # 取最近 10 条历史（5 轮对话），避免 token 超限
        recent_history = (history or [])[-10:]
        messages = [{"role": "system", "content": system_prompt}]
        if cross_session_context:
            messages.append({"role": "system", "content": f"## 跨会话记忆\n{cross_session_context}"})
        if summary:
            messages.append({"role": "system", "content": f"## 之前的对话摘要\n{summary}"})
        messages.extend(recent_history)
        messages.append({"role": "user", "content": query})
        answer_text = ""
        try:
            for token in self.llm.chat_stream(
                messages=messages,
                temperature=0.3,
                max_tokens=1024,
            ):
                answer_text += token
                yield {"type": "token", "text": token}
        except LLMError as e:
            logger.warning(f"LLM 流式生成失败，降级为检索模式: {e}")
            # 降级：用统一文案 + 检索到的原文片段（与 ask() 保持一致）
            if top_sources:
                answer_text = get_llm_degrade_message(
                    error=e, has_sources=True, source_count=len(top_sources),
                ) + "\n\n"
                for i, s in enumerate(top_sources, 1):
                    answer_text += f"[{i}] {s.doc_title}\n{s.content[:200]}\n\n"
            else:
                answer_text = get_llm_degrade_message(error=e, has_sources=False)
            yield {"type": "token", "text": answer_text}

        # 7. 提取引用
        try:
            citations = extract_citations(answer_text, sources_dict)
        except Exception as e:
            logger.warning(f"引用提取失败: {e}")
            citations = []

        # 8. 更新记忆（静默，失败不影响回答）
        try:
            self.profile_mgr.update_from_query(query, answer_text)
        except Exception as e:
            logger.warning(f"记忆更新失败: {e}")

        # 9. 宠物获得经验
        events = {}
        try:
            events = self.pet.gain_exp(EXP_TABLE.get("qa", 10), "qa")
        except Exception as e:
            logger.warning(f"宠物经验更新失败: {e}")

        yield {
            "type": "done",
            "result": AnswerResult(
                text=answer_text,
                citations=citations,
                sources=top_sources,
                pet_events=events,
                related_tasks=active_tasks if active_tasks else None,
            ),
        }

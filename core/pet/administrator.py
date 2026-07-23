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
from core.retrieval.router import route_query, should_skip_retrieval
from core.retrieval.semantic_cache import SemanticCache
from core.retrieval.hybrid import HybridRetriever, HybridResult
from core.retrieval.rerank import Reranker, RerankResult
from core.retrieval.citation import Citation, extract_citations
from core.persona.prompts import build_system_prompt
from core.llm.client import LLMClient, LLMError
from core.llm.degrade import get_llm_degrade_message
from core.todo.manager import TodoManager
from config import settings

logger = logging.getLogger(__name__)


def _sanitize_latex(text: str) -> str:
    """清理 LaTeX 数学公式语法（与 core.cli.chat.ChatMixin._sanitize_latex 保持一致）。"""
    import re
    text = re.sub(r"\$\$(.*?)\$\$", r"\1", text, flags=re.DOTALL)
    text = re.sub(r"\$(.*?)\$", r"\1", text, flags=re.DOTALL)
    replacements = {
        r"\times": "×",
        r"\div": "÷",
        r"\approx": "≈",
        r"\leq": "≤",
        r"\le": "≤",
        r"\geq": "≥",
        r"\ge": "≥",
        r"\neq": "≠",
        r"\equiv": "≡",
        r"\pm": "±",
        r"\cdot": "·",
    }
    for latex, char in replacements.items():
        text = text.replace(latex, char)
    text = re.sub(r"\\mathbf\{(.*?)\}", r"\1", text, flags=re.DOTALL)
    text = re.sub(r"\\text\{(.*?)\}", r"\1", text, flags=re.DOTALL)
    text = text.replace("\\\\", "\n")
    return text.replace("  ", " ")


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
        todo_manager: Optional[TodoManager] = None,
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
        # 每日待办管理器（可选，未传入时忽略）
        self.todo_mgr = todo_manager
        # 答案级语义缓存（与检索层 hybrid.cache 互补：这里缓存完整 LLM 答案）
        self._answer_cache = SemanticCache(threshold=0.92, ttl=1800, max_size=200)

    def _expand_query_with_context(
        self,
        query: str,
        summary: Optional[str] = None,
        history: Optional[List[Dict]] = None,
    ) -> str:
        """历史感知的查询扩展：用会话摘要补全当前问题的隐含上下文。

        策略：
        - 如果有 summary 且 query 较短（<=15 字），把摘要前 80 字附加到 query
          （短问题往往省略主语，需要摘要补全主题）
        - 如果有最近一轮 assistant 回答，提取其前 60 字作为上下文
        - 不修改原 query 的关键词，只附加上下文（避免污染 BM25）

        Args:
            query: 用户当前问题
            summary: 早期对话摘要
            history: 最近对话历史

        Returns:
            扩展后的 query（可能等于原 query）
        """
        try:
            if not settings.history_aware_retrieval:
                return query
            # 提取最近一轮 assistant 回答作为即时上下文
            last_assistant_snippet = ""
            if history:
                for msg in reversed(history):
                    if msg.get("role") == "assistant":
                        last_assistant_snippet = (msg.get("content") or "")[:60]
                        break
            # 主题摘要（取前 80 字，避免 query 过长）
            summary_snippet = ""
            if summary:
                summary_snippet = summary.strip().replace("\n", " ")[:80]
            # 只对短查询做扩展（长查询本身已包含足够上下文）
            if len(query.strip()) > 15:
                return query
            parts = [query]
            if summary_snippet:
                parts.append(f"（话题：{summary_snippet}）")
            elif last_assistant_snippet:
                parts.append(f"（上文：{last_assistant_snippet}）")
            return " ".join(parts) if len(parts) > 1 else query
        except Exception:
            return query

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
        # 加载今日待办（失败静默，不影响问答）
        today_todos = []
        if self.todo_mgr is not None:
            try:
                today_todos = self.todo_mgr.list_day()
            except Exception as e:
                logger.warning(f"加载今日待办失败: {e}")

        # 2. 混合检索（历史感知：用 summary 扩展 query，提升多轮对话召回率）
        search_query = self._expand_query_with_context(query, summary=summary, history=history)
        candidates = self.hybrid.search(search_query, top_k=10)

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
            todos=today_todos,
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

        # 7. 提取引用（提取前先清理越界 [n] 标记，确保正文与引用列表一致）
        from core.retrieval.citation import sanitize_outbound_citations
        answer_text = sanitize_outbound_citations(answer_text, len(top_sources))
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
                   cross_session_context: Optional[str] = None,
                   max_tokens: int = 1024,
                   extra_system_prompt: Optional[str] = None):
        """流式问答生成器。yield 事件 dict:
        - {"type": "stage", "stage": "检索", "count": N}
        - {"type": "stage", "stage": "重排", "count": N}
        - {"type": "token", "text": "..."}  — LLM 逐 token
        - {"type": "done", "result": AnswerResult}  — 最终结果

        步骤 1-5 与 ask() 完全一致；步骤 6 改用 chat_stream()；
        步骤 7-9（引用提取 / 记忆更新 / 宠物经验）在流式结束后执行。
        """
        # 0. 答案级语义缓存查询（命中则直接流式返回缓存的答案）
        query_type = route_query(query)
        if query_type == "knowledge":
            try:
                query_emb = None
                if self.hybrid.vector.is_available():
                    query_emb = self.hybrid.vector.embed_query(query)
                if query_emb is not None:
                    cached = self._answer_cache.get(query, query_emb)
                    if cached is not None and cached.answer:
                        logger.info(f"答案缓存命中，跳过检索+LLM: {query[:30]}...")
                        # 清理缓存中可能遗留的 LaTeX 公式
                        clean_answer = _sanitize_latex(cached.answer)
                        yield {"type": "stage", "stage": "缓存", "count": 1}
                        # 逐 token 回放缓存答案
                        import re as _re
                        for token in _re.findall(r'\S+|\s+', clean_answer):
                            yield {"type": "token", "text": token}
                        yield {
                            "type": "done",
                            "result": AnswerResult(
                                text=clean_answer,
                                citations=[],
                                sources=[],
                                pet_events={},
                            ),
                        }
                        return
            except Exception as e:
                logger.warning(f"答案缓存查询失败，继续正常流程: {e}")

        # 1. 加载记忆
        profile = self.profile_mgr.get_profile()
        active_tasks = self.task_mgr.get_active_tasks()
        # 加载今日待办（失败静默，不影响问答）
        today_todos = []
        if self.todo_mgr is not None:
            try:
                today_todos = self.todo_mgr.list_day()
            except Exception as e:
                logger.warning(f"加载今日待办失败: {e}")

        # 2. 混合检索（闲聊跳过检索，直接空候选）
        if should_skip_retrieval(query):
            candidates = []
            yield {"type": "stage", "stage": "检索", "count": 0}
        else:
            # 历史感知：用 summary 扩展 query，提升多轮对话召回率
            search_query = self._expand_query_with_context(query, summary=summary, history=history)
            candidates = self.hybrid.search(search_query, top_k=10)
            yield {"type": "stage", "stage": "检索", "count": len(candidates)}

        # 3. LLM 重排（无候选时跳过）
        if candidates:
            top_sources = self.reranker.rerank(query, candidates, top_n=5)
        else:
            top_sources = []
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
            todos=today_todos,
        )

        # 6. LLM 流式生成（带多轮历史 + 早期摘要，chat_stream 不支持重试，首帧失败直接降级）
        # 取最近 10 条历史（5 轮对话），避免 token 超限
        recent_history = (history or [])[-10:]
        messages = [{"role": "system", "content": system_prompt}]
        if extra_system_prompt:
            messages.append({"role": "system", "content": extra_system_prompt})
        if cross_session_context:
            messages.append({"role": "system", "content": f"## 跨会话记忆\n{cross_session_context}"})
        if summary:
            messages.append({"role": "system", "content": f"## 之前的对话摘要\n{summary}"})
        messages.extend(recent_history)
        messages.append({"role": "user", "content": query})
        answer_text = ""
        # 通知 REPL 参考资料数量，用于流式实时清理越界 [n] 引用标记
        yield {"type": "source_count", "count": len(top_sources)}
        try:
            for token in self.llm.chat_stream(
                messages=messages,
                temperature=0.3,
                max_tokens=max_tokens,
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

        # 7. 提取引用（提取前先清理越界 [n] 标记，确保正文与引用列表一致）
        from core.retrieval.citation import sanitize_outbound_citations
        answer_text = sanitize_outbound_citations(answer_text, len(top_sources))
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

        # 10. 写入答案缓存（知识查询且有完整答案时）
        if query_type == "knowledge" and answer_text.strip():
            try:
                if query_emb is not None:
                    # 缓存前清理 LaTeX，保证缓存内容也是干净的
                    clean_answer_for_cache = _sanitize_latex(answer_text)
                    self._answer_cache.put(
                        query=query,
                        query_embedding=query_emb,
                        answer=clean_answer_for_cache,
                        citations=[c.__dict__ if hasattr(c, '__dict__') else c for c in citations],
                    )
            except Exception as e:
                logger.warning(f"答案缓存写入失败: {e}")

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

"""问答服务：组装 PetAdministrator + 检索 + 重排 + 记忆 + LLM。

CLI (run.py cli_ask) 和 Web (web/routes/qa.py) 共用此服务，
消除两处各自手动组装 PetAdministrator 的重复代码。
"""
from __future__ import annotations

import logging
from typing import Optional, List, Dict, Any

from config import settings
from core.storage import Storage
from core.pet.administrator import PetAdministrator
from core.pet.storage import PetStorage
from core.memory.store import MemoryStore
from core.retrieval.hybrid import HybridRetriever
from core.retrieval.vector import VectorIndex
from core.retrieval.rerank import Reranker, create_reranker
from core.llm.client import LLMClient, get_llm
from core.todo.manager import TodoManager

logger = logging.getLogger(__name__)


class QAService:
    """问答编排服务。

    封装 PetAdministrator 的组装逻辑，提供同步问答和流式问答两种接口。
    支持传入外部组件（Web 共享实例）或自动创建（CLI 模式）。
    """

    def __init__(
        self,
        storage: Optional[Storage] = None,
        vector_index: Optional[VectorIndex] = None,
        llm: Optional[LLMClient] = None,
        memory_store: Optional[MemoryStore] = None,
        todo_manager: Optional[TodoManager] = None,
    ) -> None:
        """初始化问答服务。

        Args:
            storage: 存储实例（不传则自动创建）
            vector_index: 向量索引（不传则尝试自动创建，失败则降级纯 BM25）
            llm: LLM 客户端（不传则自动创建）
            memory_store: 记忆存储（不传则自动创建）
            todo_manager: 待办管理器（可选）
        """
        self.storage = storage or Storage()

        # 向量索引：传入则用，否则尝试创建
        self.vector_index = vector_index
        if self.vector_index is None:
            try:
                self.vector_index = VectorIndex()
            except Exception as e:
                logger.warning(f"向量索引初始化失败，降级纯 BM25: {e}")
                self.vector_index = None

        # 把向量索引挂到 storage，使降级路径（如 RAGChain）也能访问
        if self.vector_index is not None:
            try:
                self.storage.attach_vector_index(self.vector_index)
            except Exception as e:
                logger.warning(f"向量索引挂接失败: {e}")

        # LLM
        self.llm = llm or (get_llm() if settings.has_llm() else None)

        # 记忆
        self.memory_store = memory_store or MemoryStore()

        # 待办
        self.todo_manager = todo_manager

        # 宠物
        self.pet_storage = PetStorage()
        self.pet = self.pet_storage.load()

        # Reranker
        self.reranker = None
        if self.llm:
            try:
                self.reranker = create_reranker(llm=self.llm)
            except Exception as e:
                logger.warning(f"Reranker 初始化失败: {e}")

        # HybridRetriever
        self.hybrid = HybridRetriever(
            bm25_index=self.storage.bm25,
            vector_index=self.vector_index,
            storage=self.storage,
        )

        # PetAdministrator
        self.administrator: Optional[PetAdministrator] = None
        if self.pet and self.llm and self.reranker:
            self.administrator = PetAdministrator(
                pet=self.pet,
                storage=self.storage,
                memory_store=self.memory_store,
                hybrid_retriever=self.hybrid,
                reranker=self.reranker,
                llm=self.llm,
                todo_manager=self.todo_manager,
            )

    @property
    def is_ready(self) -> bool:
        """是否已就绪（宠物 + LLM + Reranker 均可用）。"""
        return self.administrator is not None

    @property
    def has_pet(self) -> bool:
        """宠物是否已领养。"""
        return self.pet is not None

    def ask(
        self,
        question: str,
        style_override: Optional[str] = None,
        history: Optional[List[Dict]] = None,
        summary: Optional[str] = None,
        cross_session_context: Optional[str] = None,
    ):
        """同步问答。

        Returns:
            AnswerResult
        """
        if not self.is_ready:
            raise RuntimeError("QAService 未就绪：请检查宠物领养状态和 LLM 配置")
        return self.administrator.ask(
            query=question,
            style_override=style_override,
            history=history,
            summary=summary,
            cross_session_context=cross_session_context,
        )

    def ask_stream(
        self,
        question: str,
        style_override: Optional[str] = None,
        history: Optional[List[Dict]] = None,
        summary: Optional[str] = None,
        cross_session_context: Optional[str] = None,
        max_tokens: int = 1024,
        extra_system_prompt: Optional[str] = None,
    ):
        """流式问答生成器。

        Yields:
            事件 dict，类型同 PetAdministrator.ask_stream()
        """
        if not self.is_ready:
            raise RuntimeError("QAService 未就绪：请检查宠物领养状态和 LLM 配置")
        yield from self.administrator.ask_stream(
            query=question,
            style_override=style_override,
            history=history,
            summary=summary,
            cross_session_context=cross_session_context,
            max_tokens=max_tokens,
            extra_system_prompt=extra_system_prompt,
        )

    def save_state(self) -> None:
        """保存宠物状态和记忆（问答后调用）。"""
        if self.pet and self.administrator:
            try:
                self.pet_storage.save(self.administrator.pet)
            except Exception as e:
                logger.warning(f"宠物状态保存失败: {e}")
        try:
            self.memory_store.save()
        except Exception as e:
            logger.warning(f"记忆保存失败: {e}")

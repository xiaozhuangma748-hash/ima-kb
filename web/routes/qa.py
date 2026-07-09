"""AI 问答 — SSE 流式路由。

GET /api/qa/stream?q=...&persona=...
  返回 text/event-stream，逐字推送 LLM 生成内容。
"""
from __future__ import annotations

import asyncio
import json
from typing import Optional

from fastapi import APIRouter, Query, HTTPException
from fastapi.responses import StreamingResponse

from config import settings
from core.storage import Storage
from core.llm.client import get_llm

router = APIRouter(tags=["qa"])


def _build_sse_event(event_type: str, data: dict) -> str:
    """构造 SSE 事件字符串。"""
    payload = json.dumps(data, ensure_ascii=False)
    return f"event: {event_type}\ndata: {payload}\n\n"


@router.get("/qa/stream")
async def qa_stream(
    q: str = Query(..., description="用户问题"),
    persona: str = Query("auto", description="人格: auto|scholar|warrior|artisan"),
):
    """SSE 流式问答。"""

    if not settings.has_llm():
        return StreamingResponse(
            _sse_error("LLM 未配置，请在 .env 中设置 AGNES_API_KEY"),
            media_type="text/event-stream",
        )

    async def _stream():
        """生成 SSE 事件流。"""
        try:
            from core.pet.administrator import PetAdministrator
            from core.pet.storage import PetStorage
            from core.memory.store import MemoryStore
            from core.retrieval.hybrid import HybridRetriever
            from core.retrieval.vector import VectorIndex
            from core.retrieval.rerank import Reranker

            storage = Storage()

            # 1. 混合检索
            try:
                vector_index = VectorIndex()
                hybrid = HybridRetriever(bm25_index=storage.bm25, vector_index=vector_index)
            except Exception:
                vector_index = None
                hybrid = HybridRetriever(bm25_index=storage.bm25, vector_index=None)

            retrieval_results = hybrid.search(q, top_k=6)

            # 回填检索结果中缺失的 content/doc_title（HybridResult 可能为空）
            for r in retrieval_results:
                if hasattr(r, "content") and not r.content:
                    doc_id = getattr(r, "doc_id", "")
                    if doc_id:
                        try:
                            chunks = storage.get_chunks(doc_id)
                            if chunks:
                                r.content = chunks[0].content or ""
                        except Exception:
                            pass
                if hasattr(r, "doc_title") and not r.doc_title:
                    doc_id = getattr(r, "doc_id", "")
                    if doc_id:
                        try:
                            doc = storage.get_document(doc_id)
                            if doc and doc.title:
                                r.doc_title = doc.title
                        except Exception:
                            pass

            # 2. LLM 重排序
            llm = get_llm()
            reranker = Reranker(llm)
            reranked = reranker.rerank(q, retrieval_results)

            # 3. 读取宠物/人格
            pet = None
            memory_store = None
            try:
                pet = PetStorage().load()
            except Exception:
                pass
            try:
                memory_store = MemoryStore()
            except Exception:
                pass

            # 4. 构建参考资料（content 为空时从 storage 回填）
            context_parts = []
            citations_data = []
            for i, r in enumerate(reranked[:6], 1):
                ctx = getattr(r, "content", "") or getattr(r, "text", "") or ""
                doc_title = getattr(r, "doc_title", "") or getattr(r, "title", "") or ""
                doc_id = getattr(r, "doc_id", "")

                # 回填空 content/doc_title
                if not ctx and doc_id:
                    try:
                        chunks = storage.get_chunks(doc_id)
                        if chunks:
                            ctx = chunks[0].content or ""
                    except Exception:
                        pass
                if not doc_title and doc_id:
                    try:
                        doc = storage.get_document(doc_id)
                        if doc and doc.title:
                            doc_title = doc.title
                    except Exception:
                        pass

                context_parts.append(f"[{i}] {ctx}")
                citations_data.append({
                    "marker": f"[{i}]",
                    "title": doc_title,
                    "snippet": ctx[:200],
                    "score": round(getattr(r, "score", 0), 2),
                })

            context_text = "\n\n".join(context_parts)

            # 5. 构建 system prompt（含人格）
            from core.persona.prompts import build_system_prompt

            style_map = {"auto": "neutral", "scholar": "scholar", "warrior": "warrior", "artisan": "artisan"}
            style = style_map.get(persona, "neutral")
            _pet = pet if pet else None
            _profile = {}
            _tasks = []
            _sources = context_parts

            try:
                system_prompt = build_system_prompt(
                    style=style,
                    pet=_pet,
                    profile=_profile,
                    tasks=_tasks,
                    sources=_sources,
                )
            except Exception:
                # fallback: 如果 build_system_prompt 调用失败，用通用提示
                system_prompt = "你是一个知识库助手，请根据提供的参考资料回答用户问题。引用时请标注来源编号。"

            user_prompt = f"参考资料:\n{context_text}\n\n问题: {q}\n\n请根据参考资料回答。使用 Markdown 格式，结构清晰。在回答末尾统一列出参考来源编号 [1]、[2] 等，不要在正文中夹杂引用标记。"

            # 6. 流式输出（chat_stream 直接 yield 字符串 token）
            full_text = ""
            for token in llm.chat_stream(
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                max_tokens=settings.llm_max_tokens,
            ):
                full_text += token
                yield _build_sse_event("token", {"text": token})

            # 6. 发送引用
            for c in citations_data:
                yield _build_sse_event("citation", c)

            # 7. 完成标记
            yield _build_sse_event("done", {"full_text": full_text})

            # 8. 更新记忆
            if memory_store and pet:
                try:
                    admin = PetAdministrator(
                        pet=pet, storage=storage, memory_store=memory_store,
                        hybrid_retriever=hybrid, reranker=reranker, llm=llm,
                    )
                    admin._update_memory(q, full_text)
                except Exception:
                    pass

        except Exception as e:
            yield _build_sse_event("error", {"message": str(e)})

    return StreamingResponse(
        _stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # nginx 不缓冲
        },
    )


def _sse_error(message: str):
    """返回 SSE 格式的错误流。"""
    async def _stream():
        yield _build_sse_event("error", {"message": message})
    return _stream()

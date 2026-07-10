"""AI 问答 — SSE 流式路由。

GET /api/qa/stream?q=...&persona=...
  返回 text/event-stream，逐字推送 LLM 生成内容。
"""
from __future__ import annotations

import asyncio
import json
from typing import Optional

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from config import settings
from core.storage import Storage
from core.llm.client import get_llm

router = APIRouter(tags=["qa"])


def _build_sse_event(event_type: str, data: dict) -> str:
    """构造 SSE 事件字符串。"""
    payload = json.dumps(data, ensure_ascii=False)
    return f"event: {event_type}\ndata: {payload}\n\n"


@router.post("/qa/stream")
async def qa_stream(request: Request):
    """SSE 流式问答。"""
    from core.pet.administrator import PetAdministrator
    from core.pet.storage import PetStorage
    from core.memory.store import MemoryStore
    from core.retrieval.hybrid import HybridRetriever
    from core.retrieval.vector import VectorIndex
    from core.retrieval.rerank import Reranker

    body = await request.json()
    question = body.get("question", "").strip()
    history = body.get("history", [])

    if not question:
        return {"error": "请输入问题"}

    # 初始化组件（复用 cli_ask 的模式）
    storage = Storage()
    pet_storage = PetStorage()
    pet = pet_storage.load()

    if not pet:
        return {"error": "请先领养宠物"}

    memory = MemoryStore()

    try:
        vector_index = VectorIndex()
    except Exception:
        vector_index = None

    hybrid = HybridRetriever(bm25_index=storage.bm25, vector_index=vector_index)
    llm = get_llm() if settings.has_llm() else None
    reranker = Reranker(llm) if llm else None

    if not llm or not reranker:
        return {"error": "LLM 不可用，请检查配置"}

    admin = PetAdministrator(
        pet=pet,
        storage=storage,
        memory_store=memory,
        hybrid_retriever=hybrid,
        reranker=reranker,
        llm=llm,
    )

    async def event_stream():
        try:
            for event in admin.ask_stream(question, history=history):
                if event["type"] == "stage":
                    yield f"data: {json.dumps({'type': 'stage', 'stage': event['stage'], 'count': event.get('count', 0)}, ensure_ascii=False)}\n\n"
                elif event["type"] == "token":
                    yield f"data: {json.dumps({'type': 'token', 'text': event['text']}, ensure_ascii=False)}\n\n"
                elif event["type"] == "done":
                    result = event["result"]
                    # 保存宠物状态
                    pet_storage.save(admin.pet)
                    # 保存记忆
                    try:
                        memory.save()
                    except Exception:
                        pass
                    # 构造引用数据
                    citations_data = []
                    for c in result.citations:
                        citations_data.append({
                            "marker": c.marker,
                            "title": c.title,
                            "paragraph_num": c.paragraph_num,
                            "doc_id": c.doc_id,
                        })
                    sources_data = []
                    for s in result.sources:
                        sources_data.append({
                            "doc_id": s.doc_id,
                            "doc_title": s.doc_title,
                            "score": getattr(s, "score", 0),
                        })
                    yield f"data: {json.dumps({'type': 'done', 'answer': result.text, 'citations': citations_data, 'sources': sources_data, 'pet_events': result.pet_events}, ensure_ascii=False)}\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'type': 'error', 'message': str(e)}, ensure_ascii=False)}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")


def _sse_error(message: str):
    """返回 SSE 格式的错误流。"""
    async def _stream():
        yield _build_sse_event("error", {"message": message})
    return _stream()

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
    from web.app import _get_shared_storage, _get_shared_vector_index
    from core.pet.administrator import PetAdministrator
    from core.pet.storage import PetStorage
    from core.memory.store import MemoryStore
    from core.retrieval.hybrid import HybridRetriever
    from core.retrieval.rerank import Reranker

    body = await request.json()
    question = body.get("question", "").strip()
    history = body.get("history", [])

    if not question:
        return {"error": "请输入问题"}

    # 复用全局共享组件（避免每请求重新加载索引/模型）
    storage = _get_shared_storage(request.app)
    pet_storage = PetStorage()
    pet = pet_storage.load()

    if not pet:
        return {"error": "请先领养宠物"}

    memory = MemoryStore()

    vector_index = _get_shared_vector_index(request.app)
    hybrid = HybridRetriever(bm25_index=storage.bm25, vector_index=vector_index, storage=storage)
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
        """异步 SSE 流：同步生成器放到线程中运行，不阻塞 event loop。

        实现：asyncio.Queue + threading.Thread + loop.call_soon_threadsafe。
        """
        import asyncio
        import threading

        loop = asyncio.get_event_loop()
        queue: asyncio.Queue = asyncio.Queue(maxsize=64)
        _SENTINEL = object()

        def _run_in_thread():
            """在线程中运行同步生成器，把事件推入队列。"""
            try:
                for event in admin.ask_stream(question, history=history):
                    if event["type"] == "stage":
                        msg = f"data: {json.dumps({'type': 'stage', 'stage': event['stage'], 'count': event.get('count', 0)}, ensure_ascii=False)}\n\n"
                    elif event["type"] == "token":
                        msg = f"data: {json.dumps({'type': 'token', 'text': event['text']}, ensure_ascii=False)}\n\n"
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
                        msg = f"data: {json.dumps({'type': 'done', 'answer': result.text, 'citations': citations_data, 'sources': sources_data, 'pet_events': result.pet_events}, ensure_ascii=False)}\n\n"
                    else:
                        continue
                    # 线程安全地把消息放入 asyncio.Queue
                    loop.call_soon_threadsafe(queue.put_nowait, msg)
                # 发送结束标记
                loop.call_soon_threadsafe(queue.put_nowait, _SENTINEL)
            except Exception as e:
                err_msg = f"data: {json.dumps({'type': 'error', 'message': str(e)}, ensure_ascii=False)}\n\n"
                try:
                    loop.call_soon_threadsafe(queue.put_nowait, err_msg)
                except Exception:
                    pass
                loop.call_soon_threadsafe(queue.put_nowait, _SENTINEL)

        # 启动线程
        thread = threading.Thread(target=_run_in_thread, daemon=True)
        thread.start()

        # 异步消费队列
        try:
            while True:
                msg = await queue.get()
                if msg is _SENTINEL:
                    break
                yield msg
        finally:
            if thread.is_alive():
                thread.join(timeout=1.0)

    return StreamingResponse(event_stream(), media_type="text/event-stream")


def _sse_error(message: str):
    """返回 SSE 格式的错误流。"""
    async def _stream():
        yield _build_sse_event("error", {"message": message})
    return _stream()

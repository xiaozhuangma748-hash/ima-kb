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
from services.qa_service import QAService

router = APIRouter(tags=["qa"])


def _build_sse_event(event_type: str, data: dict) -> str:
    """构造 SSE 事件字符串。"""
    payload = json.dumps(data, ensure_ascii=False)
    return f"event: {event_type}\ndata: {payload}\n\n"


@router.post("/qa/stream")
async def qa_stream(request: Request):
    """SSE 流式问答。"""
    from web.app import _get_shared_storage, _get_shared_vector_index

    body = await request.json()
    question = body.get("question", "").strip()
    history = body.get("history", [])
    # 人格风格：scholar / warrior / artisan / neutral（Web 端可选，透传给 PetAdministrator）
    persona = body.get("persona", "").strip() or None

    if not question:
        return {"error": "请输入问题"}

    # 通过 QAService 统一组装，复用 Web 共享组件
    storage = _get_shared_storage(request.app)
    vector_index = _get_shared_vector_index(request.app)

    service = QAService(
        storage=storage,
        vector_index=vector_index,
    )

    if not service.has_pet:
        return {"error": "请先领养宠物"}
    if not service.is_ready:
        return {"error": "LLM 不可用，请检查配置"}

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
                for event in service.ask_stream(
            question, history=history, style_override=persona
        ):
                    if event["type"] == "stage":
                        msg = f"data: {json.dumps({'type': 'stage', 'stage': event['stage'], 'count': event.get('count', 0)}, ensure_ascii=False)}\n\n"
                    elif event["type"] == "token":
                        msg = f"data: {json.dumps({'type': 'token', 'text': event['text']}, ensure_ascii=False)}\n\n"
                    elif event["type"] == "done":
                        result = event["result"]
                        # 保存宠物状态和记忆
                        service.save_state()
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

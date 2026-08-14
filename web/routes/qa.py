"""AI 问答 — SSE 流式路由。

GET /api/qa/stream?q=...&persona=...
  返回 text/event-stream，逐字推送 LLM 生成内容。
"""
from __future__ import annotations

import asyncio
import json
import pathlib
from typing import Optional

from fastapi import APIRouter, File, HTTPException, Request, UploadFile
from fastapi.responses import StreamingResponse

from config import settings
from services.qa_service import QAService
from web.app import STATIC_DIR

router = APIRouter(tags=["qa"])

_AVATAR_EXTS = ("png", "jpg", "jpeg", "webp", "gif")


def _current_avatar_path() -> Optional[pathlib.Path]:
    """返回当前已上传的自定义头像文件（若有）。"""
    for ext in _AVATAR_EXTS:
        p = STATIC_DIR / f"avatar.{ext}"
        if p.exists():
            return p
    return None


@router.get("/avatar")
async def get_avatar():
    """返回当前自定义 AI 头像（未设置则为 null）。"""
    avatar = _current_avatar_path()
    if avatar is None:
        return {"avatar_url": None}
    return {"avatar_url": f"/static/{avatar.name}"}


@router.post("/avatar")
async def upload_avatar(file: UploadFile = File(...)):
    """上传自定义 AI 头像照片，替换默认 SVG。"""
    content_type = file.content_type or ""
    if not content_type.startswith("image/"):
        raise HTTPException(status_code=400, detail="仅支持图片文件（png/jpg/webp/gif）")
    ext_map = {
        "image/png": "png",
        "image/jpeg": "jpg",
        "image/webp": "webp",
        "image/gif": "gif",
    }
    ext = ext_map.get(content_type)
    if ext is None:
        raise HTTPException(status_code=400, detail=f"不支持的图片格式：{content_type}")
    data = await file.read()
    if len(data) > 5 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="图片过大，请控制在 5MB 以内")
    for old in STATIC_DIR.glob("avatar.*"):
        try:
            old.unlink()
        except OSError:
            pass
    (STATIC_DIR / f"avatar.{ext}").write_bytes(data)
    return {"avatar_url": f"/static/avatar.{ext}"}


@router.delete("/avatar")
async def delete_avatar():
    """删除自定义头像，恢复默认 SVG。"""
    removed = False
    for old in STATIC_DIR.glob("avatar.*"):
        try:
            old.unlink()
            removed = True
        except OSError:
            pass
    return {"removed": removed}


@router.post("/qa/stream")
async def qa_stream(request: Request):
    """SSE 流式问答。

    所有错误响应统一用 SSE 格式（data: {"type":"error","message":"..."}\n\n），
    因为前端 qa.js 用 fetch + ReadableStream 解析，不处理 JSON 响应。
    """
    from web.app import _get_shared_storage, _get_shared_vector_index, _get_shared_hybrid_retriever

    body = await request.json()
    question = body.get("question", "").strip()
    history = body.get("history", [])
    # 人格风格：scholar / warrior / artisan / neutral（Web 端可选，透传给 PetAdministrator）
    persona = body.get("persona", "").strip() or None

    if not question:
        return StreamingResponse(_sse_error("请输入问题"), media_type="text/event-stream")

    # 通过 QAService 统一组装，复用 Web 共享组件
    storage = _get_shared_storage(request.app)
    vector_index = _get_shared_vector_index(request.app)
    hybrid_retriever = _get_shared_hybrid_retriever(request.app)

    service = QAService(
        storage=storage,
        vector_index=vector_index,
        hybrid_retriever=hybrid_retriever,
    )

    if not service.has_pet:
        return StreamingResponse(_sse_error("请先领养宠物"), media_type="text/event-stream")
    if not service.is_ready:
        return StreamingResponse(_sse_error("LLM 不可用，请检查配置"), media_type="text/event-stream")

    async def event_stream():
        """异步 SSE 流：同步生成器放到线程中运行，不阻塞 event loop。

        实现：同步 queue.Queue（线程安全，阻塞式 put 不丢事件）
        + asyncio 侧用 run_in_executor 消费，避免 QueueFull 丢消息。
        + stop_event 在客户端断开时通知线程退出，避免僵尸线程。
        """
        import asyncio
        import queue as sync_queue
        import threading

        loop = asyncio.get_event_loop()
        q: sync_queue.Queue = sync_queue.Queue(maxsize=4096)
        stop_event = threading.Event()
        _SENTINEL = object()

        def _run_in_thread():
            """在线程中运行同步生成器，把事件推入队列（阻塞式，绝不丢）。"""
            try:
                for event in service.ask_stream(
            question, history=history, style_override=persona
        ):
                    if stop_event.is_set():
                        break
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
                    # 阻塞式 put（带超时，可响应 stop_event）
                    q.put(msg, timeout=0.5)
                # 发送结束标记
                q.put(_SENTINEL, timeout=0.5)
            except Exception as e:
                err_msg = f"data: {json.dumps({'type': 'error', 'message': str(e)}, ensure_ascii=False)}\n\n"
                try:
                    q.put(err_msg, timeout=0.5)
                except Exception:
                    pass
                try:
                    q.put(_SENTINEL, timeout=0.5)
                except Exception:
                    pass

        # 启动线程
        thread = threading.Thread(target=_run_in_thread, daemon=True)
        thread.start()

        # 异步消费队列（run_in_executor 不阻塞 event loop）
        get_task = None
        try:
            while True:
                get_task = asyncio.ensure_future(loop.run_in_executor(None, q.get))
                msg = await get_task
                if msg is _SENTINEL:
                    break
                yield msg
        finally:
            # 客户端断开时通知线程退出，并等待其结束
            stop_event.set()
            if get_task and not get_task.done():
                get_task.cancel()
            thread.join(timeout=1.0)

    return StreamingResponse(event_stream(), media_type="text/event-stream")


def _sse_error(message: str):
    """返回 SSE 格式的错误流。

    格式与 event_stream 内部事件一致：data 字段为 {"type":"error","message":"..."}，
    前端 qa.js 只解析 data 行（不解析 event 行），所以 type 必须放在 data 里。
    """
    async def _stream():
        payload = json.dumps({"type": "error", "message": message}, ensure_ascii=False)
        yield f"data: {payload}\n\n"
    return _stream()

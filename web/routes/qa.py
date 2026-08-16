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
from pydantic import BaseModel

from config import settings
from services.qa_service import QAService
from web.app import STATIC_DIR

router = APIRouter(tags=["qa"])

_AVATAR_EXTS = ("png", "jpg", "jpeg", "webp", "gif")


@router.get("/models")
async def list_models():
    """返回可用模型列表及当前模型。"""
    from core.llm.client import get_llm, LLMError
    from core.llm.model_registry import get_models
    current = ""
    try:
        current = get_llm().model
    except LLMError:
        pass
    return {"models": get_models(), "current": current}


@router.put("/model")
async def set_model(request: Request):
    """切换当前使用的 LLM 模型。"""
    from core.llm.client import get_llm, LLMError
    from core.llm.model_registry import get_model
    body = await request.json()
    model_id = body.get("model", "").strip()
    if not model_id:
        raise HTTPException(status_code=400, detail="请指定模型 ID")
    if get_model(model_id) is None:
        raise HTTPException(status_code=400, detail=f"无效模型：{model_id}")
    try:
        get_llm().set_model(model_id)
    except LLMError as e:
        raise HTTPException(status_code=500, detail=str(e))
    return {"model": model_id}


class ModelBody(BaseModel):
    id: str
    name: str = ""
    desc: str = ""
    base_url: str = ""
    api_key: str = ""


@router.post("/models")
async def add_model(body: ModelBody):
    """添加自定义模型。"""
    from core.llm.model_registry import add_model as reg_add
    try:
        models = reg_add(body.id, body.name, body.desc, body.base_url, body.api_key)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"models": models}


@router.delete("/models/{model_id}")
async def delete_model(model_id: str):
    """删除自定义模型（内置模型不可删）。"""
    from core.llm.model_registry import remove_model
    try:
        models = remove_model(model_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"models": models}


def _current_avatar_path() -> Optional[pathlib.Path]:
    """返回当前已上传的自定义头像文件（若有）。仓库自带 avatar.gif 为默认头像，不算自定义。"""
    for ext in _AVATAR_EXTS:
        p = STATIC_DIR / f"custom_avatar.{ext}"
        if p.exists():
            return p
    return None


@router.get("/avatar")
async def get_avatar():
    """返回当前自定义 AI 头像（未设置则为 null，前端显示默认 avatar.gif）。"""
    avatar = _current_avatar_path()
    if avatar is None:
        return {"avatar_url": None}
    return {"avatar_url": f"/static/{avatar.name}"}


@router.post("/avatar")
async def upload_avatar(file: UploadFile = File(...)):
    """上传自定义 AI 头像照片，覆盖旧的自定义头像（不影响默认 avatar.gif）。"""
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
    for old in STATIC_DIR.glob("custom_avatar.*"):
        try:
            old.unlink()
        except OSError:
            pass
    (STATIC_DIR / f"custom_avatar.{ext}").write_bytes(data)
    return {"avatar_url": f"/static/custom_avatar.{ext}"}


@router.delete("/avatar")
async def delete_avatar():
    """删除自定义头像，恢复默认 avatar.gif。"""
    removed = False
    for old in STATIC_DIR.glob("custom_avatar.*"):
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
    # 检索方式：use_vector / use_rerank（Web 端可选，默认混合检索 + 重排序）
    use_vector = bool(body.get("use_vector", True))
    use_rerank = bool(body.get("use_rerank", True))

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
            question, history=history, style_override=persona,
            use_vector=use_vector, use_rerank=use_rerank,
        ):
                    if stop_event.is_set():
                        break
                    if event["type"] == "stage":
                        payload = {'type': 'stage', 'stage': event['stage'], 'count': event.get('count', 0)}
                        if 'context' in event:
                            payload['context'] = event['context']
                        msg = f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
                    elif event["type"] == "token":
                        msg = f"data: {json.dumps({'type': 'token', 'text': event['text']}, ensure_ascii=False)}\n\n"
                    elif event["type"] == "log":
                        # 运行日志快照（英文技术日志），供前端轨迹视图展示排查信息
                        msg = f"data: {json.dumps({'type': 'log', 'logs': event.get('logs', [])}, ensure_ascii=False)}\n\n"
                    elif event["type"] == "usage":
                        # LLM token 用量，供前端状态栏展示真实 token 数
                        msg = f"data: {json.dumps({'type': 'usage', 'input': event.get('input', 0), 'output': event.get('output', 0), 'total': event.get('total', 0)}, ensure_ascii=False)}\n\n"
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
                                # 命中片段原文，供轨迹视图就地展示真实日志
                                "preview": getattr(c, "snippet", "") or getattr(c, "preview", ""),
                            })
                        sources_data = []
                        for s in result.sources:
                            sources_data.append({
                                "doc_id": s.doc_id,
                                "doc_title": s.doc_title,
                                "score": getattr(s, "score", 0),
                                "source": getattr(s, "source", ""),
                                "paragraph_num": getattr(s, "paragraph_num", 0),
                                "preview": (getattr(s, "content", "") or "")[:180],
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

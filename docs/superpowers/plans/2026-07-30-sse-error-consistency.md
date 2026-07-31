# SSE 错误响应一致性修复 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 修复 `/api/qa/stream` 早期错误响应返回 JSON 而非 SSE 流的 bug，让前端能正确显示"请输入问题"/"请先领养宠物"/"LLM 不可用"等错误提示。

**Architecture:** 把 3 处早期 `return {"error": ...}` 改为返回 `StreamingResponse(_sse_error(...), media_type="text/event-stream")`，复用已有的 `_sse_error` helper。流式中错误统一用 `_build_sse_event("error", ...)`。不触及核心流式生成逻辑。

**Tech Stack:** Python 3.9+, FastAPI, pytest, httpx

---

## File Structure

- Modify: `web/routes/qa.py` — 3 处早期错误响应 + 1 处流式中错误格式
- Test: `tests/web/test_qa_sse_error.py` — 新增 SSE 错误响应测试

---

## Task 1: 编写 SSE 早期错误响应测试（当前会失败）

**Files:**
- Create: `tests/web/test_qa_sse_error.py`

- [x] **Step 1: 编写测试文件**

```python
"""验证 /api/qa/stream 早期错误响应使用 SSE 格式（而非 JSON）。

前端 qa.js 用 fetch + ReadableStream 直接解析 SSE 流，期望所有响应
（包括错误）都是 text/event-stream，data 字段为 JSON。
若后端早期错误返回 JSON，前端无法解析显示。
"""
from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(monkeypatch, tmp_path):
    """构造一个不依赖 LLM/向量索引的测试客户端。"""
    monkeypatch.setattr("config.settings.storage_path", tmp_path)
    monkeypatch.setattr("config.settings.agnes_api_key", "")  # 无 LLM

    from web.app import create_app
    app = create_app()
    return TestClient(app)


def _parse_sse_events(text: str) -> list:
    """把 SSE 文本解析为事件列表。"""
    events = []
    for block in text.split("\n\n"):
        if not block.strip():
            continue
        data = ""
        for line in block.split("\n"):
            if line.startswith("data: "):
                data = line[6:]
            elif line.startswith("data:"):
                data = line[5:]
        if data:
            try:
                events.append(json.loads(data))
            except json.JSONDecodeError:
                events.append({"raw": data})
    return events


def test_empty_question_returns_sse_error(client):
    """空问题应返回 SSE 错误流，而非 JSON。"""
    resp = client.post("/api/qa/stream", json={"question": ""})
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/event-stream")
    events = _parse_sse_events(resp.text)
    assert len(events) == 1
    assert events[0]["type"] == "error"
    assert "问题" in events[0]["message"]


def test_no_question_returns_sse_error(client):
    """缺少 question 字段应返回 SSE 错误流。"""
    resp = client.post("/api/qa/stream", json={})
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/event-stream")
    events = _parse_sse_events(resp.text)
    assert len(events) == 1
    assert events[0]["type"] == "error"


def test_whitespace_question_returns_sse_error(client):
    """纯空白问题应返回 SSE 错误流。"""
    resp = client.post("/api/qa/stream", json={"question": "   "})
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/event-stream")
    events = _parse_sse_events(resp.text)
    assert len(events) == 1
    assert events[0]["type"] == "error"
```

- [x] **Step 2: 运行测试验证失败**

Run: `cd "/Users/4u/Desktop/项目/拱墅区/2025身后事（殡葬）项目/34-知识库" && source .venv/bin/activate && python -m pytest tests/web/test_qa_sse_error.py -v`

Expected: 3 个测试全部 FAIL，因为当前早期错误返回 JSON（`{"error": "..."}`），不是 SSE 格式。`content-type` 是 `application/json`，`_parse_sse_events` 解析不出事件。

- [x] **Step 3: 提交**

```bash
git add tests/web/test_qa_sse_error.py
git commit -m "test: 添加 SSE 早期错误响应测试（当前失败）"
```

---

## Task 2: 修复早期错误响应为 SSE 格式

**Files:**
- Modify: `web/routes/qa.py:27-55`

- [x] **Step 1: 修改 qa_stream 早期错误响应**

把 `web/routes/qa.py` 中第 27-55 行的 `qa_stream` 函数早期返回改为 SSE 流。

将：
```python
@router.post("/qa/stream")
async def qa_stream(request: Request):
    """SSE 流式问答。"""
    from web.app import _get_shared_storage, _get_shared_vector_index, _get_shared_hybrid_retriever

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
    hybrid_retriever = _get_shared_hybrid_retriever(request.app)

    service = QAService(
        storage=storage,
        vector_index=vector_index,
        hybrid_retriever=hybrid_retriever,
    )

    if not service.has_pet:
        return {"error": "请先领养宠物"}
    if not service.is_ready:
        return {"error": "LLM 不可用，请检查配置"}
```

改为：
```python
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
```

- [x] **Step 2: 运行测试验证通过**

Run: `cd "/Users/4u/Desktop/项目/拱墅区/2025身后事（殡葬）项目/34-知识库" && source .venv/bin/activate && python -m pytest tests/web/test_qa_sse_error.py -v`

Expected: 3 个测试全部 PASS。

- [x] **Step 3: 提交**

```bash
git add web/routes/qa.py
git commit -m "fix: /api/qa/stream 早期错误响应改为 SSE 格式

前端 qa.js 用 fetch + ReadableStream 直接解析 SSE 流，期望所有响应
都是 text/event-stream。早期错误返回 JSON 时前端无法解析显示。
改为 StreamingResponse(_sse_error(...)) 统一格式。"
```

---

## Task 3: 流式中错误统一用 _build_sse_event helper

**Files:**
- Modify: `web/routes/qa.py:106-112`

- [x] **Step 1: 修改 _run_in_thread 中的错误格式**

把 `web/routes/qa.py` 中第 106-112 行的错误响应从手写 JSON 改为用 `_build_sse_event` helper。

将：
```python
            except Exception as e:
                err_msg = f"data: {json.dumps({'type': 'error', 'message': str(e)}, ensure_ascii=False)}\n\n"
                try:
                    loop.call_soon_threadsafe(queue.put_nowait, err_msg)
                except Exception:
                    pass
                loop.call_soon_threadsafe(queue.put_nowait, _SENTINEL)
```

改为：
```python
            except Exception as e:
                err_msg = _build_sse_event("error", {"message": str(e)})
                try:
                    loop.call_soon_threadsafe(queue.put_nowait, err_msg)
                except Exception:
                    pass
                loop.call_soon_threadsafe(queue.put_nowait, _SENTINEL)
```

- [x] **Step 2: 运行全量 qa 相关测试验证无回归**

Run: `cd "/Users/4u/Desktop/项目/拱墅区/2025身后事（殡葬）项目/34-知识库" && source .venv/bin/activate && python -m pytest tests/web/ -v`

Expected: 所有 web 测试通过，无回归。

- [x] **Step 3: 提交**

```bash
git add web/routes/qa.py
git commit -m "refactor: 流式中错误用 _build_sse_event 统一格式

手写 f\"data: {json.dumps(...)}\\n\\n\" 改为 _build_sse_event(\"error\", ...)，
与文件中其他 SSE 事件保持一致。纯重构，行为不变。"
```

---

## Task 4: 运行全量测试验证无回归

- [x] **Step 1: 运行全量 pytest**

Run: `cd "/Users/4u/Desktop/项目/拱墅区/2025身后事（殡葬）项目/34-知识库" && source .venv/bin/activate && python -m pytest tests/ --tb=short -q`

Expected: 727 + 3 = 730 passed, 0 failed。

- [x] **Step 2: 提交最终状态（如有需要）**

如果前面所有 commit 都已成功，此步骤可跳过。否则补一个 squash commit：
```bash
git commit --allow-empty -m "chore: SSE 错误响应一致性修复完成"
```

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

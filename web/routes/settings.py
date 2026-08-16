"""Web UI 设置 — 持久化到后端 config 文件。

GET /api/settings  读取 UI 偏好（主题/主题色/内容开关）
PUT /api/settings  保存 UI 偏好（全量覆盖）

存储位置：<storage_path>/web_settings.json，内网多浏览器共享一份。
"""
from __future__ import annotations

import json
import threading
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from config import settings as app_settings

router = APIRouter(tags=["settings"])

_lock = threading.Lock()

# 允许的键与默认值（前端 store/settings.js 的 DEFAULTS 保持一致）
_DEFAULTS = {
    "theme": "dark",          # dark | light | system
    "accent": "blue",         # blue | green | purple | orange
    "streaming": True,
    "use_rerank": True,       # 搜索页开关初始值
    "use_vector": True,
    "auto_expand_sources": True,
    "animations": True,
}

_ALLOWED_KEYS = set(_DEFAULTS.keys())
_ALLOWED_THEMES = {"dark", "light", "system"}
_ALLOWED_ACCENTS = {"blue", "green", "purple", "orange"}


def _settings_path():
    return app_settings.storage_path / "web_settings.json"


def _read() -> dict[str, Any]:
    path = _settings_path()
    data: dict[str, Any] = {}
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            data = {}
    # 归一化：丢弃未知键，合并默认值，校验枚举
    merged = dict(_DEFAULTS)
    if isinstance(data, dict):
        for k in _ALLOWED_KEYS:
            if k in data:
                merged[k] = data[k]
    if merged["theme"] not in _ALLOWED_THEMES:
        merged["theme"] = "dark"
    if merged["accent"] not in _ALLOWED_ACCENTS:
        merged["accent"] = "blue"
    return merged


def _write(data: dict[str, Any]) -> None:
    path = _settings_path()
    with _lock:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )


class SettingsBody(BaseModel):
    theme: str = Field(default="dark")
    accent: str = Field(default="blue")
    streaming: bool = True
    use_rerank: bool = True
    use_vector: bool = True
    auto_expand_sources: bool = True
    animations: bool = True


@router.get("/settings")
async def get_settings():
    """读取 Web UI 设置。"""
    return _read()


@router.put("/settings")
async def put_settings(body: SettingsBody):
    """保存 Web UI 设置（全量覆盖）。"""
    if body.theme not in _ALLOWED_THEMES:
        raise HTTPException(status_code=400, detail=f"无效主题：{body.theme}")
    if body.accent not in _ALLOWED_ACCENTS:
        raise HTTPException(status_code=400, detail=f"无效主题色：{body.accent}")
    data = body.model_dump()
    _write(data)
    return _read()
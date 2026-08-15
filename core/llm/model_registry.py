"""模型注册表：管理可用 LLM 模型列表（内置 + 用户自定义）。

持久化到 <storage_path>/models.json。内置模型不可删除，自定义模型可增删。
自定义模型可指定独立 base_url / api_key（缺省回退到全局 AGNES 配置）。
"""
from __future__ import annotations

import json
import threading
from typing import Any, List, Optional

from config import settings

_lock = threading.Lock()

# 内置模型（不可删除）。base_url / api_key 留空表示使用全局配置。
BUILTIN_MODELS: List[dict] = [
    {"id": "deepseek-chat", "name": "DeepSeek-V3", "desc": "通用对话，速度快", "builtin": True, "base_url": "", "api_key": ""},
    {"id": "deepseek-reasoner", "name": "DeepSeek-R1", "desc": "深度推理，适合复杂问题", "builtin": True, "base_url": "", "api_key": ""},
]


def _path():
    return settings.storage_path / "models.json"


def _read() -> List[dict]:
    """读取模型列表：内置 + 用户自定义（合并去重）。"""
    path = _path()
    custom: List[dict] = []
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, list):
                custom = data
        except (json.JSONDecodeError, OSError):
            custom = []
    result = [dict(m) for m in BUILTIN_MODELS]
    seen = {m["id"] for m in result}
    for m in custom:
        mid = m.get("id", "")
        if mid and mid not in seen:
            m.setdefault("name", mid)
            m.setdefault("desc", "")
            m.setdefault("builtin", False)
            m.setdefault("base_url", "")
            m.setdefault("api_key", "")
            result.append(m)
            seen.add(mid)
    return result


def _write(models: List[dict]) -> None:
    path = _path()
    with _lock:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(models, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )


def get_models() -> List[dict]:
    """返回全部模型（含内置）。"""
    return _read()


def get_model(model_id: str) -> Optional[dict]:
    """按 id 查找模型，找不到返回 None。"""
    return next((m for m in _read() if m["id"] == model_id), None)


def add_model(
    model_id: str,
    name: str = "",
    desc: str = "",
    base_url: str = "",
    api_key: str = "",
) -> List[dict]:
    """添加自定义模型。model_id 重复时抛 ValueError。"""
    model_id = model_id.strip()
    if not model_id:
        raise ValueError("模型 ID 不能为空")
    models = _read()
    if any(m["id"] == model_id for m in models):
        raise ValueError(f"模型 ID 已存在：{model_id}")
    models.append({
        "id": model_id,
        "name": name.strip() or model_id,
        "desc": desc.strip(),
        "builtin": False,
        "base_url": base_url.strip(),
        "api_key": api_key.strip(),
    })
    _write(models)
    return models


def remove_model(model_id: str) -> List[dict]:
    """删除自定义模型。内置模型或不存在时抛 ValueError。"""
    models = _read()
    target = next((m for m in models if m["id"] == model_id), None)
    if target is None:
        raise ValueError(f"模型不存在：{model_id}")
    if target.get("builtin"):
        raise ValueError(f"内置模型不可删除：{model_id}")
    models = [m for m in models if m["id"] != model_id]
    _write(models)
    return models
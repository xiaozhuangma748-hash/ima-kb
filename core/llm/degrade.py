"""LLM 降级提示统一文案。

避免各调用点各自拼字符串导致提示不一致。
所有 LLM 不可用时的用户可见提示都应走这里。
"""
from __future__ import annotations

from typing import Optional


# 错误类型 → 排查建议映射
_ERROR_HINTS = {
    "Timeout":           "请求超时，请稍后重试",
    "ConnectError":      "无法连接 LLM 服务，请检查网络",
    "ConnectionError":   "无法连接 LLM 服务，请检查网络",
    "RateLimitExceeded": "触发限流（429），请稍后再试",
    "AuthenticationError": "鉴权失败，请检查 AGNES_API_KEY 配置",
    "PermissionDenied":  "权限不足，请确认 API Key 是否有效",
    "InvalidAPIKey":     "API Key 无效，请检查 .env 中的 AGNES_API_KEY",
}


def _hint_for(error: Optional[Exception]) -> str:
    """根据异常类型返回排查建议。"""
    if error is None:
        return ""
    err_type = type(error).__name__
    # 精确匹配
    if err_type in _ERROR_HINTS:
        return _ERROR_HINTS[err_type]
    # 模糊匹配错误消息
    msg = str(error).lower()
    if "timeout" in msg or "timed out" in msg:
        return _ERROR_HINTS["Timeout"]
    if "429" in msg or "rate limit" in msg:
        return _ERROR_HINTS["RateLimitExceeded"]
    if "401" in msg or "auth" in msg or "api key" in msg:
        return _ERROR_HINTS["AuthenticationError"]
    if "connect" in msg or "network" in msg:
        return _ERROR_HINTS["ConnectError"]
    return ""


def get_llm_degrade_message(
    error: Optional[Exception] = None,
    has_sources: bool = False,
    source_count: int = 0,
) -> str:
    """生成统一的 LLM 降级提示文案。

    Args:
        error: 触发降级的异常（可选，用于拼接错误细节和排查建议）
        has_sources: 是否检索到了相关资料
        source_count: 检索到的资料条数

    Returns:
        统一的降级提示文案
    """
    err_detail = f"（{type(error).__name__}: {error}）" if error else ""
    hint = _hint_for(error)
    hint_part = f" · {hint}" if hint else ""

    if has_sources and source_count > 0:
        return (
            f"⚠ LLM 不可用{err_detail}，已降级为检索模式，"
            f"展示 {source_count} 条相关原文：{hint_part}"
        )
    return f"⚠ LLM 不可用{err_detail}，且未检索到相关资料。{hint_part}".rstrip()

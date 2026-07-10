"""LLM 客户端：封装 Agnes AI 的 OpenAI 兼容调用。

提供：
- chat(): 单轮对话
- chat_stream(): 流式对话（用于实时输出）
"""
from __future__ import annotations

import time
from typing import Iterator, List, Optional

from openai import OpenAI

from config import settings


class LLMError(Exception):
    """LLM 调用失败。"""


# 触发重试的异常类型（网络/超时类，非业务错误）
_RETRYABLE_ERRORS = (
    "APIConnectionError",
    "APITimeoutError",
    "APIStatusError",  # 5xx 服务端错误也会被这个捕获
)


class LLMClient:
    """Agnes AI LLM 客户端单例。"""

    def __init__(self) -> None:
        if not settings.has_llm():
            raise LLMError(
                "未配置 AGNES_API_KEY，请在 .env 中设置。"
                "参考 .env.example。"
            )
        self._client = OpenAI(
            api_key=settings.agnes_api_key,
            base_url=settings.agnes_base_url,
            timeout=60.0,  # 单次请求超时 60 秒（默认太短）
        )
        self._model = settings.llm_model
        # 最近一次调用的 token 使用量（由 chat/chat_stream 写入）
        self.last_usage: Optional[dict] = None

    def chat(
        self,
        messages: List[dict],
        temperature: float = 0.3,
        max_tokens: Optional[int] = None,
        max_retries: int = 3,
    ) -> str:
        """同步对话（带自动重试）。

        Args:
            messages: [{"role": "system"/"user"/"assistant", "content": "..."}]
            temperature: 温度，0=确定性，1=随机
            max_tokens: 最大输出 token
            max_retries: 最大重试次数（默认 3，仅对网络/超时错误重试）

        Returns:
            LLM 回复文本
        """
        last_err: Optional[Exception] = None
        for attempt in range(max_retries + 1):
            try:
                resp = self._client.chat.completions.create(
                    model=self._model,
                    messages=messages,
                    temperature=temperature,
                    max_tokens=max_tokens or settings.llm_max_tokens,
                )
                # 存储 token 使用量（OpenAI SDK: resp.usage 属性）
                try:
                    usage = getattr(resp, "usage", None)
                    if usage:
                        self.last_usage = {
                            "input": getattr(usage, "prompt_tokens", 0),
                            "output": getattr(usage, "completion_tokens", 0),
                            "total": getattr(usage, "total_tokens", 0),
                        }
                except Exception:
                    self.last_usage = None
                return resp.choices[0].message.content or ""
            except Exception as e:
                last_err = e
                err_type = type(e).__name__
                # 判断是否可重试
                should_retry = (
                    any(t in err_type for t in _RETRYABLE_ERRORS)
                    and attempt < max_retries
                )
                # 对 5xx 状态码单独判断（APIStatusError 可能是 4xx 也可能 5xx）
                status_code = getattr(e, "status_code", None)
                if status_code is not None and 500 <= status_code < 600 and attempt < max_retries:
                    should_retry = True
                if not should_retry:
                    raise LLMError(f"LLM 调用失败: {err_type}: {e}") from e
                # 指数退避：1s, 2s, 4s
                wait = 2 ** attempt
                time.sleep(wait)
        # 所有重试都失败
        raise LLMError(
            f"LLM 调用失败（已重试 {max_retries} 次）: "
            f"{type(last_err).__name__}: {last_err}"
        ) from last_err

    def chat_stream(
        self,
        messages: List[dict],
        temperature: float = 0.3,
        max_tokens: Optional[int] = None,
    ) -> Iterator[str]:
        """流式对话，逐 token 返回。

        注意：流式不重试（部分 token 已输出，重试会导致内容重复）。
        如果第一帧就失败，会直接抛错让用户重试。
        """
        try:
            stream = self._client.chat.completions.create(
                model=self._model,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens or settings.llm_max_tokens,
                stream=True,
                stream_options={"include_usage": True},
            )
            for chunk in stream:
                # 流式最后一帧 choices 为空，可能携带 usage，提取后跳过
                if not chunk.choices:
                    usage = getattr(chunk, "usage", None)
                    if usage:
                        try:
                            self.last_usage = {
                                "input": getattr(usage, "prompt_tokens", 0),
                                "output": getattr(usage, "completion_tokens", 0),
                                "total": getattr(usage, "total_tokens", 0),
                            }
                        except Exception:
                            pass
                    continue
                delta = chunk.choices[0].delta
                content = getattr(delta, "content", None)
                if content:
                    yield content
        except Exception as e:
            raise LLMError(f"LLM 流式调用失败: {type(e).__name__}: {e}") from e


# 模块级单例（首次访问时创建）
_client: Optional[LLMClient] = None


def get_llm() -> LLMClient:
    """获取 LLM 客户端单例。"""
    global _client
    if _client is None:
        _client = LLMClient()
    return _client

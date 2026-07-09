"""图像生成器：封装 Agnes Image 2.1 Flash API 调用。

使用 OpenAI 兼容接口（与 LLM 相同的 base_url + api_key）。

注意：Agnes Image API 不接受 response_format/size 等标准 OpenAI 参数，
这些必须通过 extra_body 透传。
"""
from __future__ import annotations

import time
import logging
from pathlib import Path
from typing import List, Optional

from config import settings
from core.llm.client import LLMClient, get_llm

logger = logging.getLogger(__name__)


class ImageError(Exception):
    """图像生成失败。"""


class ImageGenerator:
    """Agnes Image 2.1 Flash 客户端。

    复用 LLMClient 的 OpenAI 客户端（相同的 base_url 和 api_key），
    只是调用不同的 model。
    """

    def __init__(self, llm_client: Optional[LLMClient] = None) -> None:
        if not settings.has_llm():
            raise ImageError("未配置 AGNES_API_KEY，请在 .env 中设置。")
        self._client = llm_client._client if llm_client else get_llm()._client
        self._model = settings.image_model

    def text_to_image(
        self,
        prompt: str,
        enhanced: bool = True,
        size: Optional[str] = None,
    ) -> str:
        """文生图。

        Args:
            prompt: 图像描述
            enhanced: 是否启用 prompt 增强
            size: 图像尺寸（默认 1024x1024）

        Returns:
            图片 URL
        """
        size = size or "1024x1024"

        # API 只接受 model/prompt/size/n 这些标准 OpenAI 参数
        # extra_body 和 response_format 均不被支持
        params = {
            "model": self._model,
            "prompt": prompt,
            "size": size,
            "n": 1,
        }

        return self._call_api(params)

    def doc_to_image(
        self,
        doc_title: str,
        doc_content: str,
        style: str = "简洁信息图",
    ) -> str:
        """基于文档内容生成配图。

        先用 LLM 提取文档核心主题，再构造生图 prompt。

        Args:
            doc_title: 文档标题
            doc_content: 文档内容（前 500 字）
            style: 图像风格

        Returns:
            图片 URL
        """
        prompt = (
            f"请根据以下文档内容生成一张{style}风格的配图。\n"
            f"文档标题：{doc_title}\n"
            f"文档内容摘要：{doc_content[:300]}\n\n"
            f"要求：\n"
            f"1. 图像应准确反映文档核心主题\n"
            f"2. 使用{style}艺术风格\n"
            f"3. 适合用于知识库可视化展示\n"
            f"4. 用英文描述图像内容（模型对英文 prompt 理解更好）"
        )

        try:
            enhanced = self._enhance_prompt(prompt)
        except Exception as e:
            logger.warning(f"Prompt 增强失败，使用原始 prompt: {e}")
            enhanced = f"Illustration about: {doc_title}, style: {style}"

        return self.text_to_image(enhanced, enhanced=True)

    def daily_card(
        self,
        topics: List[str],
        date_str: str,
        style: str = "极简卡片",
    ) -> str:
        """生成每日知识卡片。

        Args:
            topics: 今日知识点列表
            date_str: 日期字符串
            style: 卡片风格

        Returns:
            图片 URL
        """
        topic_text = "、".join(topics[:5])
        prompt = (
            f"A minimalist knowledge card for {date_str}, "
            f"showing key topics: {topic_text}. "
            f"Style: {style}. "
            f"Clean layout with typography, soft background, "
            f"suitable for sharing on social media."
        )
        # 知识卡片用竖版比例
        return self.text_to_image(prompt, enhanced=True, size="1024x1792")

    def _enhance_prompt(self, base_prompt: str) -> str:
        """用 LLM 将中文 prompt 翻译/增强为英文。"""
        from core.llm.client import LLMError

        try:
            llm = get_llm()
            response = llm.chat(
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "You are a prompt engineer for image generation. "
                            "Translate the following Chinese prompt into English, "
                            "making it more descriptive and vivid for image generation. "
                            "Only output the enhanced English prompt, nothing else."
                        ),
                    },
                    {"role": "user", "content": base_prompt},
                ],
                temperature=0.5,
                max_tokens=300,
            )
            return response.strip()
        except LLMError:
            return f"Illustration about: {base_prompt[:100]}"

    def _call_api(self, params: dict) -> str:
        """调用 Agnes Image API。"""
        max_retries = 3
        last_err: Optional[Exception] = None

        for attempt in range(max_retries + 1):
            try:
                resp = self._client.images.generate(**params)

                if resp.data and len(resp.data) > 0:
                    url = resp.data[0].url
                    if url:
                        return url
                    b64 = resp.data[0].b64_json
                    if b64:
                        return f"data:image/png;base64,{b64}"

                raise ImageError("API 返回了空响应")

            except Exception as e:
                last_err = e
                err_type = type(e).__name__
                should_retry = (
                    any(t in err_type for t in ("APIConnectionError", "APITimeoutError", "APIStatusError"))
                    and attempt < max_retries
                )
                status_code = getattr(e, "status_code", None)
                if status_code and 500 <= status_code < 600 and attempt < max_retries:
                    should_retry = True

                if not should_retry:
                    raise ImageError(f"图像生成失败: {err_type}: {e}") from e

                wait = 2 ** attempt
                time.sleep(wait)

        if last_err:
            raise ImageError(f"图像生成失败（已重试 {max_retries} 次）: {last_err}") from last_err

        raise ImageError("图像生成失败：未知错误")


# 模块级单例
_generator: Optional[ImageGenerator] = None


def get_image_generator() -> ImageGenerator:
    """获取图像生成器单例。"""
    global _generator
    if _generator is None:
        try:
            _generator = ImageGenerator()
        except ImageError:
            _generator = None
            raise
    return _generator

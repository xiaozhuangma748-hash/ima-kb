"""ImageGenerator 配置独立性测试。

Bug 3 修复验证：图像生成器应支持独立的 IMAGE_API_KEY/IMAGE_BASE_URL 配置，
不复用 LLM 的 client，避免 LLM 切换到 DeepSeek 后图像功能失效。
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch
from pathlib import Path
import sys

import pytest

PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


def test_image_generator_uses_independent_config(monkeypatch):
    """Bug 3: ImageGenerator 应优先使用独立的 IMAGE_BASE_URL/IMAGE_API_KEY。"""
    from config import settings
    # 设置独立图像配置
    monkeypatch.setattr(settings, "image_api_key", "sk-image-test-key")
    monkeypatch.setattr(settings, "image_base_url", "https://apihub.agnes-ai.com/v1")
    monkeypatch.setattr(settings, "image_model", "agnes-image-2.1-flash")
    # LLM 配置为 DeepSeek（不应影响图像）
    monkeypatch.setattr(settings, "agnes_api_key", "sk-deepseek-key")
    monkeypatch.setattr(settings, "agnes_base_url", "https://api.deepseek.com/v1")

    from core.image.generator import ImageGenerator

    gen = ImageGenerator()

    # 验证 client 使用的是独立的图像配置，不是 DeepSeek
    assert "deepseek" not in str(gen._client.base_url).lower(), \
        "ImageGenerator 不应复用 DeepSeek 的 base_url"
    assert "agnes" in str(gen._client.base_url).lower() or "apihub" in str(gen._client.base_url).lower(), \
        f"ImageGenerator 应使用独立的图像 API base_url，实际: {gen._client.base_url}"


def test_image_generator_falls_back_to_llm_config_when_no_image_config(monkeypatch):
    """未配置 IMAGE_API_KEY 时回退到 LLM 配置（向后兼容）。"""
    from config import settings
    # 清除独立图像配置（image_api_key 为空）
    monkeypatch.setattr(settings, "image_api_key", "")
    monkeypatch.setattr(settings, "image_base_url", "")
    # LLM 配置为 Agnes
    monkeypatch.setattr(settings, "agnes_api_key", "sk-agnes-key")
    monkeypatch.setattr(settings, "agnes_base_url", "https://apihub.agnes-ai.com/v1")
    monkeypatch.setattr(settings, "image_model", "agnes-image-2.1-flash")

    from core.image.generator import ImageGenerator

    gen = ImageGenerator()
    # 应回退到 LLM 配置
    assert "agnes" in str(gen._client.base_url).lower() or "apihub" in str(gen._client.base_url).lower()


def test_image_generator_raises_friendly_error_when_no_api_key(monkeypatch):
    """未配置任何 API key 时应给出友好错误。"""
    from config import settings
    monkeypatch.setattr(settings, "image_api_key", "")
    monkeypatch.setattr(settings, "agnes_api_key", "")
    monkeypatch.setattr(settings, "image_base_url", "")

    from core.image.generator import ImageGenerator, ImageError

    with pytest.raises(ImageError) as exc_info:
        ImageGenerator()
    assert "API_KEY" in str(exc_info.value) or "未配置" in str(exc_info.value)

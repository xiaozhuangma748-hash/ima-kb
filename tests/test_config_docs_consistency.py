"""Bug 13 修复验证：配置默认值与文档一致性测试。

验证：
1. .env.example 包含独立图像 API 配置段（IMAGE_API_KEY/IMAGE_BASE_URL/IMAGE_MODEL）
2. .env.example 不再使用与 config.py 默认值冲突的模型名（agnes-2.0-flash）
3. INSTALL.md 不再错误声明"生图使用与 LLM 相同的 AGNES_API_KEY"
4. INSTALL.md 包含独立图像 API 配置说明
5. config.py 默认值与 .env.example 注释保持一致
"""
from __future__ import annotations

from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_env_example_has_independent_image_api_section():
    """Bug 13 修复验证：.env.example 应包含独立图像 API 配置段。

    场景：LLM 切换到 DeepSeek 后，图像 API 仍用 Agnes，需独立配置。
    .env.example 应同时包含 LLM 和图像两段配置。
    """
    content = _read_text(PROJECT_ROOT / ".env.example")
    # 必须包含独立图像 API 字段
    assert "IMAGE_API_KEY" in content, ".env.example 应包含 IMAGE_API_KEY（独立图像 API 配置）"
    assert "IMAGE_BASE_URL" in content, ".env.example 应包含 IMAGE_BASE_URL"
    assert "IMAGE_MODEL" in content, ".env.example 应包含 IMAGE_MODEL"


def test_env_example_does_not_use_stale_agnes_2_0_model():
    """Bug 13 修复验证：.env.example 不应使用旧版 agnes-2.0-flash 模型名。

    场景：config.py 默认值为 agnes-2.5-flash，.env.example 用 agnes-2.0-flash
    会导致新用户安装时使用与默认值不一致的旧版模型名。
    修复后 .env.example 的 LLM_MODEL 应为通用占位符或与 config.py 默认一致。
    """
    content = _read_text(PROJECT_ROOT / ".env.example")
    # 不应硬编码旧版模型名（与新用户安装时的默认行为冲突）
    assert "agnes-2.0-flash" not in content, (
        ".env.example 不应使用旧版 agnes-2.0-flash，"
        "应使用占位符或与 config.py 默认值（agnes-2.5-flash）一致"
    )


def test_install_md_does_not_claim_image_uses_same_key_as_llm():
    """Bug 13 修复验证：INSTALL.md 不应错误声明图像 API 使用与 LLM 相同的 key。

    场景：DeepSeek 切换后，LLM key 是 DeepSeek 的，图像 key 是 Agnes 的，
    两者不同。文档若仍声明"无需额外配置"会误导用户。
    """
    content = _read_text(PROJECT_ROOT / "INSTALL.md")
    # 不应再有"生图使用与 LLM 相同的 AGNES_API_KEY，无需额外配置"这类误导性表述
    misleading_phrases = [
        "生图使用与 LLM 相同的",
        "生图使用与 LLM 相同的 `AGNES_API_KEY`",
    ]
    for phrase in misleading_phrases:
        assert phrase not in content, (
            f"INSTALL.md 不应包含误导性表述: '{phrase}'。"
            f"图像 API 现已支持独立配置（IMAGE_API_KEY），文档应说明这一点。"
        )


def test_install_md_documents_independent_image_api_key():
    """Bug 13 修复验证：INSTALL.md 应说明图像 API 可独立配置。

    场景：用户使用 DeepSeek 作为 LLM 时，需要单独配置图像 API（用 Agnes）。
    文档应清楚说明 IMAGE_API_KEY 与 AGNES_API_KEY 是两个独立配置。
    """
    content = _read_text(PROJECT_ROOT / "INSTALL.md")
    # 必须提及独立图像 API 配置
    assert "IMAGE_API_KEY" in content, (
        "INSTALL.md 应提及 IMAGE_API_KEY 配置项，"
        "说明图像 API 可独立于 LLM API 配置"
    )


def test_config_default_llm_model_remains_agnes_2_5_flash_as_fallback():
    """Bug 13 修复验证：config.py 默认 llm_model 应保留 agnes-2.5-flash 作为兜底。

    场景：根据项目约定，config.py 默认值保留 agnes-2.5-flash 作为兜底，
    .env 运行时覆盖为 deepseek-chat。这是有意为之的兼容性设计。
    """
    content = _read_text(PROJECT_ROOT / "config.py")
    # 默认值应保留 agnes-2.5-flash 作为兜底
    assert 'agnes-2.5-flash' in content, (
        "config.py 应保留 agnes-2.5-flash 作为 llm_model 的默认兜底值，"
        ".env 运行时覆盖为 deepseek-chat"
    )

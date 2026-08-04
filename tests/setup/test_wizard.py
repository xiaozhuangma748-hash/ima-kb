"""setup/wizard 测试：覆盖 _write_env 持久化、API key 校验、各 step 的输入处理。"""
from __future__ import annotations

import os
import stat
from pathlib import Path
from unittest.mock import patch

import pytest

from core.setup import wizard


# ============================================================
# _write_env 测试（核心持久化逻辑，无外部依赖）
# ============================================================

class TestWriteEnv:
    """测试 .env 文件写入与更新。"""

    def test_create_new_env(self, tmp_path, monkeypatch):
        """文件不存在时从零创建。"""
        monkeypatch.setattr(wizard, "PROJECT_ROOT", tmp_path)

        wizard._write_env({"AGNES_API_KEY": "sk-test123456"})

        env_path = tmp_path / ".env"
        assert env_path.exists()
        content = env_path.read_text(encoding="utf-8")
        assert "AGNES_API_KEY=sk-test123456" in content

    def test_update_existing_key(self, tmp_path, monkeypatch):
        """更新已存在的键，保留其他键。"""
        monkeypatch.setattr(wizard, "PROJECT_ROOT", tmp_path)
        env_path = tmp_path / ".env"
        env_path.write_text(
            "AGNES_API_KEY=old-key\nOTHER_VAR=keep\n",
            encoding="utf-8",
        )

        wizard._write_env({"AGNES_API_KEY": "sk-new-key-12345"})

        content = env_path.read_text(encoding="utf-8")
        assert "AGNES_API_KEY=sk-new-key-12345" in content
        assert "old-key" not in content
        # 其他变量应保留
        assert "OTHER_VAR=keep" in content

    def test_preserves_comments(self, tmp_path, monkeypatch):
        """保留注释行和空行。"""
        monkeypatch.setattr(wizard, "PROJECT_ROOT", tmp_path)
        env_path = tmp_path / ".env"
        original = (
            "# 这是注释\n"
            "AGNES_API_KEY=old\n"
            "\n"
            "# 另一段注释\n"
            "OTHER=value\n"
        )
        env_path.write_text(original, encoding="utf-8")

        wizard._write_env({"AGNES_API_KEY": "sk-newkey12345"})

        content = env_path.read_text(encoding="utf-8")
        assert "# 这是注释" in content
        assert "# 另一段注释" in content
        assert "AGNES_API_KEY=sk-newkey12345" in content
        assert "OTHER=value" in content

    def test_appends_new_key(self, tmp_path, monkeypatch):
        """新键追加到文件末尾。"""
        monkeypatch.setattr(wizard, "PROJECT_ROOT", tmp_path)
        env_path = tmp_path / ".env"
        env_path.write_text("EXISTING=foo\n", encoding="utf-8")

        wizard._write_env({"NEW_KEY": "bar"})

        content = env_path.read_text(encoding="utf-8")
        assert "EXISTING=foo" in content
        assert "NEW_KEY=bar" in content

    def test_file_permissions_600(self, tmp_path, monkeypatch):
        """文件权限应为 600（仅所有者可读写）。"""
        monkeypatch.setattr(wizard, "PROJECT_ROOT", tmp_path)

        wizard._write_env({"AGNES_API_KEY": "sk-test123456"})

        env_path = tmp_path / ".env"
        mode = stat.S_IMODE(env_path.stat().st_mode)
        assert mode == 0o600

    def test_multiple_keys_at_once(self, tmp_path, monkeypatch):
        """同时写入多个键。"""
        monkeypatch.setattr(wizard, "PROJECT_ROOT", tmp_path)

        wizard._write_env({
            "AGNES_API_KEY": "sk-test123",
            "LLM_MODEL": "gpt-4",
            "DEBUG": "true",
        })

        content = env_path = (tmp_path / ".env").read_text(encoding="utf-8")
        assert "AGNES_API_KEY=sk-test123" in content
        assert "LLM_MODEL=gpt-4" in content
        assert "DEBUG=true" in content

    def test_value_with_special_chars_preserved(self, tmp_path, monkeypatch):
        """值中的等号和特殊字符保留。"""
        monkeypatch.setattr(wizard, "PROJECT_ROOT", tmp_path)

        # 值里含 = 号（如 base64 编码）
        wizard._write_env({"TOKEN": "abc==def="})

        content = (tmp_path / ".env").read_text(encoding="utf-8")
        assert "TOKEN=abc==def=" in content

    def test_does_not_touch_commented_keys(self, tmp_path, monkeypatch):
        """注释掉的键（# KEY=...）不应被更新。"""
        monkeypatch.setattr(wizard, "PROJECT_ROOT", tmp_path)
        env_path = tmp_path / ".env"
        env_path.write_text(
            "# AGNES_API_KEY=commented\n"
            "OTHER=keep\n",
            encoding="utf-8",
        )

        wizard._write_env({"AGNES_API_KEY": "sk-realkey12345"})

        content = env_path.read_text(encoding="utf-8")
        # 注释行应原样保留
        assert "# AGNES_API_KEY=commented" in content
        # 新的键应被追加（而非更新注释行）
        assert "AGNES_API_KEY=sk-realkey12345" in content


# ============================================================
# _step_config_llm 输入校验测试
# ============================================================

class TestStepConfigLlm:
    """测试 LLM 配置步骤的输入校验（mock getpass 和 Prompt）。"""

    def test_short_api_key_rejected(self, tmp_path, monkeypatch, capsys):
        """长度 < 10 的 API Key 被拒绝。"""
        monkeypatch.setattr(wizard, "PROJECT_ROOT", tmp_path)
        # 模拟 getpass 返回过短的 key
        monkeypatch.setattr(wizard.getpass, "getpass", lambda _: "sk-short")

        # env_path 不存在，避免触发"重新配置"分支
        wizard._step_config_llm()

        # 不应写入 .env
        assert not (tmp_path / ".env").exists()
        # 应输出错误提示
        captured = capsys.readouterr()
        # rich 输出到 stdout
        assert "格式似乎不正确" in captured.out or "格式似乎不正确" in captured.err

    def test_empty_api_key_skipped(self, tmp_path, monkeypatch, capsys):
        """空输入跳过配置。"""
        monkeypatch.setattr(wizard, "PROJECT_ROOT", tmp_path)
        monkeypatch.setattr(wizard.getpass, "getpass", lambda _: "")

        wizard._step_config_llm()

        assert not (tmp_path / ".env").exists()
        captured = capsys.readouterr()
        assert "跳过" in captured.out or "跳过" in captured.err

    def test_valid_api_key_written(self, tmp_path, monkeypatch, capsys):
        """合法 API Key 被写入 .env。"""
        monkeypatch.setattr(wizard, "PROJECT_ROOT", tmp_path)
        test_key = "sk-valid-key-12345678"
        monkeypatch.setattr(wizard.getpass, "getpass", lambda _: test_key)
        # 清理环境变量，确保不触发"已配置"分支
        monkeypatch.delenv("AGNES_API_KEY", raising=False)

        wizard._step_config_llm()

        env_content = (tmp_path / ".env").read_text(encoding="utf-8")
        assert test_key in env_content
        # 环境变量也应被设置
        assert os.environ.get("AGNES_API_KEY") == test_key
        # 清理
        monkeypatch.delenv("AGNES_API_KEY", raising=False)

    def test_existing_valid_key_prompts_overwrite(self, tmp_path, monkeypatch):
        """已存在合法 key 时询问是否重新配置。"""
        monkeypatch.setattr(wizard, "PROJECT_ROOT", tmp_path)
        env_path = tmp_path / ".env"
        env_path.write_text("AGNES_API_KEY=sk-existing12345\n", encoding="utf-8")
        monkeypatch.setenv("AGNES_API_KEY", "sk-existing12345")

        # 用户选择 n（不重新配置）
        with patch.object(wizard.Prompt, "ask", return_value="n") as mock_ask:
            wizard._step_config_llm()
            # 应询问"是否重新配置"
            assert mock_ask.called

        # .env 应未被修改
        content = env_path.read_text(encoding="utf-8")
        assert "sk-existing12345" in content


# ============================================================
# _step_adopt_pet 测试
# ============================================================

class TestStepAdoptPet:
    """测试宠物领养步骤。"""

    def test_adopt_new_pet_with_default_name(self, tmp_path, monkeypatch):
        """使用默认名领养新宠物。"""
        # 配置 storage_path 让 PetStorage 写到临时目录
        monkeypatch.setattr(wizard.settings, "storage_path", tmp_path)
        # 用户直接回车（使用默认"小林同学"）
        with patch.object(wizard.Prompt, "ask", return_value=""):
            wizard._step_adopt_pet()

        from core.pet.storage import PetStorage
        pet = PetStorage().load()
        assert pet is not None
        assert pet.name == "小林同学"

    def test_adopt_new_pet_with_custom_name(self, tmp_path, monkeypatch):
        """自定义宠物名。"""
        monkeypatch.setattr(wizard.settings, "storage_path", tmp_path)

        with patch.object(wizard.Prompt, "ask", return_value="小花"):
            wizard._step_adopt_pet()

        from core.pet.storage import PetStorage
        pet = PetStorage().load()
        assert pet is not None
        assert pet.name == "小花"

    def test_existing_pet_skip_overwrite(self, tmp_path, monkeypatch):
        """已有宠物且选择不重新领养时保留原宠物。"""
        monkeypatch.setattr(wizard.settings, "storage_path", tmp_path)

        # 先创建一个宠物
        from core.pet.pet import Pet
        from core.pet.storage import PetStorage
        PetStorage().save(Pet(name="原宠物"))

        # 用户选择 n
        with patch.object(wizard.Prompt, "ask", return_value="n"):
            wizard._step_adopt_pet()

        pet = PetStorage().load()
        assert pet.name == "原宠物"


# ============================================================
# _step_choose_persona 测试
# ============================================================

class TestStepChoosePersona:
    """测试人格选择步骤。"""

    @pytest.mark.parametrize("choice", ["scholar", "warrior", "artisan", "auto"])
    def test_each_persona_can_be_selected(self, tmp_path, monkeypatch, choice):
        """四种人格风格都能被正确保存。"""
        monkeypatch.setattr(wizard.settings, "storage_path", tmp_path)

        with patch.object(wizard.Prompt, "ask", return_value=choice):
            wizard._step_choose_persona()

        from core.memory.store import MemoryStore
        from core.memory.profile import ProfileManager
        pm = ProfileManager(MemoryStore())
        profile = pm.get_profile()
        assert profile.preferred_style == choice

    def test_default_is_scholar(self, tmp_path, monkeypatch):
        """默认人格是 scholar。"""
        monkeypatch.setattr(wizard.settings, "storage_path", tmp_path)

        # Prompt.ask 返回 default 值时传 default="scholar"
        def fake_ask(prompt, **kwargs):
            return kwargs.get("default", "")
        with patch.object(wizard.Prompt, "ask", side_effect=fake_ask):
            wizard._step_choose_persona()

        from core.memory.store import MemoryStore
        from core.memory.profile import ProfileManager
        pm = ProfileManager(MemoryStore())
        assert pm.get_profile().preferred_style == "scholar"


# ============================================================
# _step_generate_memory 测试
# ============================================================

class TestStepGenerateMemory:
    """测试 IMA.md 生成。"""

    def test_generates_ima_md(self, tmp_path, monkeypatch):
        """生成 IMA.md 文件且包含关键章节。"""
        monkeypatch.setattr(wizard, "PROJECT_ROOT", tmp_path)
        monkeypatch.setattr(wizard.settings, "storage_path", tmp_path)

        wizard._step_generate_memory()

        md_path = tmp_path / "IMA.md"
        assert md_path.exists()
        content = md_path.read_text(encoding="utf-8")
        assert "IMA 知识库项目记忆" in content
        assert "配置摘要" in content
        assert "使用指南" in content
        assert "项目结构" in content

    def test_ima_md_reflects_unconfigured_state(self, tmp_path, monkeypatch):
        """未配置 LLM 时 IMA.md 应反映"未配置"状态。"""
        monkeypatch.setattr(wizard, "PROJECT_ROOT", tmp_path)
        monkeypatch.setattr(wizard.settings, "storage_path", tmp_path)
        # 确保未配置 LLM
        monkeypatch.delenv("AGNES_API_KEY", raising=False)
        # 让 has_llm 返回 False
        with patch.object(wizard.settings, "has_llm", return_value=False):
            wizard._step_generate_memory()

        content = (tmp_path / "IMA.md").read_text(encoding="utf-8")
        assert "未配置" in content or "仅搜索" in content

    def test_ima_md_reflects_configured_state(self, tmp_path, monkeypatch):
        """已配置 LLM 时 IMA.md 应包含模型名。"""
        monkeypatch.setattr(wizard, "PROJECT_ROOT", tmp_path)
        monkeypatch.setattr(wizard.settings, "storage_path", tmp_path)
        monkeypatch.setattr(wizard.settings, "llm_model", "test-model")
        with patch.object(wizard.settings, "has_llm", return_value=True):
            wizard._step_generate_memory()

        content = (tmp_path / "IMA.md").read_text(encoding="utf-8")
        assert "test-model" in content

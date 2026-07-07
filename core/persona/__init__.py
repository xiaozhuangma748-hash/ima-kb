"""人格层：分系风格 + system prompt 模板。"""
from core.persona.prompts import build_system_prompt
from core.persona.styles import STYLE_DESCRIPTIONS

__all__ = ["build_system_prompt", "STYLE_DESCRIPTIONS"]

"""自动标签生成器：调用 LLM 给文档打主题标签。

流程：
1. 输入文档标题 + 前 N 字内容（节省 token）
2. LLM 输出 3-5 个主题标签
3. 解析返回，规整为字符串列表

设计要点：
- 用低 temperature（0.2）保证稳定
- max_tokens 设小（128）避免浪费
- 提示词强制 JSON 数组格式，便于解析
- 失败时返回空列表，不阻塞入库
"""
from __future__ import annotations

import json
import re
from typing import List, Optional

from core.llm.client import get_llm, LLMError
from core.ingestion.parser import ParsedDocument


# 标签生成提示词
TAGGER_SYSTEM_PROMPT = """你是一个文档分类专家。请为给定的文档生成 3-5 个主题标签。

要求：
1. 标签必须反映文档的核心主题、领域、用途
2. 标签简洁（2-6 个字），中文为主，必要时可用英文（如代码类）
3. 优先使用通用分类词，如"殡葬政策"、"项目方案"、"财务报表"、"代码示例"
4. 严格输出 JSON 数组格式，不要任何其他文字
5. 标签数量 3-5 个，不要多于 5 个

示例输出：
["殡葬政策","奖补标准","杭州市"]
["代码示例","向量检索","Python"]
"""

TAGGER_USER_TEMPLATE = """文档标题：{title}
文档类型：{file_type}
内容前 800 字：
{content_preview}

请生成 3-5 个主题标签（JSON 数组格式）："""


# 用于提取标签的最大内容长度（字符数）
MAX_CONTENT_PREVIEW = 800


class Tagger:
    """自动标签生成器。"""

    def __init__(self) -> None:
        self.llm = get_llm()

    def generate_tags(
        self,
        title: str,
        file_type: str,
        content: str,
    ) -> List[str]:
        """为文档生成主题标签。

        Args:
            title: 文档标题
            file_type: 文件类型（扩展名）
            content: 文档内容（只取前 800 字）

        Returns:
            标签列表（3-5 个），失败时返回空列表
        """
        content_preview = content[:MAX_CONTENT_PREVIEW].strip()
        if not content_preview:
            return []

        user_prompt = TAGGER_USER_TEMPLATE.format(
            title=title,
            file_type=file_type,
            content_preview=content_preview,
        )

        try:
            raw = self.llm.chat(
                messages=[
                    {"role": "system", "content": TAGGER_SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0.2,
                max_tokens=128,
            )
        except LLMError:
            return []

        return self._parse_tags(raw)

    def generate_tags_for_document(self, parsed: ParsedDocument) -> List[str]:
        """为 ParsedDocument 生成标签（便捷方法）。"""
        return self.generate_tags(
            title=parsed.title,
            file_type=parsed.file_type,
            content=parsed.text,
        )

    @staticmethod
    def _parse_tags(raw: str) -> List[str]:
        """从 LLM 输出解析标签列表。

        支持几种格式：
        - ["标签1","标签2"]    （标准 JSON）
        - 标签1,标签2,标签3     （逗号分隔）
        - 标签1 标签2 标签3     （空格分隔）
        """
        if not raw:
            return []

        raw = raw.strip()

        # 1. 尝试解析 JSON 数组
        try:
            tags = json.loads(raw)
            if isinstance(tags, list):
                return [str(t).strip() for t in tags if str(t).strip()][:5]
        except json.JSONDecodeError:
            pass

        # 2. 尝试从文本中提取 JSON 数组
        match = re.search(r'\[[^\]]*\]', raw, re.DOTALL)
        if match:
            try:
                tags = json.loads(match.group())
                if isinstance(tags, list):
                    return [str(t).strip() for t in tags if str(t).strip()][:5]
            except json.JSONDecodeError:
                pass

        # 3. 退而求其次：按逗号/顿号/空格分隔
        # 去掉常见的前缀（如"标签："）
        raw = re.sub(r'^(标签|tags|分类)[：:\s]*', '', raw, flags=re.IGNORECASE)
        parts = re.split(r'[,，、\s]+', raw)
        tags = [p.strip().strip('"\'""'')') for p in parts if p.strip()]
        return tags[:5]


# 模块级单例（首次访问时创建）
_tagger: Optional[Tagger] = None


def get_tagger() -> Tagger:
    """获取 Tagger 单例。"""
    global _tagger
    if _tagger is None:
        _tagger = Tagger()
    return _tagger

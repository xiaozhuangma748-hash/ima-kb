"""跨会话记忆自动提取器。

每轮对话结束后，调用 LLM 分析本轮对话（用户问题 + AI 回答），
提取值得跨会话记住的信息：用户偏好、关注主题、未解决问题、关键事实。

设计要点：
- 用 JSON 格式约束 LLM 输出，便于解析
- 低温度（0.1）保证稳定性
- 小 max_tokens（300）控制成本
- 解析失败静默降级，不影响主流程
- 提取结果交给 CrossSessionMemory.merge_extraction 去重合并
"""
from __future__ import annotations

import json
import logging
import re
from typing import TYPE_CHECKING, Dict, List, Optional

from core.memory.cross_session import CrossSessionMemory

if TYPE_CHECKING:
    from core.llm.client import LLMClient

logger = logging.getLogger(__name__)


# 提取 prompt：明确四类记忆的定义 + 输出格式
_EXTRACT_PROMPT = """你是一个记忆提取器。分析下面这轮对话，提取值得跨会话长期记住的信息。

## 四类记忆

1. **用户偏好**：用户的使用习惯、格式偏好、工作方式（如"喜欢表格输出"、"用中文"、"偏好学者风格"）
2. **关注主题**：用户长期关注的领域/话题（如"殡葬政策"、"骨灰安置"、"生态安葬"）
3. **未解决问题**：用户提出但 AI 没完全回答、或需要后续跟进的问题
4. **关键事实**：重要的、跨会话都需要记住的事实（如"项目服务于拱墅区"、"用户是民政部门工作人员"）

## 提取原则

- 只提取**明确**或**强烈暗示**的信息，不要猜测
- 偏好要用"键:值"格式，键简洁（如"格式"、"语言"、"风格"）
- 主题是名词短语，2-6 个字
- 问题是完整问句
- 事实是陈述句
- 如果本轮对话没有值得记忆的内容，返回全空

## 输出格式（严格 JSON）

```json
{
  "preferences": {"键": "值"},
  "topics": ["主题1"],
  "questions": ["问题1"],
  "facts": ["事实1"]
}
```

空值用空数组/空对象。不要输出 JSON 以外的内容。"""


class MemoryExtractor:
    """跨会话记忆自动提取器。"""

    def __init__(self, llm: "LLMClient", memory: CrossSessionMemory) -> None:
        self.llm = llm
        self.memory = memory

    def extract_and_merge(
        self,
        user_input: str,
        assistant_reply: str,
    ) -> Dict[str, List[str]]:
        """提取一轮对话的记忆并合并到 CrossSessionMemory。

        Args:
            user_input: 用户本轮输入
            assistant_reply: AI 本轮回复

        Returns:
            新增项清单（同 merge_extraction 的返回格式）。
            提取失败返回空字典（四类均为空列表）。
        """
        # 构造对话内容
        dialogue = f"用户: {user_input}\n\nAI: {assistant_reply}"

        messages = [
            {"role": "system", "content": _EXTRACT_PROMPT},
            {"role": "user", "content": dialogue},
        ]

        try:
            raw = self.llm.chat(
                messages,
                temperature=0.1,    # 低温度保证稳定
                max_tokens=300,     # 提取结果不会很长
                max_retries=1,      # 提取失败不重试，快速降级
            )
        except Exception as e:
            logger.debug(f"记忆提取 LLM 调用失败: {e}")
            return {"preferences": [], "topics": [], "questions": [], "facts": []}

        # 解析 JSON（LLM 可能输出带 markdown 代码块）
        extraction = self._parse_json(raw)
        if not extraction:
            return {"preferences": [], "topics": [], "questions": [], "facts": []}

        # 类型校验 + 合并
        preferences = extraction.get("preferences", {})
        topics = extraction.get("topics", [])
        questions = extraction.get("questions", [])
        facts = extraction.get("facts", [])

        # 类型安全：确保 preferences 是 dict，其他是 list
        if not isinstance(preferences, dict):
            preferences = {}
        if not isinstance(topics, list):
            topics = [topics] if isinstance(topics, str) else []
        if not isinstance(questions, list):
            questions = [questions] if isinstance(questions, str) else []
        if not isinstance(facts, list):
            facts = [facts] if isinstance(facts, str) else []

        # 过滤掉非字符串元素
        topics = [str(t) for t in topics if t]
        questions = [str(q) for q in questions if q]
        facts = [str(f) for f in facts if f]
        preferences = {str(k): str(v) for k, v in preferences.items() if k and v}

        return self.memory.merge_extraction(
            preferences=preferences,
            topics=topics,
            questions=questions,
            facts=facts,
        )

    @staticmethod
    def _parse_json(raw: str) -> Optional[dict]:
        """解析 LLM 输出的 JSON，兼容 markdown 代码块包裹。

        Args:
            raw: LLM 原始输出

        Returns:
            解析后的字典，失败返回 None
        """
        if not raw:
            return None

        # 尝试提取 ```json ... ``` 代码块
        m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", raw, re.DOTALL)
        if m:
            raw = m.group(1)
        else:
            # 尝试直接找第一个 { ... } 块
            m = re.search(r"\{.*\}", raw, re.DOTALL)
            if m:
                raw = m.group(0)

        try:
            result = json.loads(raw)
            return result if isinstance(result, dict) else None
        except (json.JSONDecodeError, ValueError) as e:
            logger.debug(f"记忆提取 JSON 解析失败: {e}, raw={raw[:200]}")
            return None

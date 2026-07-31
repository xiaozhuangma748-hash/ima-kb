"""Self-RAG 答案自我验证模块。

在 RAGChain 生成答案后，调用 LLM 逐句验证答案是否被检索资料支持：
- 有依据的句子保留
- 无依据的句子（幻觉）标注 "⚠️ 未经资料支持"
- LLM 调用失败时跳过验证，保留原答案（不破坏现有流程）

参考论文：Self-RAG (Asai et al., 2023.10, arXiv:2310.11511)
本项目用 Prompt 工程版，不训练专门模型。
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from typing import List, Optional

logger = logging.getLogger(__name__)


# ============================================================
# 数据结构
# ============================================================

@dataclass
class VerificationResult:
    """验证结果。"""
    has_hallucination: bool  # 是否检测到幻觉
    verified_answer: str  # 验证后的答案（幻觉句子已标注）
    needs_regenerate: bool = False  # 是否需要重新生成（默认 False，只标注）
    hallucinated_sentences: List[str] = field(default_factory=list)


# ============================================================
# 裁判 Prompt
# ============================================================

_VERIFY_SYSTEM_PROMPT = """你是一个严格的答案验证员。请逐句检查"答案"中的每个句子是否被"参考资料"支持。

判定规则：
- grounded=true：该句子的信息能在参考资料中找到依据（可 paraphrase）
- grounded=false：该句子的信息在参考资料中找不到依据（幻觉/编造）
- citation：该句子依据来自第几条参考资料（1-based），无依据时为 null

只输出 JSON，格式：
{
  "sentences": [
    {"text": "句子原文", "grounded": true/false, "citation": 1 或 null}
  ],
  "has_hallucination": true/false
}
"""


def build_verify_messages(
    question: str,
    answer: str,
    snippets: List[str],
) -> List[dict]:
    """构造验证 LLM 的 messages。"""
    snippets_text = "\n---\n".join(
        f"[{i+1}] {s[:400]}" for i, s in enumerate(snippets[:5])
    )
    user_content = f"""## 问题
{question}

## 答案（需逐句验证）
{answer}

## 参考资料
{snippets_text}

请逐句验证答案，只输出 JSON。"""
    return [
        {"role": "system", "content": _VERIFY_SYSTEM_PROMPT},
        {"role": "user", "content": user_content},
    ]


# ============================================================
# 解析裁判返回
# ============================================================

def parse_verify_response(raw: str) -> Optional[dict]:
    """解析 LLM 验证返回的 JSON。

    支持纯 JSON 和 ```json 代码块。
    解析失败返回 None（调用方应跳过验证，保留原答案）。
    """
    if not raw:
        return None
    text = raw.strip()
    # 提取 ```json ... ``` 代码块
    fence_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if fence_match:
        text = fence_match.group(1)
    # 提取 JSON 对象
    json_match = re.search(r"\{.*\}", text, re.DOTALL)
    if json_match:
        text = json_match.group(0)
    try:
        data = json.loads(text)
        if "sentences" not in data or "has_hallucination" not in data:
            return None
        return {
            "sentences": data["sentences"],
            "has_hallucination": bool(data["has_hallucination"]),
        }
    except (json.JSONDecodeError, ValueError, TypeError):
        return None


# ============================================================
# 标注幻觉句子
# ============================================================

def mark_ungrounded_sentences(sentences: List[dict]) -> str:
    """构造验证后的答案文本，给幻觉句子加 ⚠️ 标注。

    Args:
        sentences: [{"text": "...", "grounded": true/false, "citation": 1 或 null}]

    Returns:
        验证后的答案文本（幻觉句子标注 ⚠️）
    """
    parts = []
    for s in sentences:
        text = s.get("text", "")
        grounded = s.get("grounded", True)
        if grounded:
            parts.append(text)
        else:
            parts.append(f"{text} ⚠️ 未经资料支持")
    return "".join(parts)


# ============================================================
# SelfVerifier 主类
# ============================================================

class SelfVerifier:
    """Self-RAG 答案验证器。

    用法：
        verifier = SelfVerifier(llm=get_llm())
        result = verifier.verify(question, answer, snippets)
        if result is not None:
            answer = result.verified_answer  # 用验证后的答案替换
    """

    def __init__(
        self,
        llm,
        enabled: bool = True,
        max_retries: int = 0,  # 默认 0 = 只标注不重生成
    ) -> None:
        self.llm = llm
        self.enabled = enabled
        self.max_retries = max_retries

    def verify(
        self,
        question: str,
        answer: str,
        snippets: List[str],
    ) -> Optional[VerificationResult]:
        """验证答案是否被资料支持。

        Args:
            question: 用户问题
            answer: LLM 生成的答案
            snippets: 检索到的资料片段

        Returns:
            VerificationResult，或 None（验证跳过/失败时）
        """
        if not self.enabled:
            return None
        if not answer.strip() or not snippets:
            return None

        try:
            messages = build_verify_messages(question, answer, snippets)
            raw = self.llm.chat(messages, temperature=0.0, max_tokens=400)
        except Exception as e:
            logger.warning(f"Self-RAG 验证 LLM 调用失败，跳过: {e}")
            return None

        parsed = parse_verify_response(raw)
        if parsed is None:
            logger.warning("Self-RAG 验证返回解析失败，跳过")
            return None

        sentences = parsed["sentences"]
        has_halluc = parsed["has_hallucination"]
        verified = mark_ungrounded_sentences(sentences) if has_halluc else answer
        hallucinated = [s["text"] for s in sentences if not s.get("grounded", True)]

        return VerificationResult(
            has_hallucination=has_halluc,
            verified_answer=verified,
            needs_regenerate=False,  # 默认只标注不重生成
            hallucinated_sentences=hallucinated,
        )

"""Agentic RAG 反思模块。

在 RAGChain 生成答案后判断是否需要重检索：
- Self-RAG 检测到幻觉 → 重检索
- 答案含"无法回答"但检索结果有相关资料（max_score 高）→ 重检索
- 达到最大轮次或低置信度无资料 → 不重试

重检索时调用 LLM 反思改写 query，失败回退原 query。

参考：Agentic RAG 模式（Self-RAG 的迭代版，多轮检索+反思）
"""
from __future__ import annotations

import logging
from typing import Optional

logger = logging.getLogger(__name__)


# ============================================================
# 反思判断
# ============================================================

def should_retry(
    question: str,
    answer: str,
    verify_result,
    max_score: float,
    round_num: int,
    max_rounds: int,
    reject_threshold: float = 0.15,
) -> bool:
    """判断是否应该重检索一次。

    Args:
        question: 用户问题
        answer: 当前答案
        verify_result: Self-RAG 验证结果（None 表示未验证）
        max_score: 检索结果最高分
        round_num: 当前轮次（1-based）
        max_rounds: 最大轮次
        reject_threshold: 拒答阈值（低于此值说明无相关资料）

    Returns:
        True 如果应该重检索
    """
    # 1. 达到最大轮次，不重试
    if round_num >= max_rounds:
        return False

    # 2. Self-RAG 检测到幻觉，重检索
    if verify_result is not None and getattr(verify_result, "has_hallucination", False):
        return True

    # 3. 答案含"无法回答"但检索结果有相关资料（max_score 高于拒答阈值）
    #    说明知识库里有相关内容，但第一轮没答好，值得重试
    if answer and "无法回答" in answer and max_score >= reject_threshold:
        return True

    return False


# ============================================================
# 反思 Prompt
# ============================================================

_REFLECT_SYSTEM_PROMPT = """你是一个检索反思员。系统之前检索到的资料不足以回答用户问题，请反思并改写检索 query 以获取更准确的信息。

改写策略：
1. 提取问题中的关键实体和动作
2. 用同义词或更具体的术语替换
3. 去掉无关的修饰词
4. 只输出改写后的 query，不要解释，不要加引号

示例：
- 问题"海葬怎么办理？" + 之前答案无法回答 → 改写为"海葬 申请流程 材料"
- 问题"补贴多少钱？" + 之前答案无法回答 → 改写为"殡葬 补贴 标准 金额"
"""


def reflect_and_rewrite_query(
    question: str,
    previous_answer: str,
    issues: str,
    llm,
) -> str:
    """LLM 反思改写 query。

    Args:
        question: 原始用户问题
        previous_answer: 上一轮的答案（含问题说明）
        issues: 上一轮发现的问题（如"答案无法回答"、"有幻觉"等）
        llm: LLM 客户端（需有 chat 方法）

    Returns:
        改写后的 query，或原 question（LLM 失败/返回空时）
    """
    user_content = f"""## 原始问题
{question}

## 上一轮答案
{previous_answer}

## 问题
{issues}

请改写检索 query（只输出 query 本身）："""

    messages = [
        {"role": "system", "content": _REFLECT_SYSTEM_PROMPT},
        {"role": "user", "content": user_content},
    ]

    try:
        new_query = llm.chat(messages, temperature=0.0, max_tokens=100)
        new_query = (new_query or "").strip()
        # 去掉可能的引号包裹
        if len(new_query) >= 2:
            if (new_query[0] == '"' and new_query[-1] == '"') or \
               (new_query[0] == "'" and new_query[-1] == "'"):
                new_query = new_query[1:-1].strip()
        if not new_query:
            return question
        return new_query
    except Exception as e:
        logger.warning(f"Agentic RAG 反思 LLM 调用失败，回退原 query: {e}")
        return question

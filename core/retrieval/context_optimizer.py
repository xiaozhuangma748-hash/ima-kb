"""上下文优化：Lost in Middle 重排 + Context 压缩。

## Lost in Middle 重排

论文 "Lost in the Middle: How Language Models Use Long Contexts" (Liu et al., 2023)
指出：LLM 对 prompt 开头和结尾的信息关注度更高，中间部分容易被忽略。

策略：把最相关的 chunk 放在开头和结尾，最不相关的放中间。
- 已排序 [r0, r1, r2, r3, r4]（r0 最相关）
- 重排为 [r0, r2, r4, r3, r1]（最相关在两端，递减向中间）

## Context 压缩

对过长的 chunk content 做截断，保留开头和结尾的关键信息。
- 超过 max_chars 时：保留前半 + "..." + 后半
- 避免单个 chunk 占用过多 token，让 LLM 能看到更多来源

集成点：_build_user_prompt 中调用。
"""
from __future__ import annotations

from typing import List, TypeVar

T = TypeVar("T")


def reorder_lost_in_middle(results: List[T]) -> List[T]:
    """Lost in Middle 重排：最相关的放两端，最不相关的放中间。

    蛇形排列策略：
    - 偶数索引（0, 2, 4...）的结果放在前半部分
    - 奇数索引（1, 3, 5...）的结果逆序放在后半部分
    - 结果：[r0, r2, r4, ..., r5, r3, r1]

    Args:
        results: 已按相关度降序排列的结果列表

    Returns:
        重排后的列表（新列表，不修改原列表）
    """
    if len(results) <= 2:
        # 1-2 个结果无需重排
        return list(results)

    # 分离偶数索引和奇数索引
    even = [results[i] for i in range(0, len(results), 2)]   # r0, r2, r4...
    odd = [results[i] for i in range(1, len(results), 2)]    # r1, r3, r5...

    # 奇数索引逆序后追加到偶数后面
    # [r0, r2, r4] + [r5, r3, r1] = [r0, r2, r4, r5, r3, r1]
    return even + list(reversed(odd))


def compress_context(content: str, max_chars: int = 800) -> str:
    """压缩过长的 context：保留开头和结尾，中间用省略号。

    Args:
        content: 原始文本
        max_chars: 最大字符数，超过时截断

    Returns:
        压缩后的文本（不超过 max_chars 字符）
    """
    if not content or max_chars <= 0 or len(content) <= max_chars:
        return content

    # 保留前半和后半
    half = max_chars // 2
    prefix = content[:half]
    suffix = content[-half:]
    return f"{prefix}\n...\n{suffix}"


def compress_results(
    results: List,
    max_chars: int = 800,
    fields: List[str] = None,
) -> List:
    """批量压缩结果列表中每个结果的 content 字段。

    原地修改 results 中每个元素的 content。

    Args:
        results: HybridResult 或类似对象列表
        max_chars: 每个结果 content 的最大字符数
        fields: 要压缩的字段名列表（默认只压 content）

    Returns:
        同一列表对象（content 已压缩）
    """
    if not results or max_chars <= 0:
        return results

    fields = fields or ["content"]
    for r in results:
        for field_name in fields:
            val = getattr(r, field_name, None)
            if isinstance(val, str):
                setattr(r, field_name, compress_context(val, max_chars))

    return results

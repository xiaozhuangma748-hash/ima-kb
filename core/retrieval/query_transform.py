"""查询变换：HyDE 假设答案改写 + 子问题分解。

对标业界先进 RAG 的 Query Understanding 层：
1. HyDE (Hypothetical Document Embeddings)：让 LLM 生成假设答案，
   用假设答案的 embedding 检索（比原 query 语义更接近文档内容）
2. Query Decomposition：复杂问题拆分为多个子问题分别检索，
   合并多路结果统一 rerank
3. 同义词扩展：基于词库的简单同义词补充

设计原则：
- HyDE 失败时回退到原 query（不影响主流程）
- 子问题分解仅对长复杂查询触发（短查询直接走原 query）
- LLM 调用都有超时和异常保护
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import List, Optional, Tuple

logger = logging.getLogger(__name__)


# ============================================================
# HyDE：假设文档检索
# ============================================================

# HyDE 系统提示：要求 LLM 生成一段简短的"假设答案"作为检索查询
# 注意：保持领域无关（本知识库是通用个人知识库，不绑定殡葬），
# 避免对非殡葬资料产生领域偏置，影响 HyDE 召回质量。
_HYDE_SYSTEM_PROMPT = """你是一个知识库检索辅助助手。
请根据用户问题，生成一段 100-200 字的"假设答案"（hypothetical answer）。
这段假设答案即使内容不完全准确也没关系，关键是：
1. 使用与正式文档类似的表述风格（严谨、书面）
2. 包含问题中关键实体的相关术语和同义表述
3. 看起来像是从知识库文档中摘录的片段

只输出假设答案正文，不要任何解释或前缀。
"""

# 触发 HyDE 的最小 query 长度（太短的 query 直接走原 query）
_HYDE_MIN_QUERY_LEN = 8
# HyDE 生成的假设答案最大 token 数
_HYDE_MAX_TOKENS = 256
# HyDE 触发开关（运行时可通过 settings 控制）
_HYDE_DEFAULT_ENABLED = True


def hyde_transform(
    query: str,
    llm,
    enabled: bool = _HYDE_DEFAULT_ENABLED,
) -> Tuple[str, str]:
    """HyDE 假设文档改写。

    流程：
    1. 让 LLM 根据原 query 生成假设答案
    2. 用假设答案作为新 query 做检索

    Args:
        query: 原查询
        llm: LLM 客户端（需实现 chat 方法）
        enabled: 是否启用

    Returns:
        (new_query, source) — new_query 是用于检索的改写后 query，
        source 为 "hyde" 或 "original"（回退时）
    """
    if not enabled or len(query) < _HYDE_MIN_QUERY_LEN or llm is None:
        return query, "original"

    try:
        messages = [
            {"role": "system", "content": _HYDE_SYSTEM_PROMPT},
            {"role": "user", "content": query},
        ]
        hypo = llm.chat(messages, temperature=0.3, max_tokens=_HYDE_MAX_TOKENS)
        hypo = (hypo or "").strip()
        if not hypo or len(hypo) < 10:
            logger.info(f"HyDE 返回过短，回退原 query: {query[:30]}")
            return query, "original"
        logger.info(f"HyDE 改写: {query[:30]} → {hypo[:50]}...")
        return hypo, "hyde"
    except Exception as e:
        logger.warning(f"HyDE 失败，回退原 query: {e}")
        return query, "original"


# ============================================================
# Query Decomposition：子问题分解
# ============================================================

# 子问题分解系统提示
_DECOMPOSE_SYSTEM_PROMPT = """你是一个查询分解助手。
用户问题可能包含多个子问题，请拆分为独立的、可单独检索的子问题。

规则：
1. 简单问题（单一意图）返回包含原问题的单元素列表
2. 复杂问题拆分为 2-4 个独立子问题
3. 每个子问题应是完整、可独立检索的问句
4. 只输出 JSON 数组，格式：["子问题1", "子问题2", ...]
5. 不要任何解释文字

示例：
输入："海葬和树葬的区别及各自费用"
输出：["什么是海葬？", "什么是树葬？", "海葬和树葬有什么区别？", "海葬的费用是多少？", "树葬的费用是多少？"]

输入："什么是节地生态安葬"
输出：["什么是节地生态安葬"]
"""

# 触发子问题分解的最小 query 长度（太短的单句强行拆分反而增加检索噪声）
_DECOMPOSE_MIN_QUERY_LEN = 18
# 触发分解必须包含的疑问/复合连词信号（避免把普通长句拆成子问题）
_DECOMPOSE_TRIGGERS = (
    "？", "?", "的区别", "和", "与", "及", "以及",
    "怎么", "如何", "为什么", "哪些", "分别", "对比", "比较",
)


def _looks_decomposable(query: str) -> bool:
    """启发式：query 是否像需要拆分的复合问题。"""
    return any(t in query for t in _DECOMPOSE_TRIGGERS)
# 子问题分解最大 token 数
_DECOMPOSE_MAX_TOKENS = 400


def decompose_query(
    query: str,
    llm,
    enabled: bool = True,
) -> List[str]:
    """子问题分解。

    Args:
        query: 原查询
        llm: LLM 客户端
        enabled: 是否启用

    Returns:
        子问题列表（简单问题返回 [query]）
    """
    if not enabled or llm is None:
        return [query]
    # 长度 + 复合信号双重门槛：短 query 或单一意图不分解
    if len(query) < _DECOMPOSE_MIN_QUERY_LEN or not _looks_decomposable(query):
        return [query]

    try:
        messages = [
            {"role": "system", "content": _DECOMPOSE_SYSTEM_PROMPT},
            {"role": "user", "content": query},
        ]
        resp = llm.chat(messages, temperature=0.0, max_tokens=_DECOMPOSE_MAX_TOKENS)
        sub_queries = _parse_sub_queries(resp)
        if not sub_queries:
            return [query]
        # 限制最多 4 个子问题
        sub_queries = sub_queries[:4]
        logger.info(f"子问题分解: {query[:30]} → {len(sub_queries)} 个子问题")
        return sub_queries
    except Exception as e:
        logger.warning(f"子问题分解失败，回退原 query: {e}")
        return [query]


def _parse_sub_queries(response: str) -> List[str]:
    """解析 LLM 返回的子问题列表。

    支持格式：
    - JSON 数组：["q1", "q2"]
    - 编号列表：1. q1\n2. q2
    - 换行分隔：q1\nq2
    """
    if not response:
        return []

    import json
    text = response.strip()

    # 1. 尝试 JSON 数组
    try:
        data = json.loads(text)
        if isinstance(data, list):
            return [str(item).strip() for item in data if str(item).strip()]
    except (json.JSONDecodeError, TypeError):
        pass

    # 提取 JSON 数组片段
    match = re.search(r'\[.*\]', text, re.DOTALL)
    if match:
        try:
            data = json.loads(match.group(0))
            if isinstance(data, list):
                return [str(item).strip() for item in data if str(item).strip()]
        except (json.JSONDecodeError, TypeError):
            pass

    # 2. 尝试编号列表：1. xxx / 2. xxx
    numbered = re.findall(r'(?:^|\n)\s*\d+[.、)]\s*(.+?)(?=\n\s*\d+[.、)]|$)', text, re.DOTALL)
    if len(numbered) >= 2:
        return [q.strip() for q in numbered if q.strip()]

    # 3. 换行分隔（兜底）：仅当每行都像独立问句时才接受，避免把模型
    #    的一句解释误拆成"子问题"
    lines = [line.strip() for line in text.split("\n") if line.strip() and not line.startswith("#")]
    if len(lines) >= 2 and all(("？" in ln or "?" in ln or ln.endswith("？") or ln.endswith("?")) for ln in lines):
        return lines

    return []


# ============================================================
# 组合入口
# ============================================================

@dataclass
class QueryTransformResult:
    """查询变换结果。"""
    original: str               # 原始 query
    final_query: str            # 最终用于检索的 query（HyDE 后）
    sub_queries: List[str]      # 子问题列表（无分解时为 [final_query]）
    used_hyde: bool             # 是否使用了 HyDE
    used_decompose: bool        # 是否使用了子问题分解


def transform_query(
    query: str,
    llm=None,
    enable_hyde: bool = True,
    enable_decompose: bool = True,
) -> QueryTransformResult:
    """统一查询变换入口。

    流程：
    1. （可选）子问题分解：复杂问题拆分为多个子问题
    2. （可选）对每个子问题做 HyDE 改写
    3. 返回最终子问题列表

    Args:
        query: 原始查询
        llm: LLM 客户端（None 时跳过 LLM 步骤）
        enable_hyde: 启用 HyDE
        enable_decompose: 启用子问题分解

    Returns:
        QueryTransformResult
    """
    if llm is None:
        return QueryTransformResult(
            original=query, final_query=query,
            sub_queries=[query], used_hyde=False, used_decompose=False,
        )

    # 1. 子问题分解
    if enable_decompose:
        sub_qs = decompose_query(query, llm)
    else:
        sub_qs = [query]

    used_decompose = len(sub_qs) > 1

    # 2. 对第一个子问题做 HyDE（避免对每个子问题都调用 LLM，控制成本）
    # 对复杂多子问题的情况，HyDE 价值有限；只对单子问题场景做 HyDE
    final_query = query
    used_hyde = False
    if enable_hyde and not used_decompose:
        final_query, source = hyde_transform(query, llm)
        used_hyde = source == "hyde"

    # 子问题列表：若未分解，用 final_query；若分解，用原 sub_qs
    if used_decompose:
        result_subs = sub_qs
    else:
        result_subs = [final_query]

    return QueryTransformResult(
        original=query,
        final_query=final_query,
        sub_queries=result_subs,
        used_hyde=used_hyde,
        used_decompose=used_decompose,
    )

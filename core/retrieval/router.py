"""查询路由：根据查询意图决定是否需要走知识库检索。

核心思想：不是所有问题都需要 RAG 检索。
- 闲聊/问候/感谢 → 直接 LLM（跳过检索，省 1-5s）
- 知识查询     → 走完整 RAG 流水线

分流策略（按优先级）：
1. 问候/闲聊：短文本 + 问候关键词 → 'greeting'
2. 元问题：询问 AI 自身能力/状态 → 'chat'
3. 知识查询：含政策/规定/标准/流程等关键词 → 'knowledge'
4. 闲聊确认词：短文本精确匹配（好的/嗯/ok 等）→ 'chat'
5. 语义路由（可选）：用 embedding 相似度与意图原型比较，解决模糊查询
6. 默认：未知意图走知识查询（保守，不漏答）

升级点（v4.1）：
- 新增 route_query_with_embedding：用 query embedding 与预定义意图原型
  embedding 计算 cosine 相似度，解决"骨灰怎么处理"等不含知识关键词的查询
- 原关键词路由保留作为快速路径（无 LLM 调用，零延迟）
- 语义路由仅在关键词路由不确定时触发
"""
from __future__ import annotations

import logging
import re
from typing import Literal, Optional, Tuple

logger = logging.getLogger(__name__)

QueryType = Literal["chat", "knowledge", "greeting"]


# 问候/闲聊关键词（短文本匹配）
_GREETING_KEYWORDS = {
    "你好", "您好", "在吗", "在不在", "谢谢", "感谢", "thanks", "thank you",
    "hi", "hello", "hey", "嗨", "哈喽", "再见", "bye", "goodbye",
    "早上好", "下午好", "晚上好", "早安", "晚安",
}

# 闲聊确认词（短文本精确匹配，跳过检索以省时）
_CHAT_SHORT = {
    "好的", "好", "嗯", "嗯嗯", "哦", "啊", "是的", "不是", "对", "不对",
    "ok", "okay", "yes", "no", "好吧", "行", "可以", "收到", "明白",
    "了解", "知道了", "嗯哼", "噢", "诶",
}

# 元问题关键词（询问 AI 自身能力）
_META_KEYWORDS = {
    "你是谁", "你叫什么", "你能做什么", "你会什么", "你的功能",
    "你是ai", "你是机器人", "介绍一下你自己", "你的名字",
    "你是？", "你是?", "你是", "自我介绍",
    "what can you do", "who are you",
}

# 知识查询强信号关键词（命中即走知识库）
_KNOWLEDGE_KEYWORDS = {
    # 政策/规定类
    "政策", "规定", "办法", "条例", "通知", "意见", "方案", "标准", "规范",
    # 流程/操作类
    "流程", "程序", "步骤", "如何", "怎么", "怎样", "办理", "申请", "操作",
    # 查询类
    "什么是", "什么是", "解释", "定义", "含义", "意思", "区别", "对比",
    # 数据类
    "金额", "费用", "价格", "标准", "补贴", "奖补", "减免", "多少",
    "统计", "数据", "比例", "百分比",
    # 时间/地点
    "时间", "期限", "截止", "地点", "地址", "哪里", "哪儿",
    # 实体查询
    "谁", "哪个", "哪些", "名单", "目录", "清单",
    # 英文
    "what", "how", "why", "when", "where", "who", "which",
}


def route_query(query: str) -> QueryType:
    """查询路由：判断查询类型。

    Args:
        query: 用户查询文本

    Returns:
        'chat'      — 闲聊/问候/元问题，跳过检索直接 LLM
        'knowledge' — 知识查询，走完整 RAG 流水线
        'greeting'  — 纯问候（chat 的子类，可特殊处理）
    """
    q = query.strip()
    if not q:
        return "chat"

    qlower = q.lower()

    # 1. 纯问候（短文本 + 问候词）
    if len(q) <= 15:
        for kw in _GREETING_KEYWORDS:
            if kw in qlower:
                return "greeting"

    # 2. 元问题（询问 AI 自身）
    for kw in _META_KEYWORDS:
        if kw in qlower:
            return "chat"

    # 3. 知识查询强信号
    for kw in _KNOWLEDGE_KEYWORDS:
        if kw in q:
            return "knowledge"

    # 4. 短文本闲聊确认词（精确匹配，跳过检索省时）
    if q in _CHAT_SHORT:
        return "chat"

    # 5. 默认走知识库（保守，不漏答；与文件头设计意图一致）
    return "knowledge"


def should_skip_retrieval(query: str) -> bool:
    """便捷方法：是否应跳过检索（直接走 LLM）。"""
    return route_query(query) in ("chat", "greeting")


def should_use_cache(query: str) -> bool:
    """便捷方法：是否应查语义缓存（知识查询才缓存）。"""
    return route_query(query) == "knowledge"


# ============================================================
# 语义路由（v4.1 升级）：embedding 相似度意图分类
# ============================================================

# 意图原型：每类意图预定义几条典型 query，与输入 query 比相似度
_INTENT_PROTOTYPES: dict[str, list[str]] = {
    "greeting": [
        "你好", "您好", "早上好", "下午好", "晚上好",
        "谢谢", "感谢", "再见", "嗨", "哈喽",
    ],
    "chat": [
        "你是谁", "你能做什么", "介绍一下你自己", "你的功能",
        "你是机器人吗", "你会什么", "你的名字",
    ],
    "knowledge": [
        # 政策类
        "殡葬政策", "节地生态安葬规定", "公墓管理办法", "实施方案",
        # 流程类
        "如何办理海葬", "骨灰怎么处理", "申请流程", "办理步骤",
        # 费用类
        "殡葬费用标准", "丧葬费多少", "收费价格",
        # 补贴类
        "丧葬补助金", "抚恤金发放", "奖补标准",
        # 定义类
        "什么是节地生态安葬", "身后一件事是什么",
        # 时效类
        "什么时候实施", "截止日期",
    ],
}

# 意图原型 embedding 缓存（首次使用时计算）
_intent_embeddings: dict[str, list[list[float]]] = {}


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    """计算两个向量的 cosine 相似度。"""
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = sum(x * x for x in a) ** 0.5
    norm_b = sum(y * y for y in b) ** 0.5
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def _get_intent_embeddings(embed_fn) -> dict[str, list[list[float]]]:
    """获取或计算意图原型 embedding（带缓存）。

    Args:
        embed_fn: callable(text) -> List[float]，由 VectorIndex.embed_query 提供

    Returns:
        {intent: [embedding_list, ...]}
    """
    if _intent_embeddings:
        return _intent_embeddings

    for intent, prototypes in _INTENT_PROTOTYPES.items():
        embs = []
        for p in prototypes:
            try:
                e = embed_fn(p)
                if e is not None:
                    embs.append(e)
            except Exception:
                continue
        if embs:
            _intent_embeddings[intent] = embs
            logger.info(f"语义路由：加载 {intent} 意图 {len(embs)} 个原型")

    return _intent_embeddings


def route_query_with_embedding(
    query: str,
    query_embedding: Optional[list[float]] = None,
    embed_fn=None,
    threshold: float = 0.55,
) -> Tuple[QueryType, str]:
    """带 embedding 语义相似度的查询路由。

    流程：
    1. 先走关键词路由（快速路径，零延迟）
    2. 关键词路由返回 'knowledge' 但 query 较短（≤15字）且无强信号时，
       用 embedding 相似度二次判断是否真的知识查询
    3. 若 embedding 显示更像 chat/greeting，覆盖关键词路由结果

    Args:
        query: 用户查询
        query_embedding: 预计算的 query embedding（None 时用 embed_fn 计算）
        embed_fn: embedding 函数（query_embedding 为 None 时使用）
        threshold: 语义相似度阈值，超过则判定为对应意图

    Returns:
        (QueryType, reason) — reason 说明路由依据：
        "keyword" / "semantic" / "default"
    """
    # 1. 快速路径：关键词路由
    keyword_result = route_query(query)

    # 关键词路由结果为 greeting/chat 直接采用
    if keyword_result in ("greeting", "chat"):
        return keyword_result, "keyword"

    # 知识查询的强信号（含明确知识关键词）直接采用
    q = query.strip()
    qlower = q.lower()
    for kw in _KNOWLEDGE_KEYWORDS:
        if kw in q or kw.lower() in qlower:
            return "knowledge", "keyword"

    # 2. 语义路由：对模糊查询做 embedding 相似度判断
    if query_embedding is None and embed_fn is not None:
        try:
            query_embedding = embed_fn(query)
        except Exception as e:
            logger.warning(f"语义路由：query embedding 计算失败: {e}")
            return keyword_result, "default"

    if query_embedding is None:
        # 无 embedding 能力，保留关键词路由结果
        return keyword_result, "default"

    # 计算与各意图原型的最大相似度
    intent_embs = _get_intent_embeddings(embed_fn) if embed_fn else _intent_embeddings
    if not intent_embs:
        return keyword_result, "default"

    best_intent: QueryType = keyword_result
    best_score = 0.0
    for intent, embs in intent_embs.items():
        for e in embs:
            score = _cosine_similarity(query_embedding, e)
            if score > best_score:
                best_score = score
                best_intent = intent  # type: ignore

    # 阈值判断：相似度足够高才覆盖关键词路由
    if best_score >= threshold:
        logger.info(f"语义路由：{query[:20]} → {best_intent} (score={best_score:.3f})")
        return best_intent, "semantic"

    return keyword_result, "default"

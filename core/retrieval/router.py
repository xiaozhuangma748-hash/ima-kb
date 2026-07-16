"""查询路由：根据查询意图决定是否需要走知识库检索。

核心思想：不是所有问题都需要 RAG 检索。
- 闲聊/问候/感谢 → 直接 LLM（跳过检索，省 1-5s）
- 知识查询     → 走完整 RAG 流水线

分流策略（按优先级）：
1. 问候/闲聊：短文本 + 问候关键词 → 'greeting'
2. 元问题：询问 AI 自身能力/状态 → 'chat'
3. 知识查询：含政策/规定/标准/流程等关键词 → 'knowledge'
4. 闲聊确认词：短文本精确匹配（好的/嗯/ok 等）→ 'chat'
5. 默认：未知意图走知识查询（保守，不漏答）
"""
from __future__ import annotations

import re
from typing import Literal

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

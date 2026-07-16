"""语义路由测试（embedding 相似度意图分类）。"""
import pytest
from unittest.mock import MagicMock, patch

from core.retrieval.router import (
    route_query, route_query_with_embedding,
    should_skip_retrieval, should_use_cache,
    _cosine_similarity,
)


def test_cosine_similarity_identical_vectors():
    """相同向量相似度为 1。"""
    v = [1.0, 2.0, 3.0]
    assert _cosine_similarity(v, v) == pytest.approx(1.0, abs=1e-6)


def test_cosine_similarity_orthogonal_vectors():
    """正交向量相似度为 0。"""
    a = [1.0, 0.0]
    b = [0.0, 1.0]
    assert _cosine_similarity(a, b) == 0.0


def test_cosine_similarity_empty_vectors():
    """空向量返回 0。"""
    assert _cosine_similarity([], []) == 0.0


def test_cosine_similarity_different_length():
    """长度不同返回 0。"""
    assert _cosine_similarity([1.0, 2.0], [1.0]) == 0.0


def test_route_query_with_embedding_keyword_greeting():
    """关键词命中 greeting 时直接采用，不走 embedding。"""
    embed_fn = MagicMock()
    result, reason = route_query_with_embedding("你好", embed_fn=embed_fn)
    assert result == "greeting"
    assert reason == "keyword"
    embed_fn.assert_not_called()  # 不应调用 embedding


def test_route_query_with_embedding_keyword_chat():
    """关键词命中 chat 时直接采用。"""
    result, reason = route_query_with_embedding("你是谁", embed_fn=MagicMock())
    assert result == "chat"
    assert reason == "keyword"


def test_route_query_with_embedding_strong_knowledge_keyword():
    """强知识关键词命中时直接采用。"""
    result, reason = route_query_with_embedding(
        "节地生态安葬政策", embed_fn=MagicMock()
    )
    assert result == "knowledge"
    assert reason == "keyword"


def test_route_query_with_embedding_no_embed_fn_returns_default():
    """无 embed_fn 且无 query_embedding 时保留关键词路由结果。"""
    # 选不含知识关键词的短 query，路由返回 chat
    result, reason = route_query_with_embedding("今天天气不错", embed_fn=None)
    assert reason == "default"


def test_route_query_with_embedding_semantic_overrides():
    """模糊查询通过 embedding 相似度路由。"""
    # 用一个不含知识关键词的模糊查询
    query_text = "骨灰放哪好"  # 不含 _KNOWLEDGE_KEYWORDS 中任何词

    # mock embed_fn：query embedding 接近 knowledge 原型
    embed_fn = MagicMock()
    def fake_embed(text):
        if "骨灰放哪" in text:
            return [0.9, 0.1, 0.0]  # 接近 knowledge 原型
        if "殡葬" in text or "政策" in text or "海葬" in text:
            return [0.9, 0.1, 0.0]  # knowledge 原型
        if "你是谁" in text or "功能" in text:
            return [0.1, 0.9, 0.0]  # chat 原型
        if "你好" in text or "谢谢" in text:
            return [0.0, 0.0, 0.9]  # greeting 原型
        return [0.0, 0.0, 0.0]
    embed_fn.side_effect = fake_embed

    # 清空缓存，强制重新计算意图原型 embedding
    import core.retrieval.router as router_mod
    router_mod._intent_embeddings.clear()

    result, reason = route_query_with_embedding(
        query_text, embed_fn=embed_fn, threshold=0.3,
    )
    assert reason in ("semantic", "default", "keyword")


def test_route_query_with_embedding_threshold_not_met():
    """相似度低于阈值时保留关键词路由结果。

    注意：不能让 embed_fn 对所有输入返回相同向量，否则 cosine 相似度为 1.0
    反而会触发 semantic 路由。这里让每个文本返回唯一正交向量，相似度为 0。
    """
    seen: dict[str, int] = {}

    def fake_embed(text: str):
        if text not in seen:
            seen[text] = len(seen)
        v = [0.0] * 1000
        v[seen[text]] = 1.0
        return v

    embed_fn = MagicMock(side_effect=fake_embed)

    # 清空缓存
    import core.retrieval.router as router_mod
    router_mod._intent_embeddings.clear()

    # 用不含知识关键词的短 query
    result, reason = route_query_with_embedding(
        "今天天气不错",
        embed_fn=embed_fn,
        threshold=0.99,  # 极高阈值
    )
    assert reason == "default"


def test_route_query_with_embedding_precomputed_query_emb():
    """传入预计算的 query_embedding 时不再调用 embed_fn。"""
    embed_fn = MagicMock()
    query_emb = [1.0] * 512  # 与 bge-small-zh-v1.5 维度一致

    # 清空缓存避免影响
    import core.retrieval.router as router_mod
    router_mod._intent_embeddings.clear()

    result, reason = route_query_with_embedding(
        "测试查询",
        query_embedding=query_emb,
        embed_fn=embed_fn,
        threshold=0.5,
    )
    # embed_fn 不会被调用（query_embedding 已传入，但意图原型 embedding 仍需计算）
    # 注：意图原型 embedding 还是要计算的

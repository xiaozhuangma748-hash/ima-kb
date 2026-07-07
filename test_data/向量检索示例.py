"""Python 知识库示例：简单的向量检索实现。"""
from typing import List, Tuple
import math


def cosine_similarity(vec_a: List[float], vec_b: List[float]) -> float:
    """计算两个向量的余弦相似度。

    Args:
        vec_a: 向量 A
        vec_b: 向量 B

    Returns:
        余弦相似度，范围 [-1, 1]
    """
    if len(vec_a) != len(vec_b):
        raise ValueError("向量维度不一致")
    if not vec_a:
        return 0.0

    dot = sum(a * b for a, b in zip(vec_a, vec_b))
    norm_a = math.sqrt(sum(a * a for a in vec_a))
    norm_b = math.sqrt(sum(b * b for b in vec_b))

    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def top_k_search(
    query: List[float],
    corpus: List[Tuple[str, List[float]]],
    k: int = 5,
) -> List[Tuple[str, float]]:
    """在语料库中检索与 query 最相似的 top-k 文档。

    Args:
        query: 查询向量
        corpus: 语料库 [(doc_id, vector), ...]
        k: 返回前 k 个

    Returns:
        [(doc_id, score), ...] 按相似度降序
    """
    scores = [(doc_id, cosine_similarity(query, vec)) for doc_id, vec in corpus]
    scores.sort(key=lambda x: x[1], reverse=True)
    return scores[:k]


if __name__ == "__main__":
    # 简单测试
    v1 = [1.0, 2.0, 3.0]
    v2 = [2.0, 4.0, 6.0]
    v3 = [1.0, 0.0, 0.0]
    print(f"v1 vs v2: {cosine_similarity(v1, v2):.4f}")  # 应为 1.0
    print(f"v1 vs v3: {cosine_similarity(v1, v3):.4f}")  # 约 0.267

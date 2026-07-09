"""BM25 检索器：基于 jieba 中文分词。

特点：
- 入库时增量建索引（pickle 持久化）
- 查询时用 jieba.cut 分词，BM25 算法打分
- 比传统 LIKE 搜索强很多：懂中文分词、懂词频权重、懂文档长度归一化
- 不懂同义词、不懂语义（这是 Embedding 才能做到的）
"""
from __future__ import annotations

import math
import pickle
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

import jieba

from config import settings


# ---- 抑制 jieba 首次加载时的 stdout 输出 ----
def _suppress_jieba_init_output() -> None:
    """jieba 首次调用时会打印 'Building prefix dict...' 到 stdout，这里静默完成初始化。"""
    from contextlib import redirect_stdout
    import io

    with redirect_stdout(io.StringIO()):
        # 触发字典加载，所有输出会被重定向到内存缓冲区
        list(jieba.cut(""))


_suppress_jieba_init_output()


# ---- 停用词（无意义的常见词，不参与检索）----
_STOP_WORDS: Set[str] = {
    "的", "了", "在", "是", "我", "有", "和", "就", "不", "人", "都", "一",
    "一个", "上", "也", "很", "到", "说", "要", "去", "你", "会", "着", "没有",
    "看", "好", "自己", "这", "那", "它", "他", "她", "与", "及", "或", "但",
    "而", "且", "则", "于", "以", "对", "为", "由", "把", "被", "让", "使",
    "其", "此", "该", "那些", "这些", "什么", "怎么", "如何", "为什么",
    "可以", "可能", "应该", "需要", "通过", "进行", "根据", "按照",
    "the", "a", "an", "is", "are", "was", "were", "be", "been", "being",
    "and", "or", "but", "if", "of", "at", "by", "for", "with", "in", "on",
    "to", "from", "this", "that", "these", "those",
}


def tokenize(text: str) -> List[str]:
    """jieba 分词 + 过滤停用词和空白。

    Args:
        text: 原文本

    Returns:
        token 列表（保留词形，已过滤停用词和单字符标点）
    """
    tokens: list[str] = []
    for tok in jieba.cut_for_search(text):
        tok = tok.strip()
        if not tok:
            continue
        if tok in _STOP_WORDS:
            continue
        if len(tok) == 1 and not tok.isalnum():
            continue
        tokens.append(tok)
    return tokens


@dataclass
class _DocEntry:
    """索引中的单条文档（chunk）记录。"""
    chunk_id: str
    doc_id: str
    tokens: List[str]                # 分词后的 token 列表
    token_freq: Dict[str, int]      # token → 出现次数
    length: int                      # token 总数


@dataclass
class SearchResult:
    """检索结果。"""
    chunk_id: str
    doc_id: str
    score: float
    content: str = ""               # 由调用方填充
    doc_title: str = ""             # 由调用方填充


class BM25Index:
    """BM25 索引：增量插入、持久化、检索。

    BM25 公式：
        score(q, d) = Σ IDF(qi) * (f(qi,d) * (k1+1)) /
                       (f(qi,d) + k1 * (1 - b + b * |d| / avgdl))
    其中：
        IDF(qi) = ln((N - n(qi) + 0.5) / (n(qi) + 0.5) + 1)
    """

    def __init__(
        self,
        k1: float = 1.5,
        b: float = 0.75,
        index_path: Optional[Path] = None,
    ) -> None:
        self.k1 = k1
        self.b = b
        self.index_path = index_path or settings.bm25_index_path

        # 索引数据
        self._docs: Dict[str, _DocEntry] = {}            # chunk_id → entry
        self._doc_freq: Dict[str, int] = {}              # token → 包含该 token 的文档数
        self._total_length: int = 0                       # 所有文档 token 总长

        # 加载已有索引
        self._load()

    # ---- 增删 ----

    def add(self, chunk_id: str, doc_id: str, content: str) -> None:
        """添加/更新一个 chunk 到索引。"""
        # 如果已存在，先移除
        if chunk_id in self._docs:
            self.remove(chunk_id)

        tokens = tokenize(content)
        token_freq: Dict[str, int] = {}
        for tok in tokens:
            token_freq[tok] = token_freq.get(tok, 0) + 1

        entry = _DocEntry(
            chunk_id=chunk_id,
            doc_id=doc_id,
            tokens=tokens,
            token_freq=token_freq,
            length=len(tokens),
        )
        self._docs[chunk_id] = entry
        self._total_length += entry.length

        # 更新 doc_freq
        for tok in token_freq:
            self._doc_freq[tok] = self._doc_freq.get(tok, 0) + 1

    def remove(self, chunk_id: str) -> bool:
        """从索引移除一个 chunk。"""
        entry = self._docs.pop(chunk_id, None)
        if entry is None:
            return False
        self._total_length -= entry.length
        for tok in entry.token_freq:
            self._doc_freq[tok] = self._doc_freq.get(tok, 0) - 1
            if self._doc_freq[tok] <= 0:
                del self._doc_freq[tok]
        return True

    def clear(self) -> None:
        """清空索引。"""
        self._docs.clear()
        self._doc_freq.clear()
        self._total_length = 0

    # ---- 检索 ----

    def search(
        self,
        query: str,
        top_k: int = 10,
    ) -> List[SearchResult]:
        """检索最相关的 top_k 个 chunk。

        Args:
            query: 查询文本
            top_k: 返回前 K 条

        Returns:
            SearchResult 列表（按分数降序，content/doc_title 留给调用方填充）
        """
        if not self._docs:
            return []

        query_tokens = tokenize(query)
        if not query_tokens:
            return []

        N = len(self._docs)
        avgdl = self._total_length / N if N > 0 else 0

        scores: List[Tuple[str, float]] = []
        for chunk_id, entry in self._docs.items():
            score = 0.0
            for qt in query_tokens:
                f = entry.token_freq.get(qt, 0)
                if f == 0:
                    continue
                # IDF
                n_qi = self._doc_freq.get(qt, 0)
                idf = math.log((N - n_qi + 0.5) / (n_qi + 0.5) + 1)
                # BM25
                denom = f + self.k1 * (1 - self.b + self.b * (entry.length / avgdl if avgdl > 0 else 0))
                score += idf * (f * (self.k1 + 1)) / denom
            if score > 0:
                scores.append((chunk_id, score))

        scores.sort(key=lambda x: x[1], reverse=True)
        return [
            SearchResult(chunk_id=cid, doc_id=self._docs[cid].doc_id, score=s)
            for cid, s in scores[:top_k]
        ]

    # ---- 持久化 ----

    def save(self) -> None:
        """保存索引到磁盘。"""
        self.index_path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "k1": self.k1,
            "b": self.b,
            "docs": self._docs,
            "doc_freq": self._doc_freq,
            "total_length": self._total_length,
        }
        with open(self.index_path, "wb") as f:
            pickle.dump(data, f, protocol=pickle.HIGHEST_PROTOCOL)

    def _load(self) -> None:
        """从磁盘加载索引。"""
        if not self.index_path.exists():
            return
        try:
            with open(self.index_path, "rb") as f:
                data = pickle.load(f)
            self.k1 = data.get("k1", self.k1)
            self.b = data.get("b", self.b)
            self._docs = data.get("docs", {})
            self._doc_freq = data.get("doc_freq", {})
            self._total_length = data.get("total_length", 0)
        except Exception:
            # 索引文件损坏，重置
            self._docs = {}
            self._doc_freq = {}
            self._total_length = 0

    # ---- 统计 ----

    def __len__(self) -> int:
        return len(self._docs)

    def info(self) -> Dict[str, int]:
        return {
            "chunks": len(self._docs),
            "vocabulary": len(self._doc_freq),
            "total_tokens": self._total_length,
        }

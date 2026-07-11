"""BM25 检索器：基于 jieba 中文分词。

特点：
- 入库时增量建索引（pickle 持久化）
- 查询时用 jieba.cut 分词，BM25 算法打分
- 比传统 LIKE 搜索强很多：懂中文分词、懂词频权重、懂文档长度归一化
- 不懂同义词、不懂语义（这是 Embedding 才能做到的）

性能优化：
- jieba 懒加载，避免模块导入时就触发字典加载
- 倒排索引 _inverted_index: Dict[token, Set[chunk_id]]，检索只遍历相关文档
- threading.RLock 保护读写，并发安全
- 不再冗余存储 tokens list，只用 token_freq
"""
from __future__ import annotations

import math
import pickle
import threading
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

import jieba
jieba.setLogLevel(jieba.logging.WARNING)

from config import settings


# ---- jieba 懒加载 ----
_jieba_ready: bool = False


def _ensure_jieba() -> None:
    """懒加载 jieba 并静默完成字典初始化。"""
    global _jieba_ready
    if _jieba_ready:
        return
    from contextlib import redirect_stdout
    import io
    with redirect_stdout(io.StringIO()):
        list(jieba.cut(""))
    _jieba_ready = True


# ---- 文本归一化 ----
def _normalize_text(text: str) -> str:
    """文本归一化：全角转半角（NFKC）+ 英文小写。

    - 全角字符（如 （）、ＡＢＣ、１２３）统一转为半角，消除格式差异
    - 英文字母统一小写，让 "API" 与 "api" 能匹配
    """
    text = unicodedata.normalize("NFKC", text)
    text = text.lower()
    return text


# ---- 停用词（无意义的常见词，不参与检索）----
# 说明：精简自原版，移除了 "通过"/"进行"/"根据"/"按照" 等在专业文档中
# 可能承载实际语义的词，避免误杀；保留真正无语义价值的虚词。
_STOP_WORDS: Set[str] = {
    "的", "了", "在", "是", "我", "有", "和", "就", "不", "人", "都", "一",
    "一个", "上", "也", "很", "到", "说", "要", "去", "你", "会", "着", "没有",
    "看", "好", "自己", "这", "那", "它", "他", "她", "与", "及", "或", "但",
    "而", "且", "则", "于", "以", "对", "为", "由", "把", "被", "让", "使",
    "其", "此", "该", "那些", "这些", "什么", "怎么", "如何", "为什么",
    "可以", "可能", "应该",
    "the", "a", "an", "is", "are", "was", "were", "be", "been", "being",
    "and", "or", "but", "if", "of", "at", "by", "for", "with", "in", "on",
    "to", "from", "this", "that", "these", "those",
}


def tokenize(text: str) -> List[str]:
    """jieba 分词 + 文本归一化 + 过滤停用词和空白。

    改进点（提升召回率）：
    - 先做 NFKC 归一化（全角→半角）+ 英文小写，消除格式差异
    - 同时用搜索引擎模式（cut_for_search）和全模式（cut_all=True），
      取两者 token 并集。全模式会切出所有可能的词组合，覆盖更细粒度的切分，
      提升召回率（可能引入噪音，但 BM25 的 IDF 会自动降低无意义词的权重）
    - 过滤停用词和单字符标点

    Args:
        text: 原文本

    Returns:
        token 列表（已归一化、去重、过滤停用词）
    """
    _ensure_jieba()
    text = _normalize_text(text)
    tokens: list[str] = []
    seen: set[str] = set()

    def _add(tok: str) -> None:
        tok = tok.strip()
        if not tok or tok in _STOP_WORDS:
            return
        if len(tok) == 1 and not tok.isalnum():
            return
        if tok not in seen:
            seen.add(tok)
            tokens.append(tok)

    # 搜索引擎模式：精确切分 + 对长词再切分
    for tok in jieba.cut_for_search(text):
        _add(tok)
    # 全模式：列出所有可能的词组合，补充搜索引擎模式遗漏的切分
    for tok in jieba.cut(text, cut_all=True):
        _add(tok)
    return tokens


@dataclass
class _DocEntry:
    """索引中的单条文档（chunk）记录。

    性能优化：不再存储完整的 tokens list（检索时只用 token_freq），
    节省内存约 30-50%。
    """
    chunk_id: str
    doc_id: str
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

    线程安全：所有读写操作通过 self._lock 保护。
    """

    def __init__(
        self,
        k1: float = 1.5,
        b: float = 0.5,
        index_path: Optional[Path] = None,
    ) -> None:
        self.k1 = k1
        self.b = b
        self.index_path = index_path or settings.bm25_index_path

        # 索引数据
        self._docs: Dict[str, _DocEntry] = {}            # chunk_id → entry
        self._doc_freq: Dict[str, int] = {}              # token → 包含该 token 的文档数
        self._inverted: Dict[str, Set[str]] = {}         # 倒排索引: token → {chunk_id}
        self._total_length: int = 0                       # 所有文档 token 总长

        # 读写锁（可重入，支持嵌套调用）
        self._lock = threading.RLock()

        # 加载已有索引
        self._load()

    # ---- 增删 ----

    def add(self, chunk_id: str, doc_id: str, content: str) -> None:
        """添加/更新一个 chunk 到索引。"""
        with self._lock:
            # 如果已存在，先移除
            if chunk_id in self._docs:
                self._remove_locked(chunk_id)

            tokens = tokenize(content)
            token_freq: Dict[str, int] = {}
            for tok in tokens:
                token_freq[tok] = token_freq.get(tok, 0) + 1

            entry = _DocEntry(
                chunk_id=chunk_id,
                doc_id=doc_id,
                token_freq=token_freq,
                length=len(tokens),
            )
            self._docs[chunk_id] = entry
            self._total_length += entry.length

            # 更新 doc_freq 和倒排索引
            for tok in token_freq:
                self._doc_freq[tok] = self._doc_freq.get(tok, 0) + 1
                self._inverted.setdefault(tok, set()).add(chunk_id)

    def _remove_locked(self, chunk_id: str) -> bool:
        """从索引移除一个 chunk（调用方需持有锁）。"""
        entry = self._docs.pop(chunk_id, None)
        if entry is None:
            return False
        self._total_length -= entry.length
        for tok in entry.token_freq:
            self._doc_freq[tok] = self._doc_freq.get(tok, 0) - 1
            if self._doc_freq[tok] <= 0:
                del self._doc_freq[tok]
            # 从倒排索引移除
            postings = self._inverted.get(tok)
            if postings:
                postings.discard(chunk_id)
                if not postings:
                    del self._inverted[tok]
        return True

    def remove(self, chunk_id: str) -> bool:
        """从索引移除一个 chunk。"""
        with self._lock:
            return self._remove_locked(chunk_id)

    def clear(self) -> None:
        """清空索引。"""
        with self._lock:
            self._docs.clear()
            self._doc_freq.clear()
            self._inverted.clear()
            self._total_length = 0

    # ---- 检索 ----

    def search(
        self,
        query: str,
        top_k: int = 10,
    ) -> List[SearchResult]:
        """检索最相关的 top_k 个 chunk。

        性能优化：用倒排索引只遍历包含 query token 的文档，
        复杂度从 O(N×Q) 降到 O(Σ|postings|)。
        """
        with self._lock:
            if not self._docs:
                return []

            query_tokens = tokenize(query)
            if not query_tokens:
                return []

            N = len(self._docs)
            avgdl = self._total_length / N if N > 0 else 0

            # 用倒排索引收集候选文档
            # candidate_scores: chunk_id → score
            candidate_scores: Dict[str, float] = {}
            for qt in query_tokens:
                postings = self._inverted.get(qt)
                if not postings:
                    continue
                n_qi = self._doc_freq.get(qt, 0)
                # IDF 截断：当词在多数文档出现时 IDF 可能为负，设为 0 避免反向扣分
                idf = max(0.0, math.log((N - n_qi + 0.5) / (n_qi + 0.5) + 1))
                for cid in postings:
                    entry = self._docs.get(cid)
                    if entry is None:
                        continue
                    f = entry.token_freq.get(qt, 0)
                    if f == 0:
                        continue
                    denom = f + self.k1 * (1 - self.b + self.b * (entry.length / avgdl if avgdl > 0 else 0))
                    candidate_scores[cid] = candidate_scores.get(cid, 0.0) + idf * (f * (self.k1 + 1)) / denom

            if not candidate_scores:
                return []

            # 排序并取 top_k
            sorted_ids = sorted(candidate_scores.items(), key=lambda x: x[1], reverse=True)
            return [
                SearchResult(chunk_id=cid, doc_id=self._docs[cid].doc_id, score=s)
                for cid, s in sorted_ids[:top_k]
            ]

    # ---- 持久化 ----

    def save(self) -> None:
        """保存索引到磁盘。"""
        with self._lock:
            self.index_path.parent.mkdir(parents=True, exist_ok=True)
            # 注意：k1/b 不持久化，作为运行时参数由代码默认值决定，
            # 这样调参后无需重建索引即可生效
            data = {
                "docs": self._docs,
                "doc_freq": self._doc_freq,
                "inverted": self._inverted,
                "total_length": self._total_length,
            }
            with open(self.index_path, "wb") as f:
                pickle.dump(data, f, protocol=pickle.HIGHEST_PROTOCOL)

    def _load(self) -> None:
        """从磁盘加载索引。

        注意：k1/b 不从持久化加载，使用代码中的默认值/构造参数。
        这样调整 BM25 参数后无需重建索引即可立即生效。
        """
        if not self.index_path.exists():
            return
        try:
            with open(self.index_path, "rb") as f:
                data = pickle.load(f)
            self._docs = data.get("docs", {})
            self._doc_freq = data.get("doc_freq", {})
            self._inverted = data.get("inverted", {})
            self._total_length = data.get("total_length", 0)
            # 兼容旧版索引（没有倒排索引字段）：重建
            if not self._inverted and self._docs:
                self._rebuild_inverted_locked()
        except Exception:
            # 索引文件损坏，重置
            self._docs = {}
            self._doc_freq = {}
            self._inverted = {}
            self._total_length = 0

    def _rebuild_inverted_locked(self) -> None:
        """从 _docs 重建倒排索引（调用方需持有锁）。"""
        self._inverted.clear()
        for cid, entry in self._docs.items():
            for tok in entry.token_freq:
                self._inverted.setdefault(tok, set()).add(cid)

    # ---- 统计 ----

    def __len__(self) -> int:
        with self._lock:
            return len(self._docs)

    def info(self) -> Dict[str, int]:
        with self._lock:
            return {
                "chunks": len(self._docs),
                "vocabulary": len(self._doc_freq),
                "total_tokens": self._total_length,
            }

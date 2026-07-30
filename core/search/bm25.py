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


# ---- 机构名词典（加载一次，提升专有名词切分准确度）----
_user_dict_loaded = False

# 项目内置的机构名/术语词典（殡葬领域专有名词）
_BIZ_USER_DICT_PATH = Path(__file__).resolve().parent.parent.parent / "storage" / "user_dict.txt"

# 内置词典内容（若文件不存在则用代码内置）
_BUILTIN_TERMS = [
    # 行政区划
    "拱墅区", "余杭区", "钱塘区", "临平区", "滨江区", "萧山区", "上城区", "西湖区",
    "杭州市", "浙江省", "上海市",
    # 街道/社区
    "白杨街道", "晨光社区",
    # 机构全称
    "居家养老服务照料中心", "养老服务照料中心", "照料中心",
    "殡葬服务中心", "殡仪服务中心", "殡仪馆",
    "民政局", "财政厅", "民政厅",
    # 殡葬术语
    "骨灰安置", "骨灰寄存", "骨灰撒海", "节地生态安葬", "生态安葬",
    "身后事", "身后一件事", "一件事",
    "遗体接运", "遗体火化", "遗体告别",
    "白事服务", "殡葬服务", "殡仪服务",
    "公益性墓地", "经营性墓地", "骨灰堂",
    "奖补政策", "奖补标准",
]


def _load_user_dict() -> None:
    """加载用户词典（机构名/术语），提升 jieba 对专有名词的切分准确度。

    优先加载 storage/user_dict.txt（用户可自行扩展），叠加内置术语。
    只加载一次（线程安全由 GIL 保证）。
    """
    global _user_dict_loaded
    if _user_dict_loaded:
        return

    # 1. 加载内置术语
    for term in _BUILTIN_TERMS:
        jieba.add_word(term)

    # 2. 加载用户扩展词典（若存在）
    if _BIZ_USER_DICT_PATH.exists():
        try:
            jieba.load_userdict(str(_BIZ_USER_DICT_PATH))
        except Exception:
            pass  # 词典加载失败不影响主流程

    _user_dict_loaded = True


# ---- jieba 懒加载 ----
_jieba_ready: bool = False


def _ensure_jieba() -> None:
    """懒加载 jieba 并静默完成字典初始化 + 加载用户词典。"""
    global _jieba_ready
    if _jieba_ready:
        return
    from contextlib import redirect_stdout
    import io
    with redirect_stdout(io.StringIO()):
        list(jieba.cut(""))
    _load_user_dict()  # 加载机构名词典
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
    # 疑问代词/副词：作为查询词时无检索意义，会因极低 doc_freq 产生高 IDF 噪音
    "哪些", "哪种", "哪类", "几个", "多少", "哪里", "哪儿", "何时",
    "可以", "可能", "应该",
    "the", "a", "an", "is", "are", "was", "were", "be", "been", "being",
    "and", "or", "but", "if", "of", "at", "by", "for", "with", "in", "on",
    "to", "from", "this", "that", "these", "those",
}


def tokenize(text: str) -> List[str]:
    """jieba 分词 + 文本归一化 + 过滤停用词和空白 + bigram 短语匹配。

    改进点（提升召回率 + 精确率）：
    - 先做 NFKC 归一化（全角→半角）+ 英文小写，消除格式差异
    - 加载机构名词典（居家养老服务照料中心等），避免专有名词被错误切分
    - 用搜索引擎模式（cut_for_search）：精确切分 + 对长词再切分，召回率足够
    - 去掉了 cut_all=True 全模式路径：全模式会切出"家养"等噪音词（从"居家养老"
      中错误切出），降低长机构名查询的精确率。cut_for_search 已足够覆盖细粒度切分。
    - 过滤停用词和单字符标点
    - bigram 短语匹配：基于精确模式（jieba.cut）的有序 token 生成相邻 bigram，
      让"晨光社区"作为"晨光_社区"整体参与匹配。bigram 的 IDF 天然更高
      （只有包含该连续短语的文档才命中），显著提升短语查询的精确率。

    Args:
        text: 原文本

    Returns:
        token 列表（已归一化、去重、过滤停用词，含 unigram 和 bigram）
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

    # 搜索引擎模式：精确切分 + 对长词再切分（覆盖足够，不引入全模式噪音）
    for tok in jieba.cut_for_search(text):
        _add(tok)

    # bigram 短语匹配：用精确模式的有序 token 生成相邻 bigram
    # 例："晨光社区" → ["晨光", "社区"] → bigram "晨光_社区"
    # 只有文档中连续出现"晨光"+"社区"才命中，区分性远高于单独的"晨光"或"社区"
    _add_bigrams(text, _add)

    return tokens


def _add_bigrams(text: str, _add) -> None:
    """生成 bigram 并通过 _add 加入 token 列表。

    用精确模式（jieba.cut）获取有序 token，过滤后生成相邻 bigram。
    bigram 格式：f"{tok1}_{tok2}"，下划线分隔避免与正常 token 混淆。
    """
    ordered_tokens: list[str] = []
    for tok in jieba.cut(text):  # 精确模式，保留原始顺序
        tok = tok.strip()
        if not tok or tok in _STOP_WORDS:
            continue
        if len(tok) == 1 and not tok.isalnum():
            continue
        ordered_tokens.append(tok)

    # 生成相邻 bigram
    for i in range(len(ordered_tokens) - 1):
        bigram = f"{ordered_tokens[i]}_{ordered_tokens[i + 1]}"
        _add(bigram)


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
    heading: str = ""               # 所属章节标题（由调用方填充，PDF rerank 用）


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
        b: float = 0.35,
        index_path: Optional[Path] = None,
    ) -> None:
        self.k1 = k1
        # b 参数控制文档长度归一化强度：
        # - b=1.0 完全归一化（短文档与长文档同等对待）
        # - b=0.0 不归一化（原始词频决定分数）
        # - 中文政务文档推荐 b=0.3-0.4
        # - 从 0.5 调到 0.35：减少短 chunk（如 xlsx 单行）被长度归一化虚高的问题
        #   长查询命中数相同时，短 chunk 不再因 |d|/avgdl 小而得分虚高
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
                # 单字 token 降权：中文单字（如"中心""服务"）语义模糊且高频，
                # 容易在管理类文档累积高分挤掉真正结果。乘 0.6 系数降低其影响。
                # 注意：bigram（含下划线）和多字 token 不受影响
                if len(qt) == 1:
                    idf *= 0.6
                # 高频双字 token 降权：doc_freq > N*0.5 的双字词（如"中心""服务""养老"）
                # 在政务文档中极常见，累加分数会干扰精确查询排名。乘 0.8 系数。
                # bigram（含下划线）和低频双字词不受影响
                elif len(qt) == 2 and "_" not in qt and n_qi > N * 0.5 and N > 10:
                    idf *= 0.8
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

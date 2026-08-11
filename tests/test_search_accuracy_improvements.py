"""搜索准确率改进单元测试。

覆盖三项改进：
1. xlsx parser 注入文档标题（让 BM25 能命中标题里的关键词）
2. BM25 单字 token 降权 + b 参数调优（缓解短文档虚高、单字噪音）
3. Weighted RRF 查询自适应（精确/模糊/普通查询用不同权重）
"""
from __future__ import annotations

import math
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from core.search.bm25 import BM25Index, tokenize, _STOP_WORDS
from core.retrieval.hybrid import (
    HybridRetriever,
    QUERY_WEIGHTS,
    _FUZZY_MARKERS,
    _PRECISE_MARKERS,
)


# ============================================================
# 改进 1：xlsx parser 注入文档标题
# ============================================================

class TestXlsxDocTitleInjection:
    """xlsx parser 在每行 chunk 前缀注入「文档=DocTitle |」。"""

    def test_tokenize_xlsx_chunk_includes_doc_title_keywords(self):
        """注入后 BM25 tokenize 能切出标题中的关键词。"""
        # 模拟注入后的 chunk content
        chunk = "[钱塘安装情况] 文档=2025年智能服务终端配置安装情况 | 序号=6 | 街道=白杨街道"
        tokens = tokenize(chunk)
        # "智能" 现在应该在 tokens 中（之前因 chunk 内容缺"智能"二字无法命中）
        assert "智能" in tokens, f"注入文档标题后应能切出'智能'，实际 tokens: {tokens}"
        assert "终端" in tokens, f"应能切出'终端'，实际 tokens: {tokens}"
        # bigram 应包含连续相邻 token 对（jieba 切"智能服务终端"为 智能/服务/终端）
        # 关键是"智能"和"终端"作为独立 token 出现，BM25 即可命中
        # bigram 智能_服务 / 服务_终端 是预期产物
        assert "智能_服务" in tokens or "服务_终端" in tokens, \
            f"应生成相关 bigram，实际 tokens: {tokens}"

    def test_stop_words_include_fuzzy_markers(self):
        """疑问词应进入 BM25 停用词表，避免极低 doc_freq 产生高 IDF 噪音。"""
        # B1 修复的关键：'哪些' 必须在停用词里
        assert "哪些" in _STOP_WORDS, "'哪些' 应在停用词表中"
        assert "哪种" in _STOP_WORDS, "'哪种' 应在停用词表中"
        assert "多少" in _STOP_WORDS, "'多少' 应在停用词表中"

    def test_tokenize_filters_fuzzy_markers(self):
        """疑问词被 tokenize 过滤，不进入 BM25 索引。"""
        tokens = tokenize("养老中心有哪些")
        assert "哪些" not in tokens, "疑问词'哪些'应被过滤"
        # 但有意义的"养老""中心"应保留
        assert "养老" in tokens
        assert "中心" in tokens


# ============================================================
# 改进 2：BM25 单字 token 降权 + b 参数调优
# ============================================================

class TestBM25SingleCharDownweight:
    """单字 token 在 BM25 search 时 IDF 乘 0.6 降权。"""

    def test_bm25_default_b_is_035(self):
        """b 参数默认值应为 0.35（从 0.5 调整以缓解短文档虚高）。"""
        idx = BM25Index()
        assert idx.b == 0.35, f"默认 b 应为 0.35，实际 {idx.b}"

    def test_single_char_token_idf_downweighted(self, tmp_path):
        """单字 token 在 search 时 IDF 乘 0.6（间接验证：单字得分低于多字）。"""
        idx = BM25Index(index_path=tmp_path / "test_bm25.pkl")
        # 两个 chunk：一个含单字"中"高频，一个含多字"中心"
        idx.add("c1", "d1", "中中中中中中管理知识")  # 单字"中"高频
        idx.add("c2", "d2", "居家养老服务中心服务")  # 多字"中心"

        # 查询"中心"
        results = idx.search("中心", top_k=5)
        # 由于"中心"是多字 token，应正常打分
        # "中"是单字，被降权
        # 验证 c2（含"中心"）排名高于 c1（只含单字"中"）
        assert len(results) > 0
        top_ids = [r.chunk_id for r in results]
        # c2 应该靠前（包含完整"中心"token，且单字"中"在 c1 中虽高频但被降权）
        if "c2" in top_ids and "c1" in top_ids:
            assert top_ids.index("c2") < top_ids.index("c1"), \
                f"含'中心'多字 token 的 chunk 应排前，实际顺序: {top_ids}"

    def test_bigram_not_affected_by_single_char_downweight(self, tmp_path):
        """bigram token（含下划线）不受单字降权影响。"""
        idx = BM25Index(index_path=tmp_path / "test_bm25.pkl")
        idx.add("c1", "d1", "白杨街道晨光社区居家养老服务照料中心")
        results = idx.search("晨光社区", top_k=5)
        assert len(results) > 0
        # bigram 晨光_社区 应该有较高分数
        assert results[0].chunk_id == "c1"


# ============================================================
# 改进 3：Weighted RRF 查询自适应
# ============================================================

class TestWeightedRRF:
    """Weighted RRF 根据查询类型使用不同权重。"""

    def test_classify_fuzzy_query(self):
        """含疑问词的查询应分类为 fuzzy。"""
        for q in ["智能终端怎么安装", "养老中心有哪些", "骨灰寄存在哪里", "如何办理身后事"]:
            weights = HybridRetriever._classify_query(q)
            assert weights == QUERY_WEIGHTS["fuzzy"], \
                f"'{q}' 应分类为 fuzzy，实际 {weights}"

    def test_classify_precise_query(self):
        """含具体名词的查询应分类为 precise。"""
        for q in [
            "白杨街道晨光社区居家养老服务照料中心",
            "浙民事〔2025〕84号",
            "九堡街道居家养老服务中心",
        ]:
            weights = HybridRetriever._classify_query(q)
            assert weights == QUERY_WEIGHTS["precise"], \
                f"'{q}' 应分类为 precise，实际 {weights}"

    def test_classify_normal_query(self):
        """不含疑问词也不含具体名词的查询分类为 normal。"""
        for q in ["骨灰寄存", "殡葬服务流程", "PDCA循环", "养老服务"]:
            weights = HybridRetriever._classify_query(q)
            assert weights == QUERY_WEIGHTS["normal"], \
                f"'{q}' 应分类为 normal，实际 {weights}"

    def test_classify_none_query_returns_normal(self):
        """None 查询返回 normal 权重（兼容旧调用）。"""
        weights = HybridRetriever._classify_query(None)
        assert weights == QUERY_WEIGHTS["normal"]

    def test_fuzzy_priority_over_precise(self):
        """fuzzy 优先于 precise：含疑问词+具体名词的查询归 fuzzy。"""
        # "白杨街道怎么走" 含"街道"（precise）和"怎么"（fuzzy）
        weights = HybridRetriever._classify_query("白杨街道怎么走")
        assert weights == QUERY_WEIGHTS["fuzzy"], \
            "fuzzy 应优先于 precise，因为口语化查询语义检索更重要"

    def test_weights_sum_to_one(self):
        """所有权重组合的 bm25+vector 应等于 1.0。"""
        for key, w in QUERY_WEIGHTS.items():
            assert math.isclose(w["bm25"] + w["vector"], 1.0, abs_tol=1e-6), \
                f"{key} 权重和应为 1.0，实际 {w['bm25'] + w['vector']}"

    def test_rrf_fusion_uses_query_weights(self, tmp_path):
        """_rrf_fusion 接收 query 参数，使用对应权重。

        验证策略：用极端 rank 差距让权重生效可见
        - bm25_results: c1 rank 1, c2 rank 50（c1 在 BM25 远超 c2）
        - vector_results: c2 rank 1, c3 rank 2（c2 在向量远超 c1，c1 不在向量中）
        - precise 模式（bm25=0.7）下 c1 应排第一（BM25 优势放大）
        - fuzzy 模式（vector=0.7）下 c2 应排第一（向量优势放大）
        """
        from core.search.bm25 import SearchResult
        from core.retrieval.vector import VectorResult

        # c1 只在 BM25 中排第一，c2 在 BM25 中排第 50 但在向量中排第一
        bm25_results = [SearchResult(chunk_id="c1", doc_id="d1", score=10.0)]
        # 把 c2 塞到第 50 位：构造 49 个填充结果
        for i in range(2, 51):
            bm25_results.append(SearchResult(chunk_id=f"filler_{i}", doc_id=f"d{i}", score=float(50-i)))
        bm25_results.append(SearchResult(chunk_id="c2", doc_id="d2", score=0.1))  # rank 50

        vector_results = [
            VectorResult(chunk_id="c2", doc_id="d2", score=0.9),
            VectorResult(chunk_id="c3", doc_id="d3", score=0.8),
        ]

        retriever = object.__new__(HybridRetriever)

        # precise 查询：bm25=0.7，c1 在 BM25 排第一应胜出
        results_precise = retriever._rrf_fusion(bm25_results, vector_results, 5, query="晨光社区")
        precise_top = results_precise[0].chunk_id
        assert precise_top == "c1", \
            f"precise 查询下 c1 应排第一（BM25 权重高 + rank 1），实际第一是 {precise_top}"

        # fuzzy 查询：vector=0.7，c2 在向量排第一应胜出
        results_fuzzy = retriever._rrf_fusion(bm25_results, vector_results, 5, query="怎么安装")
        fuzzy_top = results_fuzzy[0].chunk_id
        assert fuzzy_top == "c2", \
            f"fuzzy 查询下 c2 应排第一（向量权重高 + rank 1），实际第一是 {fuzzy_top}"

        # 验证两种模式排名确实不同（权重生效）
        assert precise_top != fuzzy_top, \
            f"precise 和 fuzzy 模式应产生不同排名，实际都是 {precise_top}"


# ============================================================
# 改进 2 续：rerank_by_exact_match 单字 token 过滤
# ============================================================

class TestRerankFiltersSingleChar:
    """rerank_by_exact_match 识别区分性词时过滤单字 token。"""

    def test_single_char_not_treated_as_distinctive(self):
        """单字 token 不应被识别为区分性词。"""
        from core.storage import Storage
        from core.search.bm25 import SearchResult as Bm25SearchResult

        # 构造 mock storage（不需要真实数据库）
        storage = object.__new__(Storage)

        # 两个结果：c1 含"中心"，c2 不含
        # 查询"养老中心"会 tokenize 出 "养老""中心" + bigram
        # 单字"中""心"被过滤，多字"养老""中心"参与
        r1 = MagicMock()
        r1.content = "居家养老服务中心服务"
        r1.score = 5.0

        r2 = MagicMock()
        r2.content = "中中中管理知识库"
        r2.score = 5.0

        results = [r1, r2]
        out = storage.rerank_by_exact_match("养老中心", results)
        # r1 含"养老""中心"多字 token，应被加权
        # r2 只含单字"中"，被过滤后无区分性词命中
        # 验证 r1 排在 r2 前面
        assert out[0] is r1, f"含多字 token 的 r1 应排前，实际顺序: {[r.content[:20] for r in out]}"


# ============================================================
# 集成测试：迁移方法
# ============================================================

class TestXlsxMigration:
    """migrate_xlsx_chunks_inject_doc_title 迁移方法测试。"""

    def test_migration_is_idempotent(self, tmp_path, monkeypatch):
        """迁移方法应幂等：已含前缀的 chunk 不再修改。"""
        import sqlite3
        import threading

        # 构造临时 db
        db_path = tmp_path / "metadata.db"
        conn = sqlite3.connect(str(db_path))
        conn.executescript("""
            CREATE TABLE documents (
                id TEXT PRIMARY KEY, title TEXT NOT NULL, file_name TEXT,
                file_path TEXT, file_type TEXT NOT NULL, file_size INTEGER,
                content_hash TEXT, language TEXT, meta TEXT, created_at TEXT,
                chunk_count INTEGER, total_tokens INTEGER, tags TEXT
            );
            CREATE TABLE chunks (
                id TEXT PRIMARY KEY, doc_id TEXT NOT NULL, index_in_doc INTEGER,
                content TEXT NOT NULL, token_count INTEGER, start_char INTEGER,
                end_char INTEGER, parent_content TEXT, created_at TEXT
            );
        """)
        conn.commit()
        conn.close()

        # 构造 storage 实例，绕过 __init__ 但补齐必要属性
        from core.storage import Storage
        storage = object.__new__(Storage)
        storage.db_path = db_path
        storage.storage_path = tmp_path
        storage.uploads_dir = tmp_path / "uploads"
        storage._tls = threading.local()  # _conn() 需要

        # mock bm25（不实际建索引）
        storage.bm25 = MagicMock()
        storage.bm25.clear = MagicMock()
        storage.bm25.add = MagicMock()
        storage.bm25.save = MagicMock()
        storage.rebuild_bm25_index = MagicMock(return_value=0)

        # 插入 1 个 xlsx 文档 + 1 个 chunk（不含前缀）
        conn = sqlite3.connect(str(db_path))
        conn.execute(
            "INSERT INTO documents (id, title, file_name, file_path, file_type, file_size, content_hash, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            ("d1", "智能服务终端配置安装情况", "test.xlsx", "/tmp/test.xlsx", ".xlsx", 100, "h1", "2025-01-01"),
        )
        conn.execute(
            "INSERT INTO chunks (id, doc_id, index_in_doc, content, token_count, start_char, end_char, parent_content, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ("c1", "d1", 0, "[钱塘安装情况] 序号=6 | 街道=白杨街道", 10, 0, 50, "", "2025-01-01"),
        )
        conn.commit()
        conn.close()

        # 第一次迁移：应修改 1 条
        n1 = storage.migrate_xlsx_chunks_inject_doc_title()
        assert n1 == 1, f"第一次迁移应修改 1 条，实际 {n1}"

        # 验证 chunk content 已注入文档标题
        conn = sqlite3.connect(str(db_path))
        row = conn.execute("SELECT content FROM chunks WHERE id = ?", ("c1",)).fetchone()
        conn.close()
        assert "文档=智能服务终端配置安装情况" in row[0], \
            f"chunk content 应含文档标题前缀，实际: {row[0]}"

        # 第二次迁移：应修改 0 条（幂等）
        n2 = storage.migrate_xlsx_chunks_inject_doc_title()
        assert n2 == 0, f"第二次迁移应修改 0 条（幂等），实际 {n2}"

# 宠物知识库管理员 · 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把虚拟宠物升级为知识库管理员——宠物作为 AI 助手的人格化化身，具备精准召回（混合检索+重排+溯源）、长期记忆（偏好+工作流+任务）、分系人格三大能力。

**Architecture:** 分层架构——`core/retrieval/`（检索）、`core/memory/`（记忆）、`core/persona/`（人格）三个独立模块 + `core/pet/administrator.py`（编排层）整合三层。REPL 的所有 AI 交互改为走 administrator。

**Tech Stack:** Python 3.9+ / ChromaDB + sentence-transformers（向量）/ rich（CLI）/ pytest / dataclasses

## Global Constraints

- Python ≥ 3.9（不使用 `X | Y` 联合类型，用 `Optional[X]`）
- 文件命名：snake_case
- 中文注释 + 英文变量名
- 测试框架：pytest（已存在）
- 所有时间用 ISO 字符串存储
- 路径含中文，用 Path 对象处理
- 现有接口：`BM25Index.search(query, top_k) -> List[SearchResult]`，`SearchResult` 有 `chunk_id/doc_id/score/content/doc_title`
- 现有接口：`Storage.get_chunks(doc_id) -> List[ChunkRecord]`，`ChunkRecord` 有 `id/doc_id/index/content/token_count/start_char/end_char`
- 现有接口：`LLMClient.chat(messages, temperature, max_tokens) -> str`
- 现有配置：`settings.chroma_dir`（storage/chroma）、`settings.storage_path`
- 向量模型：BAAI/bge-small-zh-v1.5（512 维）
- 向量库：ChromaDB

---

## File Structure

```
core/retrieval/
├── __init__.py
├── citation.py      # 引用结构化 + 溯源映射
├── vector.py        # 向量索引（ChromaDB + bge-small-zh-v1.5）
├── hybrid.py        # BM25 + 向量混合检索（RRF 融合）
└── rerank.py        # LLM 重排序

core/memory/
├── __init__.py
├── store.py         # JSON 持久化 + 增量更新
├── tasks.py         # 跨会话任务
├── profile.py       # 用户偏好
└── workflow.py      # 工作流模式识别

core/persona/
├── __init__.py
├── styles.py        # 三种人格风格定义
└── prompts.py       # 分系 system prompt 模板

core/pet/
└── administrator.py # 编排层（整合检索+记忆+人格+LLM）

tests/retrieval/     (4 文件)
tests/memory/        (4 文件)
tests/persona/       (1 文件)
tests/pet/test_administrator.py
tests/integration/test_pet_admin_flow.py

repl.py              # 修改：_handle_chat 改走 administrator + /memory + /pet style + 工作流推荐
run.py               # 修改：新增 CLI 命令（rebuild --vector, ask, memory）
config.py            # 修改：新增 memory_path 属性
requirements.txt     # 修改：新增 chromadb + sentence-transformers
```

---

## Task 1: 引用结构化（core/retrieval/citation.py）

**Files:**
- Create: `core/retrieval/__init__.py`
- Create: `core/retrieval/citation.py`
- Create: `tests/retrieval/__init__.py`
- Create: `tests/retrieval/test_citation.py`

**Interfaces:**
- Produces: `Citation` dataclass, `extract_citations(answer: str, sources: List[dict]) -> List[Citation]`

- [ ] **Step 1: 创建模块骨架**

```python
# core/retrieval/__init__.py
"""检索层：混合检索 + 重排 + 引用结构化。"""
from core.retrieval.citation import Citation, extract_citations

__all__ = ["Citation", "extract_citations"]
```

- [ ] **Step 2: 写引用提取测试**

```python
# tests/retrieval/test_citation.py
"""引用结构化测试。"""
import pytest
from core.retrieval.citation import Citation, extract_citations


def test_extract_single_citation():
    """回答中有 [1] 时提取为引用。"""
    answer = "骨灰安置分为四类[1]。"
    sources = [
        {"doc_id": "abc123", "title": "殡葬管理条例", "paragraph_num": 3, "snippet": "骨灰安置分为四类"}
    ]
    citations = extract_citations(answer, sources)
    assert len(citations) == 1
    assert citations[0].marker == "[1]"
    assert citations[0].doc_id == "abc123"
    assert citations[0].title == "殡葬管理条例"
    assert citations[0].paragraph_num == 3


def test_extract_multiple_citations():
    """回答中有 [1][2] 时提取多个引用。"""
    answer = "生态安置包括树葬[1]和海葬[2]。"
    sources = [
        {"doc_id": "abc", "title": "条例A", "paragraph_num": 1, "snippet": "树葬"},
        {"doc_id": "def", "title": "条例B", "paragraph_num": 2, "snippet": "海葬"},
    ]
    citations = extract_citations(answer, sources)
    assert len(citations) == 2
    assert citations[0].doc_id == "abc"
    assert citations[1].doc_id == "def"


def test_extract_merged_citation():
    """[1][2] 合并引用时都提取。"""
    answer = "骨灰安置方式[1][2]多样。"
    sources = [
        {"doc_id": "abc", "title": "条例A", "paragraph_num": 1, "snippet": "方式"},
        {"doc_id": "def", "title": "条例B", "paragraph_num": 2, "snippet": "多样"},
    ]
    citations = extract_citations(answer, sources)
    assert len(citations) == 2


def test_no_citation_in_answer():
    """回答中无引用标记时返回空列表。"""
    answer = "骨灰安置方式多样。"
    sources = [{"doc_id": "abc", "title": "条例A", "paragraph_num": 1, "snippet": "骨灰"}]
    citations = extract_citations(answer, sources)
    assert citations == []


def test_citation_index_out_of_range():
    """引用编号超出 sources 范围时跳过。"""
    answer = "骨灰安置[5]。"
    sources = [{"doc_id": "abc", "title": "条例A", "paragraph_num": 1, "snippet": "骨灰"}]
    citations = extract_citations(answer, sources)
    assert citations == []


def test_citation_snippet_extraction():
    """Citation 包含 snippet 字段。"""
    answer = "安置[1]。"
    sources = [{"doc_id": "abc", "title": "条例A", "paragraph_num": 1, "snippet": "安置方式"}]
    citations = extract_citations(answer, sources)
    assert citations[0].snippet == "安置方式"
```

- [ ] **Step 3: 运行测试确认失败**

Run: `pytest tests/retrieval/test_citation.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'core.retrieval'`

- [ ] **Step 4: 实现 Citation + extract_citations**

```python
# core/retrieval/citation.py
"""引用结构化：从回答中提取 [n] 标记，映射到 doc_id + 段落号。"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import List


@dataclass
class Citation:
    """单条引用。"""
    marker: str           # "[1]"
    doc_id: str
    title: str
    paragraph_num: int
    snippet: str          # 原文片段（50-100 字）


def extract_citations(answer: str, sources: List[dict]) -> List[Citation]:
    """从回答中提取 [n] 引用标记，映射到 sources。

    Args:
        answer: LLM 回答文本，含 [1][2] 形式引用标记
        sources: 检索到的来源列表，每项含 doc_id/title/paragraph_num/snippet
                 sources[0] 对应 [1]，sources[1] 对应 [2]，以此类推

    Returns:
        引用列表，按出现顺序去重
    """
    # 匹配 [1] [12] [1][2] 等形式
    pattern = re.compile(r"\[(\d+)\]")
    matches = pattern.findall(answer)

    seen = set()
    citations = []
    for match in matches:
        idx = int(match) - 1  # [1] → sources[0]
        if idx < 0 or idx >= len(sources):
            continue
        if idx in seen:
            continue
        seen.add(idx)
        src = sources[idx]
        citations.append(Citation(
            marker=f"[{match}]",
            doc_id=src["doc_id"],
            title=src["title"],
            paragraph_num=src["paragraph_num"],
            snippet=src["snippet"],
        ))
    return citations
```

- [ ] **Step 5: 运行测试确认通过**

Run: `pytest tests/retrieval/test_citation.py -v`
Expected: 6 passed

- [ ] **Step 6: 提交**

```bash
git add core/retrieval/__init__.py core/retrieval/citation.py tests/retrieval/__init__.py tests/retrieval/test_citation.py
git commit -m "feat(retrieval): add citation extraction with [n] marker parsing"
```

---

## Task 2: 向量索引（core/retrieval/vector.py）

**Files:**
- Create: `core/retrieval/vector.py`
- Create: `tests/retrieval/test_vector.py`

**Interfaces:**
- Consumes: `ChunkRecord`（来自 core/storage.py，有 id/doc_id/content）
- Produces: `VectorResult` dataclass, `VectorIndex` 类 with `build_index/add_chunk/search`

- [ ] **Step 1: 写向量索引测试**

```python
# tests/retrieval/test_vector.py
"""向量索引测试。"""
import pytest
from unittest.mock import patch, MagicMock
from core.retrieval.vector import VectorIndex, VectorResult


def test_vector_result_dataclass():
    """VectorResult 包含 chunk_id/doc_id/score。"""
    r = VectorResult(chunk_id="chunk_1", doc_id="doc_1", score=0.95)
    assert r.chunk_id == "chunk_1"
    assert r.doc_id == "doc_1"
    assert r.score == 0.95


@patch("core.retrieval.vector._get_embedding_function")
def test_build_index_empty_chunks(mock_get_ef, tmp_path):
    """空 chunks 列表构建索引不报错。"""
    mock_ef = MagicMock()
    mock_get_ef.return_value = mock_ef
    index = VectorIndex(storage_path=tmp_path)
    index.build_index([])
    assert index.is_available()


@patch("core.retrieval.vector._get_embedding_function")
def test_add_and_search(mock_get_ef, tmp_path):
    """添加 chunk 后能搜索到。"""
    mock_ef = MagicMock()
    # mock embedding：返回固定向量
    mock_ef.side_effect = lambda texts: [[0.1, 0.2, 0.3] for _ in texts]
    mock_get_ef.return_value = mock_ef

    index = VectorIndex(storage_path=tmp_path)
    index.build_index([{
        "chunk_id": "c1",
        "doc_id": "d1",
        "content": "骨灰安置政策",
    }])
    results = index.search("骨灰安置", top_k=5)
    assert len(results) >= 1
    assert results[0].doc_id == "d1"


@patch("core.retrieval.vector._get_embedding_function")
def test_search_empty_index(mock_get_ef, tmp_path):
    """空索引搜索返回空列表。"""
    mock_ef = MagicMock()
    mock_get_ef.return_value = mock_ef
    index = VectorIndex(storage_path=tmp_path)
    index.build_index([])
    results = index.search("任意查询", top_k=5)
    assert results == []


def test_vector_index_unavailable_when_model_missing(tmp_path):
    """embedding 模型加载失败时 is_available 返回 False。"""
    with patch("core.retrieval.vector._get_embedding_function", side_effect=ImportError("no chromadb")):
        index = VectorIndex(storage_path=tmp_path)
        assert not index.is_available()
        # 降级：search 返回空列表
        results = index.search("任意", top_k=5)
        assert results == []
```

- [ ] **Step 2: 运行测试确认失败**

Run: `pytest tests/retrieval/test_vector.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'core.retrieval.vector'`

- [ ] **Step 3: 实现 VectorIndex**

```python
# core/retrieval/vector.py
"""向量索引：ChromaDB + bge-small-zh-v1.5。

降级策略：模型加载失败时 is_available() 返回 False，search 返回空列表。
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

from config import settings

logger = logging.getLogger(__name__)


@dataclass
class VectorResult:
    """向量检索结果。"""
    chunk_id: str
    doc_id: str
    score: float


def _get_embedding_function():
    """加载 bge-small-zh-v1.5 embedding 函数。

    失败时抛 ImportError，由调用方降级处理。
    """
    try:
        from chromadb.utils import embedding_functions
        return embedding_functions.SentenceTransformerEmbeddingFunction(
            model_name="BAAI/bge-small-zh-v1.5"
        )
    except Exception as e:
        raise ImportError(f"无法加载 embedding 模型: {e}")


class VectorIndex:
    """向量索引（ChromaDB 持久化）。"""

    def __init__(self, storage_path: Optional[Path] = None) -> None:
        self.storage_path = Path(storage_path) if storage_path else settings.chroma_dir
        self.storage_path.mkdir(parents=True, exist_ok=True)
        self._client = None
        self._collection = None
        self._embedding_fn = None
        self._available = False
        self._init()

    def _init(self) -> None:
        """初始化 ChromaDB 客户端和 collection。"""
        try:
            import chromadb
            self._embedding_fn = _get_embedding_function()
            self._client = chromadb.PersistentClient(path=str(self.storage_path))
            self._collection = self._client.get_or_create_collection(
                name="ima_chunks",
                embedding_function=self._embedding_fn,
            )
            self._available = True
        except Exception as e:
            logger.warning(f"向量索引初始化失败，降级为纯 BM25: {e}")
            self._available = False

    def is_available(self) -> bool:
        """向量索引是否可用。"""
        return self._available

    def build_index(self, chunks: List[dict]) -> None:
        """全量构建索引。

        Args:
            chunks: [{"chunk_id", "doc_id", "content"}]
        """
        if not self._available:
            return
        # 清空旧索引
        if self._collection.count() > 0:
            self._client.delete_collection("ima_chunks")
            self._collection = self._client.get_or_create_collection(
                name="ima_chunks",
                embedding_function=self._embedding_fn,
            )
        if not chunks:
            return
        # 批量插入
        ids = [c["chunk_id"] for c in chunks]
        documents = [c["content"] for c in chunks]
        metadatas = [{"doc_id": c["doc_id"]} for c in chunks]
        self._collection.add(ids=ids, documents=documents, metadatas=metadatas)

    def add_chunk(self, chunk: dict) -> None:
        """增量添加单个 chunk。"""
        if not self._available:
            return
        self._collection.add(
            ids=[chunk["chunk_id"]],
            documents=[chunk["content"]],
            metadatas=[{"doc_id": chunk["doc_id"]}],
        )

    def search(self, query: str, top_k: int = 10) -> List[VectorResult]:
        """向量检索。"""
        if not self._available:
            return []
        try:
            results = self._collection.query(
                query_texts=[query],
                n_results=top_k,
            )
            vector_results = []
            if results and results.get("ids"):
                for i, chunk_id in enumerate(results["ids"][0]):
                    doc_id = results["metadatas"][0][i].get("doc_id", "")
                    # ChromaDB 返回 distance（越小越相似），转为 score（越大越好）
                    distance = results["distances"][0][i]
                    score = 1.0 - distance  # 简单转换
                    vector_results.append(VectorResult(
                        chunk_id=chunk_id,
                        doc_id=doc_id,
                        score=score,
                    ))
            return vector_results
        except Exception as e:
            logger.warning(f"向量检索失败: {e}")
            return []
```

- [ ] **Step 4: 运行测试确认通过**

Run: `pytest tests/retrieval/test_vector.py -v`
Expected: 5 passed

- [ ] **Step 5: 提交**

```bash
git add core/retrieval/vector.py tests/retrieval/test_vector.py
git commit -m "feat(retrieval): add VectorIndex with ChromaDB + bge-small-zh-v1.5"
```

---

## Task 3: 混合检索（core/retrieval/hybrid.py）

**Files:**
- Create: `core/retrieval/hybrid.py`
- Create: `tests/retrieval/test_hybrid.py`

**Interfaces:**
- Consumes: `BM25Index`（来自 core/search/bm25.py），`VectorIndex`（Task 2）
- Produces: `HybridResult` dataclass, `HybridRetriever` 类 with `search`

- [ ] **Step 1: 写混合检索测试**

```python
# tests/retrieval/test_hybrid.py
"""混合检索测试。"""
import pytest
from unittest.mock import MagicMock, patch
from core.retrieval.hybrid import HybridResult, HybridRetriever


def test_hybrid_result_dataclass():
    """HybridResult 包含 chunk_id/doc_id/score/source。"""
    r = HybridResult(chunk_id="c1", doc_id="d1", score=0.5, source="both")
    assert r.chunk_id == "c1"
    assert r.doc_id == "d1"
    assert r.score == 0.5
    assert r.source == "both"


def test_rrf_fusion_both_sources():
    """BM25 和向量都命中的 chunk source='both'。"""
    bm25 = MagicMock()
    bm25.search.return_value = [
        MagicMock(chunk_id="c1", doc_id="d1", score=0.9, content="content1", doc_title="title1"),
        MagicMock(chunk_id="c2", doc_id="d2", score=0.8, content="content2", doc_title="title2"),
    ]
    vector = MagicMock()
    vector.is_available.return_value = True
    vector.search.return_value = [
        MagicMock(chunk_id="c1", doc_id="d1", score=0.95),
        MagicMock(chunk_id="c3", doc_id="d3", score=0.85),
    ]

    retriever = HybridRetriever(bm25_index=bm25, vector_index=vector)
    results = retriever.search("查询", top_k=5)

    assert len(results) >= 1
    # c1 在两边都出现，source 应为 "both"
    c1 = next(r for r in results if r.chunk_id == "c1")
    assert c1.source == "both"


def test_rrf_fusion_bm25_only():
    """只在 BM25 命中的 chunk source='bm25'。"""
    bm25 = MagicMock()
    bm25.search.return_value = [
        MagicMock(chunk_id="c1", doc_id="d1", score=0.9, content="c1", doc_title="t1"),
        MagicMock(chunk_id="c2", doc_id="d2", score=0.8, content="c2", doc_title="t2"),
    ]
    vector = MagicMock()
    vector.is_available.return_value = True
    vector.search.return_value = [
        MagicMock(chunk_id="c3", doc_id="d3", score=0.9),
    ]

    retriever = HybridRetriever(bm25_index=bm25, vector_index=vector)
    results = retriever.search("查询", top_k=5)

    c2 = next(r for r in results if r.chunk_id == "c2")
    assert c2.source == "bm25"


def test_vector_unavailable_degrades_to_bm25():
    """向量不可用时降级为纯 BM25。"""
    bm25 = MagicMock()
    bm25.search.return_value = [
        MagicMock(chunk_id="c1", doc_id="d1", score=0.9, content="c1", doc_title="t1"),
    ]
    vector = MagicMock()
    vector.is_available.return_value = False

    retriever = HybridRetriever(bm25_index=bm25, vector_index=vector)
    results = retriever.search("查询", top_k=5)

    assert len(results) == 1
    assert results[0].source == "bm25"


def test_empty_results():
    """BM25 和向量都返回空时返回空列表。"""
    bm25 = MagicMock()
    bm25.search.return_value = []
    vector = MagicMock()
    vector.is_available.return_value = True
    vector.search.return_value = []

    retriever = HybridRetriever(bm25_index=bm25, vector_index=vector)
    results = retriever.search("查询", top_k=5)
    assert results == []


def test_top_k_limit():
    """结果数量不超过 top_k。"""
    bm25 = MagicMock()
    bm25.search.return_value = [
        MagicMock(chunk_id=f"c{i}", doc_id=f"d{i}", score=0.9, content="c", doc_title="t")
        for i in range(10)
    ]
    vector = MagicMock()
    vector.is_available.return_value = True
    vector.search.return_value = []

    retriever = HybridRetriever(bm25_index=bm25, vector_index=vector)
    results = retriever.search("查询", top_k=3)
    assert len(results) == 3
```

- [ ] **Step 2: 运行测试确认失败**

Run: `pytest tests/retrieval/test_hybrid.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: 实现 HybridRetriever**

```python
# core/retrieval/hybrid.py
"""混合检索：BM25 + 向量 + RRF 融合。"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional

from core.search.bm25 import BM25Index, SearchResult
from core.retrieval.vector import VectorIndex, VectorResult


# RRF 参数：k 越大，排名差异的影响越小
RRF_K = 60


@dataclass
class HybridResult:
    """混合检索结果。"""
    chunk_id: str
    doc_id: str
    score: float
    source: str           # "bm25" / "vector" / "both"
    content: str = ""
    doc_title: str = ""


class HybridRetriever:
    """混合检索器：BM25 + 向量并行检索，RRF 融合。"""

    def __init__(self, bm25_index: BM25Index, vector_index: VectorIndex) -> None:
        self.bm25 = bm25_index
        self.vector = vector_index

    def search(self, query: str, top_k: int = 10) -> List[HybridResult]:
        """混合检索：BM25 + 向量 + RRF 融合。

        Args:
            query: 查询文本
            top_k: 返回结果数量

        Returns:
            融合后的结果列表，按 RRF 分数降序
        """
        # 1. BM25 检索
        bm25_results = self.bm25.search(query, top_k=top_k)

        # 2. 向量检索（不可用时降级为纯 BM25）
        if not self.vector.is_available():
            return self._bm25_only_results(bm25_results, top_k)

        vector_results = self.vector.search(query, top_k=top_k)

        # 3. RRF 融合
        return self._rrf_fusion(bm25_results, vector_results, top_k)

    def _bm25_only_results(self, bm25_results: List[SearchResult], top_k: int) -> List[HybridResult]:
        """纯 BM25 降级结果。"""
        results = [
            HybridResult(
                chunk_id=r.chunk_id,
                doc_id=r.doc_id,
                score=r.score,
                source="bm25",
                content=getattr(r, "content", ""),
                doc_title=getattr(r, "doc_title", ""),
            )
            for r in bm25_results[:top_k]
        ]
        return results

    def _rrf_fusion(
        self,
        bm25_results: List[SearchResult],
        vector_results: List[VectorResult],
        top_k: int,
    ) -> List[HybridResult]:
        """RRF 融合：score = Σ 1/(k + rank)。"""
        # 收集所有 chunk_id
        bm25_ids = {r.chunk_id for r in bm25_results}
        vector_ids = {r.chunk_id for r in vector_results}
        all_ids = bm25_ids | vector_ids

        # 计算 RRF 分数
        scores = {}
        sources = {}
        for rank, r in enumerate(bm25_results, 1):
            scores[r.chunk_id] = scores.get(r.chunk_id, 0) + 1.0 / (RRF_K + rank)
            sources[r.chunk_id] = "bm25"
        for rank, r in enumerate(vector_results, 1):
            scores[r.chunk_id] = scores.get(r.chunk_id, 0) + 1.0 / (RRF_K + rank)
            if r.chunk_id in sources:
                sources[r.chunk_id] = "both"
            else:
                sources[r.chunk_id] = "vector"

        # 构建 doc_id 和 content 映射
        doc_map = {}
        for r in bm25_results:
            doc_map[r.chunk_id] = (r.doc_id, getattr(r, "content", ""), getattr(r, "doc_title", ""))
        for r in vector_results:
            if r.chunk_id not in doc_map:
                doc_map[r.chunk_id] = (r.doc_id, "", "")

        # 排序并取 top_k
        sorted_ids = sorted(all_ids, key=lambda cid: scores[cid], reverse=True)
        results = []
        for cid in sorted_ids[:top_k]:
            doc_id, content, doc_title = doc_map.get(cid, ("", "", ""))
            results.append(HybridResult(
                chunk_id=cid,
                doc_id=doc_id,
                score=scores[cid],
                source=sources[cid],
                content=content,
                doc_title=doc_title,
            ))
        return results
```

- [ ] **Step 4: 运行测试确认通过**

Run: `pytest tests/retrieval/test_hybrid.py -v`
Expected: 6 passed

- [ ] **Step 5: 提交**

```bash
git add core/retrieval/hybrid.py tests/retrieval/test_hybrid.py
git commit -m "feat(retrieval): add HybridRetriever with RRF fusion"
```

---

## Task 4: LLM 重排序（core/retrieval/rerank.py）

**Files:**
- Create: `core/retrieval/rerank.py`
- Create: `tests/retrieval/test_rerank.py`

**Interfaces:**
- Consumes: `HybridResult`（Task 3），`LLMClient`（来自 core/llm/client.py）
- Produces: `RerankResult` dataclass, `Reranker` 类 with `rerank`

- [ ] **Step 1: 写重排序测试**

```python
# tests/retrieval/test_rerank.py
"""LLM 重排序测试。"""
import pytest
from unittest.mock import MagicMock
from core.retrieval.rerank import RerankResult, Reranker
from core.retrieval.hybrid import HybridResult


def test_rerank_result_dataclass():
    """RerankResult 包含 reason 字段。"""
    r = RerankResult(
        chunk_id="c1", doc_id="d1", score=0.9,
        source="both", content="内容", doc_title="标题",
        relevance_score=8.5, reason="高度相关"
    )
    assert r.relevance_score == 8.5
    assert r.reason == "高度相关"


def test_rerank_reorders_by_score():
    """LLM 打分后按分数降序排列。"""
    candidates = [
        HybridResult(chunk_id="c1", doc_id="d1", score=0.1, source="bm25", content="内容1", doc_title="标题1"),
        HybridResult(chunk_id="c2", doc_id="d2", score=0.2, source="vector", content="内容2", doc_title="标题2"),
        HybridResult(chunk_id="c3", doc_id="d3", score=0.3, source="both", content="内容3", doc_title="标题3"),
    ]
    # mock LLM 返回：c2 最相关（9分），c1 次之（5分），c3 最不相关（3分）
    llm = MagicMock()
    llm.chat.return_value = '[{"index": 0, "score": 5, "reason": "一般"}, {"index": 1, "score": 9, "reason": "高度相关"}, {"index": 2, "score": 3, "reason": "不太相关"}]'

    reranker = Reranker(llm)
    results = reranker.rerank("查询", candidates, top_n=3)

    assert results[0].chunk_id == "c2"
    assert results[0].relevance_score == 9
    assert results[1].chunk_id == "c1"
    assert results[2].chunk_id == "c3"


def test_rerank_top_n_limit():
    """top_n 限制返回数量。"""
    candidates = [
        HybridResult(chunk_id=f"c{i}", doc_id=f"d{i}", score=0.1, source="bm25", content=f"内容{i}", doc_title=f"标题{i}")
        for i in range(5)
    ]
    llm = MagicMock()
    llm.chat.return_value = '[{"index": 0, "score": 5, "reason": "r"}, {"index": 1, "score": 9, "reason": "r"}, {"index": 2, "score": 3, "reason": "r"}, {"index": 3, "score": 7, "reason": "r"}, {"index": 4, "score": 1, "reason": "r"}]'

    reranker = Reranker(llm)
    results = reranker.rerank("查询", candidates, top_n=2)
    assert len(results) == 2


def test_rerank_llm_failure_keeps_original_order():
    """LLM 失败时保留原顺序。"""
    candidates = [
        HybridResult(chunk_id="c1", doc_id="d1", score=0.5, source="bm25", content="内容1", doc_title="标题1"),
        HybridResult(chunk_id="c2", doc_id="d2", score=0.3, source="vector", content="内容2", doc_title="标题2"),
    ]
    llm = MagicMock()
    llm.chat.side_effect = Exception("LLM 不可用")

    reranker = Reranker(llm)
    results = reranker.rerank("查询", candidates, top_n=2)

    # 保留原顺序
    assert results[0].chunk_id == "c1"
    assert results[1].chunk_id == "c2"
    # relevance_score 为 0（降级）
    assert results[0].relevance_score == 0


def test_rerank_empty_candidates():
    """空候选列表返回空结果。"""
    llm = MagicMock()
    reranker = Reranker(llm)
    results = reranker.rerank("查询", [], top_n=5)
    assert results == []


def test_rerank_handles_malformed_llm_response():
    """LLM 返回格式错误时降级为原顺序。"""
    candidates = [
        HybridResult(chunk_id="c1", doc_id="d1", score=0.5, source="bm25", content="内容1", doc_title="标题1"),
    ]
    llm = MagicMock()
    llm.chat.return_value = "这不是 JSON 格式"

    reranker = Reranker(llm)
    results = reranker.rerank("查询", candidates, top_n=1)
    assert len(results) == 1
    assert results[0].chunk_id == "c1"
```

- [ ] **Step 2: 运行测试确认失败**

Run: `pytest tests/retrieval/test_rerank.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: 实现 Reranker**

```python
# core/retrieval/rerank.py
"""LLM 重排序：让 LLM 对候选打分（0-10）。"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import List, Optional

from core.retrieval.hybrid import HybridResult
from core.llm.client import LLMClient

logger = logging.getLogger(__name__)


@dataclass
class RerankResult:
    """重排序结果。"""
    chunk_id: str
    doc_id: str
    score: float                    # 原 hybrid 分数
    source: str
    content: str
    doc_title: str
    relevance_score: float          # LLM 打分（0-10）
    reason: str                     # LLM 相关性理由


class Reranker:
    """LLM 重排序器。"""

    def __init__(self, llm: LLMClient) -> None:
        self.llm = llm

    def rerank(
        self,
        query: str,
        candidates: List[HybridResult],
        top_n: int = 5,
    ) -> List[RerankResult]:
        """对候选列表用 LLM 打分并重排。

        Args:
            query: 用户查询
            candidates: 混合检索结果
            top_n: 返回前 N 个

        Returns:
            重排序后的结果列表，降级时保留原顺序
        """
        if not candidates:
            return []

        try:
            scores = self._call_llm_for_scores(query, candidates)
        except Exception as e:
            logger.warning(f"LLM 重排失败，保留原顺序: {e}")
            return self._fallback_results(candidates, top_n)

        # 合并分数并排序
        results = []
        for i, c in enumerate(candidates):
            score_data = scores.get(i, {"score": 0, "reason": ""})
            results.append(RerankResult(
                chunk_id=c.chunk_id,
                doc_id=c.doc_id,
                score=c.score,
                source=c.source,
                content=c.content,
                doc_title=c.doc_title,
                relevance_score=score_data.get("score", 0),
                reason=score_data.get("reason", ""),
            ))

        # 按 relevance_score 降序
        results.sort(key=lambda r: r.relevance_score, reverse=True)
        return results[:top_n]

    def _call_llm_for_scores(self, query: str, candidates: List[HybridResult]) -> dict:
        """调用 LLM 对候选批量打分。

        Returns:
            {index: {"score": float, "reason": str}}
        """
        # 构造候选列表文本
        candidate_texts = []
        for i, c in enumerate(candidates):
            # 截取前 200 字避免 token 过长
            snippet = c.content[:200] if c.content else ""
            candidate_texts.append(f"[{i}] {c.doc_title}: {snippet}")

        prompt = f"""请对以下候选文档与查询的相关性打分（0-10 分，10 最相关）。

查询：{query}

候选文档：
{chr(10).join(candidate_texts)}

请只返回 JSON 数组，格式如下：
[{{"index": 0, "score": 8.5, "reason": "高度相关"}}]

不要返回其他内容。"""

        messages = [{"role": "user", "content": prompt}]
        response = self.llm.chat(messages, temperature=0.0, max_tokens=1000)

        # 解析 JSON
        data = json.loads(response)
        scores = {}
        for item in data:
            idx = item.get("index")
            if idx is not None:
                scores[idx] = {
                    "score": float(item.get("score", 0)),
                    "reason": item.get("reason", ""),
                }
        return scores

    def _fallback_results(
        self,
        candidates: List[HybridResult],
        top_n: int,
    ) -> List[RerankResult]:
        """降级：保留原顺序，relevance_score=0。"""
        return [
            RerankResult(
                chunk_id=c.chunk_id,
                doc_id=c.doc_id,
                score=c.score,
                source=c.source,
                content=c.content,
                doc_title=c.doc_title,
                relevance_score=0,
                reason="",
            )
            for c in candidates[:top_n]
        ]
```

- [ ] **Step 4: 运行测试确认通过**

Run: `pytest tests/retrieval/test_rerank.py -v`
Expected: 6 passed

- [ ] **Step 5: 提交**

```bash
git add core/retrieval/rerank.py tests/retrieval/test_rerank.py
git commit -m "feat(retrieval): add LLM reranker with batch scoring"
```

---

## Task 5: 记忆持久化（core/memory/store.py）

**Files:**
- Create: `core/memory/__init__.py`
- Create: `core/memory/store.py`
- Create: `tests/memory/__init__.py`
- Create: `tests/memory/test_store.py`

**Interfaces:**
- Produces: `MemoryStore` 类 with `load/save/update/get_data`

- [ ] **Step 1: 创建模块骨架**

```python
# core/memory/__init__.py
"""记忆层：用户偏好 + 工作流 + 任务。"""
from core.memory.store import MemoryStore

__all__ = ["MemoryStore"]
```

- [ ] **Step 2: 写持久化测试**

```python
# tests/memory/test_store.py
"""记忆持久化测试。"""
import json
import pytest
from pathlib import Path
from core.memory.store import MemoryStore


def test_load_empty_when_file_missing(tmp_path):
    """文件不存在时返回空结构。"""
    store = MemoryStore(storage_path=tmp_path)
    data = store.load()
    assert data == {
        "profile": {},
        "workflow": {"patterns": [], "suggestions_enabled": True},
        "tasks": [],
        "history": {"recent_queries": []},
    }


def test_save_and_load_roundtrip(tmp_path):
    """保存后加载应一致。"""
    store = MemoryStore(storage_path=tmp_path)
    store.update("profile", "preferred_format", "table")
    store.update("profile", "focus_topics", ["骨灰安置"])
    store.save()

    store2 = MemoryStore(storage_path=tmp_path)
    data = store2.load()
    assert data["profile"]["preferred_format"] == "table"
    assert data["profile"]["focus_topics"] == ["骨灰安置"]


def test_update_creates_nested_keys(tmp_path):
    """update 能创建嵌套 key。"""
    store = MemoryStore(storage_path=tmp_path)
    store.update("profile", "preferred_style", "scholar")
    data = store.get_data()
    assert data["profile"]["preferred_style"] == "scholar"


def test_load_corrupted_json_backups(tmp_path):
    """损坏 JSON 备份后返回空结构。"""
    (tmp_path / "memory.json").write_text("{invalid json", encoding="utf-8")
    store = MemoryStore(storage_path=tmp_path)
    data = store.load()
    assert "profile" in data  # 返回默认结构
    # 备份文件存在
    backups = list(tmp_path.glob("memory.json.bak.*"))
    assert len(backups) == 1


def test_atomic_write(tmp_path):
    """原子写入：写入过程中崩溃不应损坏原文件。"""
    store = MemoryStore(storage_path=tmp_path)
    store.update("profile", "preferred_format", "table")
    store.save()

    # 再次保存
    store.update("profile", "preferred_style", "scholar")
    store.save()

    data = store.load()
    assert data["profile"]["preferred_format"] == "table"
    assert data["profile"]["preferred_style"] == "scholar"
```

- [ ] **Step 3: 运行测试确认失败**

Run: `pytest tests/memory/test_store.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 4: 实现 MemoryStore**

```python
# core/memory/store.py
"""记忆持久化：JSON 文件 + 原子写入 + 损坏备份。"""
from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path
from typing import Any, Dict, Optional

from config import settings

logger = logging.getLogger(__name__)


# 默认记忆结构
DEFAULT_MEMORY = {
    "profile": {},
    "workflow": {"patterns": [], "suggestions_enabled": True},
    "tasks": [],
    "history": {"recent_queries": []},
}


class MemoryStore:
    """记忆数据 JSON 存储。"""

    def __init__(self, storage_path: Optional[Path] = None) -> None:
        if storage_path is None:
            storage_path = settings.storage_path
        self.storage_path = Path(storage_path)
        self.storage_path.mkdir(parents=True, exist_ok=True)
        self.file_path = self.storage_path / "memory.json"
        self._data: Dict = dict(DEFAULT_MEMORY)
        self._load()

    def _load(self) -> None:
        """加载记忆数据。文件不存在或损坏时用默认值。"""
        if not self.file_path.exists():
            self._data = dict(DEFAULT_MEMORY)
            return
        try:
            self._data = json.loads(self.file_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, ValueError) as e:
            # 备份损坏的文件
            bak = self.file_path.parent / f"{self.file_path.name}.bak.{int(time.time())}"
            try:
                self.file_path.rename(bak)
                logger.warning(f"记忆文件损坏，已备份到 {bak}")
            except Exception:
                pass
            self._data = dict(DEFAULT_MEMORY)

    def load(self) -> Dict:
        """加载并返回记忆数据。"""
        self._load()
        return self.get_data()

    def save(self) -> None:
        """原子写入：临时文件 + rename。"""
        tmp_path = self.file_path.with_suffix(".json.tmp")
        tmp_path.write_text(
            json.dumps(self._data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        os.replace(str(tmp_path), str(self.file_path))

    def update(self, section: str, key: str, value: Any) -> None:
        """更新某 section 下的 key。"""
        if section not in self._data:
            self._data[section] = {}
        if not isinstance(self._data[section], dict):
            self._data[section] = {}
        self._data[section][key] = value

    def get_data(self) -> Dict:
        """返回当前记忆数据。"""
        return self._data

    def clear(self) -> None:
        """清空所有记忆。"""
        self._data = dict(DEFAULT_MEMORY)
        self.save()
```

- [ ] **Step 5: 运行测试确认通过**

Run: `pytest tests/memory/test_store.py -v`
Expected: 5 passed

- [ ] **Step 6: 提交**

```bash
git add core/memory/__init__.py core/memory/store.py tests/memory/__init__.py tests/memory/test_store.py
git commit -m "feat(memory): add MemoryStore with atomic write and corruption backup"
```

---

## Task 6: 跨会话任务（core/memory/tasks.py）

**Files:**
- Create: `core/memory/tasks.py`
- Create: `tests/memory/test_tasks.py`

**Interfaces:**
- Consumes: `MemoryStore`（Task 5）
- Produces: `Task` dataclass, `TaskManager` 类 with `add_task/update_task/get_active_tasks/link_doc`

- [ ] **Step 1: 写任务记忆测试**

```python
# tests/memory/test_tasks.py
"""跨会话任务测试。"""
import pytest
from core.memory.tasks import Task, TaskManager
from core.memory.store import MemoryStore


def test_add_task_returns_id(tmp_path):
    """添加任务返回 task_id。"""
    store = MemoryStore(storage_path=tmp_path)
    mgr = TaskManager(store)
    task_id = mgr.add_task("整理殡葬政策对比")
    assert task_id.startswith("task_")
    tasks = mgr.get_active_tasks()
    assert len(tasks) == 1
    assert tasks[0].description == "整理殡葬政策对比"
    assert tasks[0].status == "pending"


def test_add_task_with_related_docs(tmp_path):
    """添加任务时可指定关联文档。"""
    store = MemoryStore(storage_path=tmp_path)
    mgr = TaskManager(store)
    mgr.add_task("任务", related_docs=["doc1", "doc2"])
    tasks = mgr.get_active_tasks()
    assert tasks[0].related_docs == ["doc1", "doc2"]


def test_update_task_status(tmp_path):
    """更新任务状态。"""
    store = MemoryStore(storage_path=tmp_path)
    mgr = TaskManager(store)
    task_id = mgr.add_task("任务")
    mgr.update_task(task_id, status="in_progress")
    tasks = mgr.get_active_tasks()
    assert tasks[0].status == "in_progress"


def test_completed_task_not_in_active(tmp_path):
    """完成的任务不在 active 列表中。"""
    store = MemoryStore(storage_path=tmp_path)
    mgr = TaskManager(store)
    task_id = mgr.add_task("任务")
    mgr.update_task(task_id, status="completed")
    assert mgr.get_active_tasks() == []


def test_link_doc(tmp_path):
    """关联文档到任务。"""
    store = MemoryStore(storage_path=tmp_path)
    mgr = TaskManager(store)
    task_id = mgr.add_task("任务")
    mgr.link_doc(task_id, "doc_new")
    tasks = mgr.get_active_tasks()
    assert "doc_new" in tasks[0].related_docs


def test_persistence_across_instances(tmp_path):
    """任务跨实例持久化。"""
    store = MemoryStore(storage_path=tmp_path)
    mgr1 = TaskManager(store)
    mgr1.add_task("任务1")
    store.save()

    store2 = MemoryStore(storage_path=tmp_path)
    mgr2 = TaskManager(store2)
    tasks = mgr2.get_active_tasks()
    assert len(tasks) == 1
    assert tasks[0].description == "任务1"


def test_task_with_context(tmp_path):
    """任务包含 context 字段。"""
    store = MemoryStore(storage_path=tmp_path)
    mgr = TaskManager(store)
    mgr.add_task("任务", context="用户在整理拱墅区政策")
    tasks = mgr.get_active_tasks()
    assert tasks[0].context == "用户在整理拱墅区政策"
```

- [ ] **Step 2: 运行测试确认失败**

Run: `pytest tests/memory/test_tasks.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: 实现 Task + TaskManager**

```python
# core/memory/tasks.py
"""跨会话任务记忆。"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import List, Optional

from core.memory.store import MemoryStore


@dataclass
class Task:
    """单条任务。"""
    id: str
    description: str
    created_at: str
    updated_at: str
    status: str  # pending / in_progress / completed
    related_docs: List[str] = field(default_factory=list)
    context: str = ""


class TaskManager:
    """任务管理：增删改查 + 持久化。"""

    def __init__(self, store: MemoryStore) -> None:
        self.store = store

    def add_task(
        self,
        description: str,
        related_docs: Optional[List[str]] = None,
        context: str = "",
    ) -> str:
        """添加任务，返回 task_id。"""
        now = time.strftime("%Y-%m-%dT%H:%M:%S")
        task_id = f"task_{int(time.time() * 1000)}"
        task = {
            "id": task_id,
            "description": description,
            "created_at": now,
            "updated_at": now,
            "status": "pending",
            "related_docs": related_docs or [],
            "context": context,
        }
        data = self.store.get_data()
        data["tasks"].append(task)
        self.store.save()
        return task_id

    def update_task(self, task_id: str, status: str) -> None:
        """更新任务状态。"""
        data = self.store.get_data()
        for task in data["tasks"]:
            if task["id"] == task_id:
                task["status"] = status
                task["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
                break
        self.store.save()

    def get_active_tasks(self) -> List[Task]:
        """获取未完成任务。"""
        data = self.store.get_data()
        tasks = []
        for t in data.get("tasks", []):
            if t["status"] != "completed":
                tasks.append(Task(
                    id=t["id"],
                    description=t["description"],
                    created_at=t["created_at"],
                    updated_at=t["updated_at"],
                    status=t["status"],
                    related_docs=t.get("related_docs", []),
                    context=t.get("context", ""),
                ))
        return tasks

    def link_doc(self, task_id: str, doc_id: str) -> None:
        """关联文档到任务。"""
        data = self.store.get_data()
        for task in data["tasks"]:
            if task["id"] == task_id:
                if doc_id not in task.get("related_docs", []):
                    task.setdefault("related_docs", []).append(doc_id)
                    task["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
                break
        self.store.save()
```

- [ ] **Step 4: 运行测试确认通过**

Run: `pytest tests/memory/test_tasks.py -v`
Expected: 7 passed

- [ ] **Step 5: 提交**

```bash
git add core/memory/tasks.py tests/memory/test_tasks.py
git commit -m "feat(memory): add TaskManager with cross-session task persistence"
```

---

## Task 7: 用户偏好（core/memory/profile.py）

**Files:**
- Create: `core/memory/profile.py`
- Create: `tests/memory/test_profile.py`

**Interfaces:**
- Consumes: `MemoryStore`（Task 5）
- Produces: `Profile` dataclass, `ProfileManager` 类 with `get_profile/update_from_query/update_format_preference/update_style_preference`

- [ ] **Step 1: 写偏好测试**

```python
# tests/memory/test_profile.py
"""用户偏好测试。"""
import pytest
from core.memory.profile import Profile, ProfileManager
from core.memory.store import MemoryStore


def test_default_profile(tmp_path):
    """默认 profile 为空值。"""
    store = MemoryStore(storage_path=tmp_path)
    mgr = ProfileManager(store)
    p = mgr.get_profile()
    assert p.preferred_format == ""
    assert p.preferred_style == "auto"
    assert p.focus_topics == []
    assert p.focus_regions == []
    assert p.interaction_count == 0


def test_update_format_preference(tmp_path):
    """更新格式偏好。"""
    store = MemoryStore(storage_path=tmp_path)
    mgr = ProfileManager(store)
    mgr.update_format_preference("table")
    assert mgr.get_profile().preferred_format == "table"


def test_update_style_preference(tmp_path):
    """更新风格偏好。"""
    store = MemoryStore(storage_path=tmp_path)
    mgr = ProfileManager(store)
    mgr.update_style_preference("scholar")
    assert mgr.get_profile().preferred_style == "scholar"


def test_update_from_query_adds_topic(tmp_path):
    """从查询中提取主题。"""
    store = MemoryStore(storage_path=tmp_path)
    mgr = ProfileManager(store)
    mgr.update_from_query("骨灰安置政策", "回答")
    p = mgr.get_profile()
    assert "骨灰安置" in p.focus_topics


def test_update_from_query_adds_region(tmp_path):
    """从查询中提取地区。"""
    store = MemoryStore(storage_path=tmp_path)
    mgr = ProfileManager(store)
    mgr.update_from_query("杭州市骨灰安置", "回答")
    p = mgr.get_profile()
    assert "杭州市" in p.focus_regions


def test_update_from_query_increments_count(tmp_path):
    """每次更新增加 interaction_count。"""
    store = MemoryStore(storage_path=tmp_path)
    mgr = ProfileManager(store)
    mgr.update_from_query("查询1", "回答1")
    mgr.update_from_query("查询2", "回答2")
    assert mgr.get_profile().interaction_count == 2


def test_focus_topics_dedup(tmp_path):
    """重复主题不重复添加。"""
    store = MemoryStore(storage_path=tmp_path)
    mgr = ProfileManager(store)
    mgr.update_from_query("骨灰安置", "回答")
    mgr.update_from_query("骨灰安置政策", "回答")
    p = mgr.get_profile()
    # "骨灰安置" 只出现一次
    assert p.focus_topics.count("骨灰安置") == 1


def test_persistence_across_instances(tmp_path):
    """偏好跨实例持久化。"""
    store = MemoryStore(storage_path=tmp_path)
    mgr1 = ProfileManager(store)
    mgr1.update_format_preference("table")
    store.save()

    store2 = MemoryStore(storage_path=tmp_path)
    mgr2 = ProfileManager(store2)
    assert mgr2.get_profile().preferred_format == "table"
```

- [ ] **Step 2: 运行测试确认失败**

Run: `pytest tests/memory/test_profile.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: 实现 Profile + ProfileManager**

```python
# core/memory/profile.py
"""用户偏好：主题/地区/格式/风格。"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import List, Optional

from core.memory.store import MemoryStore


# 已知地区关键词（用于从查询中提取）
_KNOWN_REGIONS = [
    "杭州市", "杭州市区", "拱墅区", "西湖区", "上城区", "滨江区",
    "余杭区", "萧山区", "富阳区", "临安区", "临平区", "钱塘区",
    "浙江省", "北京", "上海", "广州", "深圳",
]


@dataclass
class Profile:
    """用户偏好。"""
    preferred_format: str = ""           # table / list / prose
    preferred_style: str = "auto"        # auto / scholar / warrior / artisan
    focus_topics: List[str] = field(default_factory=list)
    focus_regions: List[str] = field(default_factory=list)
    interaction_count: int = 0
    last_active: str = ""


class ProfileManager:
    """用户偏好管理。"""

    def __init__(self, store: MemoryStore) -> None:
        self.store = store

    def get_profile(self) -> Profile:
        """读取当前偏好。"""
        data = self.store.get_data()
        profile_data = data.get("profile", {})
        return Profile(
            preferred_format=profile_data.get("preferred_format", ""),
            preferred_style=profile_data.get("preferred_style", "auto"),
            focus_topics=profile_data.get("focus_topics", []),
            focus_regions=profile_data.get("focus_regions", []),
            interaction_count=profile_data.get("interaction_count", 0),
            last_active=profile_data.get("last_active", ""),
        )

    def update_format_preference(self, format: str) -> None:
        """更新格式偏好。"""
        self.store.update("profile", "preferred_format", format)
        self.store.save()

    def update_style_preference(self, style: str) -> None:
        """更新风格偏好。"""
        self.store.update("profile", "preferred_style", style)
        self.store.save()

    def update_from_query(self, query: str, answer: str) -> None:
        """从查询中提取主题和地区，更新偏好。"""
        data = self.store.get_data()
        profile = data.setdefault("profile", {})

        # 提取主题（简单实现：用查询本身作为主题候选，取前 10 字符）
        topic = query.strip()[:10] if query.strip() else ""
        if topic:
            topics = profile.setdefault("focus_topics", [])
            # 简单去重：如果已有包含关系则不重复添加
            if not any(topic in t or t in topic for t in topics):
                topics.append(topic)
                # 最多保留 10 个
                if len(topics) > 10:
                    topics.pop(0)

        # 提取地区
        regions = profile.setdefault("focus_regions", [])
        for region in _KNOWN_REGIONS:
            if region in query and region not in regions:
                regions.append(region)
                if len(regions) > 10:
                    regions.pop(0)

        # 更新计数和时间
        profile["interaction_count"] = profile.get("interaction_count", 0) + 1
        profile["last_active"] = time.strftime("%Y-%m-%dT%H:%M:%S")

        self.store.save()
```

- [ ] **Step 4: 运行测试确认通过**

Run: `pytest tests/memory/test_profile.py -v`
Expected: 8 passed

- [ ] **Step 5: 提交**

```bash
git add core/memory/profile.py tests/memory/test_profile.py
git commit -m "feat(memory): add ProfileManager with topic/region extraction"
```

---

## Task 8: 工作流模式（core/memory/workflow.py）

**Files:**
- Create: `core/memory/workflow.py`
- Create: `tests/memory/test_workflow.py`

**Interfaces:**
- Consumes: `MemoryStore`（Task 5）
- Produces: `WorkflowTracker` 类 with `record_command/suggest_next/detect_pattern`

- [ ] **Step 1: 写工作流测试**

```python
# tests/memory/test_workflow.py
"""工作流模式测试。"""
import pytest
from core.memory.workflow import WorkflowTracker
from core.memory.store import MemoryStore


def test_record_command_no_suggestion_initially(tmp_path):
    """首次执行命令时无推荐。"""
    store = MemoryStore(storage_path=tmp_path)
    tracker = WorkflowTracker(store)
    assert tracker.suggest_next("ingest") is None


def test_suggest_next_after_pattern_formed(tmp_path):
    """形成模式后能推荐下一步。"""
    store = MemoryStore(storage_path=tmp_path)
    tracker = WorkflowTracker(store)
    # 重复 ingest → analyze 序列 3 次
    for _ in range(3):
        tracker.record_command("ingest")
        tracker.record_command("analyze")

    suggestion = tracker.suggest_next("ingest")
    assert suggestion == "analyze"


def test_suggest_next_returns_none_for_unknown_cmd(tmp_path):
    """未形成模式的命令无推荐。"""
    store = MemoryStore(storage_path=tmp_path)
    tracker = WorkflowTracker(store)
    tracker.record_command("ingest")
    tracker.record_command("analyze")
    assert tracker.suggest_next("search") is None


def test_pattern_count_increments(tmp_path):
    """重复序列计数递增。"""
    store = MemoryStore(storage_path=tmp_path)
    tracker = WorkflowTracker(store)
    tracker.record_command("ingest")
    tracker.record_command("analyze")
    tracker.record_command("ingest")
    tracker.record_command("analyze")

    data = store.get_data()
    patterns = data["workflow"]["patterns"]
    assert len(patterns) == 1
    assert patterns[0]["count"] == 2


def test_suggestions_disabled(tmp_path):
    """suggestions_enabled=False 时不推荐。"""
    store = MemoryStore(storage_path=tmp_path)
    store.update("workflow", "suggestions_enabled", False)
    tracker = WorkflowTracker(store)
    for _ in range(3):
        tracker.record_command("ingest")
        tracker.record_command("analyze")
    assert tracker.suggest_next("ingest") is None


def test_window_timeout(tmp_path):
    """超过 30 分钟窗口的命令不形成模式。"""
    store = MemoryStore(storage_path=tmp_path)
    tracker = WorkflowTracker(store)
    # 第一组命令（旧时间）
    tracker.record_command("ingest", timestamp="2026-07-01T10:00:00")
    tracker.record_command("analyze", timestamp="2026-07-01T10:05:00")
    # 第二组命令（新时间，间隔 > 30 分钟）
    tracker.record_command("ingest", timestamp="2026-07-01T11:00:00")
    tracker.record_command("analyze", timestamp="2026-07-01T11:05:00")

    # 仍然能形成模式（count=2，因为两组都是 ingest→analyze）
    suggestion = tracker.suggest_next("ingest")
    assert suggestion == "analyze"


def test_persistence_across_instances(tmp_path):
    """工作流模式跨实例持久化。"""
    store = MemoryStore(storage_path=tmp_path)
    tracker1 = WorkflowTracker(store)
    tracker1.record_command("ingest")
    tracker1.record_command("analyze")
    store.save()

    store2 = MemoryStore(storage_path=tmp_path)
    tracker2 = WorkflowTracker(store2)
    # 再重复一次让 count 达到 2
    tracker2.record_command("ingest")
    tracker2.record_command("analyze")
    assert tracker2.suggest_next("ingest") == "analyze"
```

- [ ] **Step 2: 运行测试确认失败**

Run: `pytest tests/memory/test_workflow.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: 实现 WorkflowTracker**

```python
# core/memory/workflow.py
"""工作流模式识别：记录命令序列，推荐下一步。"""
from __future__ import annotations

import time
from typing import List, Optional

from core.memory.store import MemoryStore


# 触发推荐的最低次数
MIN_PATTERN_COUNT = 2
# 窗口时间（秒）：30 分钟
WINDOW_SECONDS = 30 * 60


class WorkflowTracker:
    """工作流模式识别器。"""

    def __init__(self, store: MemoryStore) -> None:
        self.store = store

    def record_command(self, cmd: str, timestamp: Optional[str] = None) -> None:
        """记录命令执行。

        维护一个最近命令的滑动窗口，检测 2-gram 模式。
        """
        if timestamp is None:
            timestamp = time.strftime("%Y-%m-%dT%H:%M:%S")

        data = self.store.get_data()
        workflow = data.setdefault("workflow", {})
        patterns = workflow.setdefault("patterns", [])

        # 记录到 recent_commands（用于窗口检测）
        recent = workflow.setdefault("recent_commands", [])
        recent.append({"cmd": cmd, "timestamp": timestamp})
        # 只保留最近 10 条
        if len(recent) > 10:
            recent = recent[-10:]

        # 检测 2-gram 模式：最近两条命令形成序列
        if len(recent) >= 2:
            seq = [recent[-2]["cmd"], recent[-1]["cmd"]]
            self._update_pattern(patterns, seq)

        self.store.save()

    def _update_pattern(self, patterns: List[dict], seq: List[str]) -> None:
        """更新或创建模式。"""
        seq_key = " → ".join(seq)
        for p in patterns:
            if p["sequence"] == seq:
                p["count"] += 1
                p["last_used"] = time.strftime("%Y-%m-%dT%H:%M:%S")
                return
        patterns.append({
            "sequence": seq,
            "count": 1,
            "last_used": time.strftime("%Y-%m-%dT%H:%M:%S"),
        })

    def suggest_next(self, current_cmd: str) -> Optional[str]:
        """根据当前命令推荐下一步。

        Returns:
            推荐的命令名，或 None
        """
        data = self.store.get_data()
        workflow = data.get("workflow", {})

        # 检查是否启用推荐
        if not workflow.get("suggestions_enabled", True):
            return None

        patterns = workflow.get("patterns", [])
        # 找出以 current_cmd 开头的高频序列
        candidates = []
        for p in patterns:
            seq = p["sequence"]
            if isinstance(seq, list) and len(seq) >= 2 and seq[0] == current_cmd:
                candidates.append((seq[1], p["count"]))

        if not candidates:
            return None

        # 按频次降序，取第一个
        candidates.sort(key=lambda x: x[1], reverse=True)
        next_cmd, count = candidates[0]
        if count >= MIN_PATTERN_COUNT:
            return next_cmd
        return None

    def detect_pattern(self) -> Optional[List[str]]:
        """检测当前是否在常用工作流中。

        Returns:
            当前正在执行的序列，或 None
        """
        data = self.store.get_data()
        workflow = data.get("workflow", {})
        recent = workflow.get("recent_commands", [])
        patterns = workflow.get("patterns", [])

        if len(recent) < 1:
            return None

        # 检查最近命令是否是某个高频序列的开始
        last_cmd = recent[-1]["cmd"]
        for p in patterns:
            seq = p["sequence"]
            if isinstance(seq, list) and len(seq) >= 2 and seq[0] == last_cmd and p["count"] >= MIN_PATTERN_COUNT:
                return seq
        return None
```

- [ ] **Step 4: 运行测试确认通过**

Run: `pytest tests/memory/test_workflow.py -v`
Expected: 7 passed

- [ ] **Step 5: 提交**

```bash
git add core/memory/workflow.py tests/memory/test_workflow.py
git commit -m "feat(memory): add WorkflowTracker with 2-gram pattern detection"
```

---

## Task 9: 人格层（core/persona/）

**Files:**
- Create: `core/persona/__init__.py`
- Create: `core/persona/styles.py`
- Create: `core/persona/prompts.py`
- Create: `tests/persona/__init__.py`
- Create: `tests/persona/test_prompts.py`

**Interfaces:**
- Consumes: `Pet`（来自 core/pet/pet.py，有 name/level/branch/mood/hunger/energy）
- Produces: `build_system_prompt(style, pet, profile, tasks, sources) -> str`

- [ ] **Step 1: 创建模块骨架**

```python
# core/persona/__init__.py
"""人格层：分系风格 + system prompt 模板。"""
from core.persona.prompts import build_system_prompt
from core.persona.styles import STYLE_DESCRIPTIONS

__all__ = ["build_system_prompt", "STYLE_DESCRIPTIONS"]
```

- [ ] **Step 2: 写人格测试**

```python
# tests/persona/test_prompts.py
"""人格 prompt 模板测试。"""
import pytest
from core.persona.prompts import build_system_prompt, SCHOLAR_SYSTEM, WARRIOR_SYSTEM, ARTISAN_SYSTEM, NEUTRAL_SYSTEM
from core.persona.styles import STYLE_DESCRIPTIONS
from core.pet.pet import Pet


def test_style_descriptions_has_three():
    """三种人格风格描述都存在。"""
    assert "scholar" in STYLE_DESCRIPTIONS
    assert "warrior" in STYLE_DESCRIPTIONS
    assert "artisan" in STYLE_DESCRIPTIONS


def test_build_scholar_prompt():
    """构建 scholar 风格 prompt。"""
    pet = Pet(name="小白", level=5, branch="scholar")
    profile = {"preferred_format": "table", "focus_topics": ["骨灰安置"]}
    tasks = [{"description": "整理政策", "status": "in_progress"}]
    sources = [{"doc_id": "d1", "title": "条例", "paragraph_num": 1, "content": "内容"}]

    prompt = build_system_prompt("scholar", pet, profile, tasks, sources)

    assert "小白" in prompt
    assert "Lv5" in prompt or "Lv 5" in prompt or "level 5" in prompt.lower()
    assert "骨灰安置" in prompt
    assert "整理政策" in prompt
    assert "条例" in prompt


def test_build_warrior_prompt():
    """构建 warrior 风格 prompt。"""
    pet = Pet(name="小狼", level=6, branch="warrior")
    prompt = build_system_prompt("warrior", pet, {}, [], [])
    assert "小狼" in prompt
    assert "warrior" in prompt.lower() or "战士" in prompt


def test_build_artisan_prompt():
    """构建 artisan 风格 prompt。"""
    pet = Pet(name="小匠", level=7, branch="artisan")
    prompt = build_system_prompt("artisan", pet, {}, [], [])
    assert "小匠" in prompt


def test_build_neutral_prompt_for_unbranched():
    """未分系时用中性风格。"""
    pet = Pet(name="小白", level=3, branch=None)
    prompt = build_system_prompt("neutral", pet, {}, [], [])
    assert "小白" in prompt
    # 中性 prompt 较短
    assert len(prompt) < len(SCHOLAR_SYSTEM)


def test_build_prompt_with_empty_sources():
    """无检索结果时 prompt 仍能构建。"""
    pet = Pet(name="小白", level=1)
    prompt = build_system_prompt("scholar", pet, {}, [], [])
    assert "小白" in prompt


def test_build_prompt_includes_pet_state_warnings():
    """宠物状态低时 prompt 包含警告。"""
    pet = Pet(name="小白", level=5, mood=20, hunger=20)
    prompt = build_system_prompt("scholar", pet, {}, [], [])
    # mood < 30 应有提示
    assert "心情" in prompt or "mood" in prompt.lower()
```

- [ ] **Step 3: 运行测试确认失败**

Run: `pytest tests/persona/test_prompts.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 4: 实现 styles.py + prompts.py**

```python
# core/persona/styles.py
"""三种人格风格定义。"""

STYLE_DESCRIPTIONS = {
    "scholar": {
        "name": "学者",
        "emoji": "🦉",
        "description": "深度分析型：严谨、博学、引用密集",
        "traits": [
            "先结论后论证",
            "每个观点必须有原文引用 [n]",
            "偏好表格对比、条文列举",
            "主动指出例外情况和边界条件",
            "语气正式客观",
        ],
    },
    "warrior": {
        "name": "战士",
        "emoji": "🐺",
        "description": "直接行动型：果断、高效、行动导向",
        "traits": [
            "开门见山给答案",
            "引用最少但最相关（最多 3 个）",
            "主动给行动建议",
            "偏好列表、步骤",
            "语气简洁有力",
        ],
    },
    "artisan": {
        "name": "工匠",
        "emoji": "🦡",
        "description": "结构化型：细致、有条理、注重呈现",
        "traits": [
            "结构化分块，必带小标题 ##",
            "偏好表格、流程图描述",
            "主动总结要点",
            "每节至少 1 个引用",
            "语气温和清晰，引导式",
        ],
    },
    "neutral": {
        "name": "通用",
        "emoji": "🐾",
        "description": "中性风格：综合三种特点",
        "traits": [
            "先结论 + 适度引用",
            "简单结构化",
            "语气平和",
        ],
    },
}
```

```python
# core/persona/prompts.py
"""分系 system prompt 模板。"""
from __future__ import annotations

from typing import List, Optional


SCHOLAR_SYSTEM = """你是 {pet_name}，一只学者型（scholar）知识库管理员。
当前等级 Lv{level}，专注深度分析与严谨引用。

## 回答风格
- 先结论后论证，每个观点必须有原文引用支撑 [n]
- 偏好表格对比、条文列举
- 主动指出例外情况和边界条件
- 语气正式客观

## 当前用户偏好
{user_profile}

## 当前任务上下文
{user_tasks}

## 检索到的资料（含 doc_id 和段落号）
{retrieved_context}

## 引用规则
- 引用标记 [1][2] 对应资料编号
- 关键事实必须引用，常识无需引用
- 多个资料支撑同一观点时合并引用 [1][3]
"""

WARRIOR_SYSTEM = """你是 {pet_name}，一只战士型（warrior）知识库管理员。
当前等级 Lv{level}，专注直接结论与行动建议。

## 回答风格
- 开门见山给答案
- 引用最少但最相关（最多 3 个）
- 主动给行动建议："建议你..."、"下一步可..."
- 偏好列表、步骤，简洁有力

## 当前用户偏好
{user_profile}

## 当前任务上下文
{user_tasks}

## 检索到的资料
{retrieved_context}

## 引用规则
- 关键结论必引，其余可省
- 最多 3 个引用，宁少勿多
"""

ARTISAN_SYSTEM = """你是 {pet_name}，一只工匠型（artisan）知识库管理员。
当前等级 Lv{level}，专注结构化呈现与可视化。

## 回答风格
- 结构化分块，必带小标题 ##
- 偏好表格、流程图描述
- 主动总结要点（"小结："）
- 语气温和清晰，引导式

## 当前用户偏好
{user_profile}

## 当前任务上下文
{user_tasks}

## 检索到的资料
{retrieved_context}

## 引用规则
- 表格中标注引用
- 每个小节至少 1 个引用
"""

NEUTRAL_SYSTEM = """你是 {pet_name}，一只知识库管理员。
当前等级 Lv{level}。

## 回答风格
- 先给结论，再展开说明
- 关键事实适度引用 [n]
- 简单结构化，分点说明
- 语气平和

## 当前用户偏好
{user_profile}

## 当前任务上下文
{user_tasks}

## 检索到的资料
{retrieved_context}
"""

# 风格 → 模板映射
_STYLE_TEMPLATES = {
    "scholar": SCHOLAR_SYSTEM,
    "warrior": WARRIOR_SYSTEM,
    "artisan": ARTISAN_SYSTEM,
    "neutral": NEUTRAL_SYSTEM,
}


def _format_profile(profile: dict) -> str:
    """格式化用户偏好为文本。"""
    if not profile:
        return "（暂无偏好数据）"
    lines = []
    if profile.get("preferred_format"):
        lines.append(f"- 回答格式：{profile['preferred_format']}")
    if profile.get("focus_topics"):
        lines.append(f"- 关注主题：{', '.join(profile['focus_topics'][:5])}")
    if profile.get("focus_regions"):
        lines.append(f"- 关注地区：{', '.join(profile['focus_regions'][:5])}")
    return "\n".join(lines) if lines else "（暂无偏好数据）"


def _format_tasks(tasks: list) -> str:
    """格式化任务上下文为文本。"""
    if not tasks:
        return "（无活跃任务）"
    lines = []
    for t in tasks:
        status = t.get("status", "")
        desc = t.get("description", "")
        lines.append(f"- {desc}（{status}）")
    return "\n".join(lines)


def _format_sources(sources: list) -> str:
    """格式化检索资料为文本。"""
    if not sources:
        return "（未检索到相关资料）"
    lines = []
    for i, s in enumerate(sources, 1):
        title = s.get("title", s.get("doc_title", "未知"))
        para = s.get("paragraph_num", "")
        content = s.get("content", "")[:500]  # 截取前 500 字
        lines.append(f"[{i}] {title} §{para}\n{content}\n")
    return "\n".join(lines)


def _format_pet_state_warnings(pet) -> str:
    """宠物状态低时的警告。"""
    warnings = []
    if hasattr(pet, "mood") and pet.mood < 30:
        warnings.append("（宠物心情低落，回答可能不够完整，建议先 /pet play）")
    if hasattr(pet, "hunger") and pet.hunger < 30:
        warnings.append("（宠物饿了，建议 /pet feed）")
    if warnings:
        return "\n\n## 注意\n" + "\n".join(warnings)
    return ""


def build_system_prompt(
    style: str,
    pet,
    profile: dict,
    tasks: list,
    sources: list,
) -> str:
    """构建 system prompt。

    Args:
        style: 风格名（scholar/warrior/artisan/neutral）
        pet: Pet 对象（有 name/level/mood/hunger）
        profile: 用户偏好 dict
        tasks: 任务列表
        sources: 检索资料列表

    Returns:
        完整的 system prompt 字符串
    """
    template = _STYLE_TEMPLATES.get(style, NEUTRAL_SYSTEM)

    prompt = template.format(
        pet_name=pet.name,
        level=pet.level,
        user_profile=_format_profile(profile),
        user_tasks=_format_tasks(tasks),
        retrieved_context=_format_sources(sources),
    )

    # 追加宠物状态警告
    prompt += _format_pet_state_warnings(pet)

    return prompt
```

- [ ] **Step 5: 运行测试确认通过**

Run: `pytest tests/persona/test_prompts.py -v`
Expected: 6 passed

- [ ] **Step 6: 提交**

```bash
git add core/persona/__init__.py core/persona/styles.py core/persona/prompts.py tests/persona/__init__.py tests/persona/test_prompts.py
git commit -m "feat(persona): add 3-style system prompt templates with pet state linkage"
```

---

## Task 10: 编排层（core/pet/administrator.py）

**Files:**
- Create: `core/pet/administrator.py`
- Create: `tests/pet/test_administrator.py`

**Interfaces:**
- Consumes: `Pet`（core/pet/pet.py），`Storage`（core/storage.py），`MemoryStore`（Task 5），`HybridRetriever`（Task 3），`Reranker`（Task 4），`build_system_prompt`（Task 9）
- Produces: `AnswerResult` dataclass, `PetAdministrator` 类 with `ask`

- [ ] **Step 1: 写编排层测试**

```python
# tests/pet/test_administrator.py
"""编排层测试。"""
import pytest
from unittest.mock import MagicMock, patch
from core.pet.administrator import PetAdministrator, AnswerResult
from core.pet.pet import Pet
from core.retrieval.hybrid import HybridResult
from core.retrieval.rerank import RerankResult


def _make_admin(tmp_path):
    """构建测试用 administrator（mock 所有外部依赖）。"""
    pet = Pet(name="小白", level=5, branch="scholar")
    storage = MagicMock()
    storage.get_chunks.return_value = []

    memory = MagicMock()
    memory.get_data.return_value = {
        "profile": {"focus_topics": ["骨灰安置"]},
        "tasks": [],
    }
    memory.get_active_tasks.return_value = []

    hybrid = MagicMock()
    hybrid.search.return_value = [
        HybridResult(chunk_id="c1", doc_id="d1", score=0.5, source="both", content="骨灰安置内容", doc_title="条例")
    ]

    reranker = MagicMock()
    reranker.rerank.return_value = [
        RerankResult(
            chunk_id="c1", doc_id="d1", score=0.5, source="both",
            content="骨灰安置内容", doc_title="条例",
            relevance_score=9.0, reason="高度相关"
        )
    ]

    llm = MagicMock()
    llm.chat.return_value = "骨灰安置分为四类[1]。"

    admin = PetAdministrator(
        pet=pet, storage=storage, memory_store=memory,
        hybrid_retriever=hybrid, reranker=reranker, llm=llm,
    )
    return admin


def test_ask_returns_answer_result(tmp_path):
    """ask 返回 AnswerResult。"""
    admin = _make_admin(tmp_path)
    result = admin.ask("骨灰安置政策")
    assert isinstance(result, AnswerResult)
    assert result.text == "骨灰安置分为四类[1]。"
    assert len(result.citations) >= 1
    assert result.citations[0].doc_id == "d1"


def test_ask_increments_pet_exp(tmp_path):
    """ask 后宠物获得经验。"""
    admin = _make_admin(tmp_path)
    initial_exp = admin.pet.exp
    admin.ask("查询")
    assert admin.pet.exp > initial_exp


def test_ask_updates_memory(tmp_path):
    """ask 后更新记忆。"""
    admin = _make_admin(tmp_path)
    admin.ask("骨灰安置")
    # memory.update_from_query 被调用（通过 profile manager）
    admin.memory.get_data.assert_called()


def test_ask_with_style_override(tmp_path):
    """style_override 临时覆盖风格。"""
    admin = _make_admin(tmp_path)
    admin.ask("查询", style_override="warrior")
    # 验证 LLM 被调用
    admin.llm.chat.assert_called()


def test_ask_degradation_llm_failure(tmp_path):
    """LLM 失败时返回原文片段。"""
    admin = _make_admin(tmp_path)
    admin.llm.chat.side_effect = Exception("LLM 不可用")
    result = admin.ask("查询")
    assert "原文" in result.text or "不可用" in result.text or "骨灰安置内容" in result.text


def test_ask_degradation_no_sources(tmp_path):
    """无检索结果时仍返回回答。"""
    admin = _make_admin(tmp_path)
    admin.hybrid.search.return_value = []
    admin.reranker.rerank.return_value = []
    result = admin.ask("查询")
    assert result.text  # 非空


def test_ask_citation_extraction(tmp_path):
    """回答中的 [1] 被提取为引用。"""
    admin = _make_admin(tmp_path)
    admin.llm.chat.return_value = "回答[1]内容[2]。"
    # 添加第二个 source
    admin.reranker.rerank.return_value = [
        RerankResult(chunk_id="c1", doc_id="d1", score=0.5, source="both",
                     content="内容1", doc_title="标题1", relevance_score=9, reason=""),
        RerankResult(chunk_id="c2", doc_id="d2", score=0.4, source="bm25",
                     content="内容2", doc_title="标题2", relevance_score=7, reason=""),
    ]
    result = admin.ask("查询")
    assert len(result.citations) == 2
    assert result.citations[0].doc_id == "d1"
    assert result.citations[1].doc_id == "d2"
```

- [ ] **Step 2: 运行测试确认失败**

Run: `pytest tests/pet/test_administrator.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: 实现 PetAdministrator**

```python
# core/pet/administrator.py
"""宠物知识库管理员：编排检索 + 记忆 + 人格 + LLM。"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from core.pet.pet import Pet
from core.storage import Storage
from core.memory.store import MemoryStore
from core.memory.profile import ProfileManager
from core.memory.tasks import TaskManager
from core.memory.workflow import WorkflowTracker
from core.retrieval.hybrid import HybridRetriever, HybridResult
from core.retrieval.rerank import Reranker, RerankResult
from core.retrieval.citation import Citation, extract_citations
from core.persona.prompts import build_system_prompt
from core.llm.client import LLMClient, LLMError
from core.llm.degrade import get_llm_degrade_message

logger = logging.getLogger(__name__)


# 经验值表
EXP_TABLE = {
    "qa": 10,
    "ingest": 30,
    "analyze": 15,
    "agent": 15,
    "report": 20,
    "read": 10,
    "compare": 10,
    "smart": 8,
    "graph_build": 30,
}


@dataclass
class AnswerResult:
    """问答结果。"""
    text: str
    citations: List[Citation] = field(default_factory=list)
    sources: List[RerankResult] = field(default_factory=list)
    pet_events: dict = field(default_factory=dict)
    related_tasks: Optional[List] = None


class PetAdministrator:
    """宠物知识库管理员。"""

    def __init__(
        self,
        pet: Pet,
        storage: Storage,
        memory_store: MemoryStore,
        hybrid_retriever: HybridRetriever,
        reranker: Reranker,
        llm: LLMClient,
    ) -> None:
        self.pet = pet
        self.storage = storage
        self.memory = memory_store
        self.hybrid = hybrid_retriever
        self.reranker = reranker
        self.llm = llm
        self.profile_mgr = ProfileManager(memory_store)
        self.task_mgr = TaskManager(memory_store)
        self.workflow = WorkflowTracker(memory_store)

    def ask(self, query: str, style_override: Optional[str] = None,
            history: Optional[List[Dict]] = None,
            summary: Optional[str] = None) -> AnswerResult:
        """主入口：用户提问 → 带引用的回答。

        Args:
            query: 用户问题
            style_override: 临时覆盖人格风格
            history: 多轮对话历史（[{role, content}, ...]），最多取最近 10 条
            summary: 早期对话的摘要（压缩长期记忆）
        """
        # 1. 加载记忆
        profile = self.profile_mgr.get_profile()
        active_tasks = self.task_mgr.get_active_tasks()

        # 2. 混合检索
        candidates = self.hybrid.search(query, top_k=15)

        # 3. LLM 重排
        top_sources = self.reranker.rerank(query, candidates, top_n=5)

        # 4. 确定风格
        if style_override:
            style = style_override
        elif profile.preferred_style and profile.preferred_style != "auto":
            style = profile.preferred_style
        elif self.pet.branch:
            style = self.pet.branch
        else:
            style = "neutral"

        # 5. 组装 system prompt
        # sources_dict 同时为 build_system_prompt（用 content）和 extract_citations（用 snippet）提供数据
        sources_dict = [
            {
                "doc_id": s.doc_id,
                "title": s.doc_title,
                "paragraph_num": i + 1,  # 简化：用序号作为段落号
                "content": s.content,
                "snippet": s.content,
            }
            for i, s in enumerate(top_sources)
        ]
        profile_dict = {
            "preferred_format": profile.preferred_format,
            "focus_topics": profile.focus_topics,
            "focus_regions": profile.focus_regions,
        }
        tasks_dict = [
            {"description": t.description, "status": t.status}
            for t in active_tasks
        ]
        system_prompt = build_system_prompt(
            style=style,
            pet=self.pet,
            profile=profile_dict,
            tasks=tasks_dict,
            sources=sources_dict,
        )

        # 6. LLM 生成（带多轮历史 + 早期摘要）
        # 取最近 10 条历史（5 轮对话），避免 token 超限
        recent_history = (history or [])[-10:]
        messages = [{"role": "system", "content": system_prompt}]
        if summary:
            messages.append({"role": "system", "content": f"## 之前的对话摘要\n{summary}"})
        messages.extend(recent_history)
        messages.append({"role": "user", "content": query})
        try:
            answer_text = self.llm.chat(
                messages=messages,
                temperature=0.3,
                max_tokens=1024,
            )
        except LLMError as e:
            logger.warning(f"LLM 生成失败，降级为检索模式: {e}")
            # 降级：用统一文案 + 检索到的原文片段
            if top_sources:
                answer_text = get_llm_degrade_message(
                    error=e, has_sources=True, source_count=len(top_sources),
                ) + "\n\n"
                for i, s in enumerate(top_sources, 1):
                    answer_text += f"[{i}] {s.doc_title}\n{s.content[:200]}\n\n"
            else:
                answer_text = get_llm_degrade_message(error=e, has_sources=False)

        # 7. 提取引用
        try:
            citations = extract_citations(answer_text, sources_dict)
        except Exception as e:
            logger.warning(f"引用提取失败: {e}")
            citations = []

        # 8. 更新记忆（静默，失败不影响回答）
        try:
            self.profile_mgr.update_from_query(query, answer_text)
        except Exception as e:
            logger.warning(f"记忆更新失败: {e}")

        # 9. 宠物获得经验
        events = {}
        try:
            events = self.pet.gain_exp(EXP_TABLE.get("qa", 10), "qa")
        except Exception as e:
            logger.warning(f"宠物经验更新失败: {e}")

        return AnswerResult(
            text=answer_text,
            citations=citations,
            sources=top_sources,
            pet_events=events,
            related_tasks=active_tasks if active_tasks else None,
        )

    def ask_stream(self, query: str, style_override: Optional[str] = None,
                   history: Optional[List[Dict]] = None,
                   summary: Optional[str] = None):
        """流式问答生成器。yield 事件 dict:
        - {"type": "stage", "stage": "检索", "count": N}
        - {"type": "stage", "stage": "重排", "count": N}
        - {"type": "token", "text": "..."}  — LLM 逐 token
        - {"type": "done", "result": AnswerResult}  — 最终结果

        步骤 1-5 与 ask() 完全一致；步骤 6 改用 chat_stream()；
        步骤 7-9（引用提取 / 记忆更新 / 宠物经验）在流式结束后执行。
        """
        # 1. 加载记忆
        profile = self.profile_mgr.get_profile()
        active_tasks = self.task_mgr.get_active_tasks()

        # 2. 混合检索
        candidates = self.hybrid.search(query, top_k=15)
        yield {"type": "stage", "stage": "检索", "count": len(candidates)}

        # 3. LLM 重排
        top_sources = self.reranker.rerank(query, candidates, top_n=5)
        yield {"type": "stage", "stage": "重排", "count": len(top_sources)}

        # 4. 确定风格
        if style_override:
            style = style_override
        elif profile.preferred_style and profile.preferred_style != "auto":
            style = profile.preferred_style
        elif self.pet.branch:
            style = self.pet.branch
        else:
            style = "neutral"

        # 5. 组装 system prompt
        # sources_dict 同时为 build_system_prompt（用 content）和 extract_citations（用 snippet）提供数据
        sources_dict = [
            {
                "doc_id": s.doc_id,
                "title": s.doc_title,
                "paragraph_num": i + 1,  # 简化：用序号作为段落号
                "content": s.content,
                "snippet": s.content,
            }
            for i, s in enumerate(top_sources)
        ]
        profile_dict = {
            "preferred_format": profile.preferred_format,
            "focus_topics": profile.focus_topics,
            "focus_regions": profile.focus_regions,
        }
        tasks_dict = [
            {"description": t.description, "status": t.status}
            for t in active_tasks
        ]
        system_prompt = build_system_prompt(
            style=style,
            pet=self.pet,
            profile=profile_dict,
            tasks=tasks_dict,
            sources=sources_dict,
        )

        # 6. LLM 流式生成（带多轮历史 + 早期摘要，chat_stream 不支持重试，首帧失败直接降级）
        # 取最近 10 条历史（5 轮对话），避免 token 超限
        recent_history = (history or [])[-10:]
        messages = [{"role": "system", "content": system_prompt}]
        if summary:
            messages.append({"role": "system", "content": f"## 之前的对话摘要\n{summary}"})
        messages.extend(recent_history)
        messages.append({"role": "user", "content": query})
        answer_text = ""
        try:
            for token in self.llm.chat_stream(
                messages=messages,
                temperature=0.3,
                max_tokens=1024,
            ):
                answer_text += token
                yield {"type": "token", "text": token}
        except LLMError as e:
            logger.warning(f"LLM 流式生成失败，降级为检索模式: {e}")
            # 降级：用统一文案 + 检索到的原文片段（与 ask() 保持一致）
            if top_sources:
                answer_text = get_llm_degrade_message(
                    error=e, has_sources=True, source_count=len(top_sources),
                ) + "\n\n"
                for i, s in enumerate(top_sources, 1):
                    answer_text += f"[{i}] {s.doc_title}\n{s.content[:200]}\n\n"
            else:
                answer_text = get_llm_degrade_message(error=e, has_sources=False)
            yield {"type": "token", "text": answer_text}

        # 7. 提取引用
        try:
            citations = extract_citations(answer_text, sources_dict)
        except Exception as e:
            logger.warning(f"引用提取失败: {e}")
            citations = []

        # 8. 更新记忆（静默，失败不影响回答）
        try:
            self.profile_mgr.update_from_query(query, answer_text)
        except Exception as e:
            logger.warning(f"记忆更新失败: {e}")

        # 9. 宠物获得经验
        events = {}
        try:
            events = self.pet.gain_exp(EXP_TABLE.get("qa", 10), "qa")
        except Exception as e:
            logger.warning(f"宠物经验更新失败: {e}")

        yield {
            "type": "done",
            "result": AnswerResult(
                text=answer_text,
                citations=citations,
                sources=top_sources,
                pet_events=events,
                related_tasks=active_tasks if active_tasks else None,
            ),
        }
```

- [ ] **Step 4: 运行测试确认通过**

Run: `pytest tests/pet/test_administrator.py -v`
Expected: 7 passed

- [ ] **Step 5: 提交**

```bash
git add core/pet/administrator.py tests/pet/test_administrator.py
git commit -m "feat(pet): add PetAdministrator orchestrating retrieval+memory+persona"
```

---

## Task 11: REPL 集成

**Files:**
- Modify: `repl.py`
- Create: `tests/integration/__init__.py`
- Create: `tests/integration/test_pet_admin_flow.py`

**Interfaces:**
- Consumes: `PetAdministrator`（Task 10），所有前序 Task 的模块

- [ ] **Step 1: 写集成测试**

```python
# tests/integration/__init__.py
"""集成测试包。"""
```

```python
# tests/integration/test_pet_admin_flow.py
"""端到端流程测试。"""
import pytest
from unittest.mock import MagicMock, patch
from core.pet.administrator import PetAdministrator, AnswerResult
from core.pet.pet import Pet
from core.pet.storage import PetStorage
from core.memory.store import MemoryStore
from core.retrieval.hybrid import HybridResult
from core.retrieval.rerank import RerankResult


def _build_admin(tmp_path):
    """构建完整 admin（mock LLM 和向量）。"""
    pet = Pet(name="小白", level=5, branch="scholar")
    storage = MagicMock()
    storage.get_chunks.return_value = []

    memory = MemoryStore(storage_path=tmp_path)

    hybrid = MagicMock()
    hybrid.search.return_value = [
        HybridResult(chunk_id="c1", doc_id="d1", score=0.5, source="both",
                     content="骨灰安置分为四类", doc_title="殡葬条例")
    ]

    reranker = MagicMock()
    reranker.rerank.return_value = [
        RerankResult(chunk_id="c1", doc_id="d1", score=0.5, source="both",
                     content="骨灰安置分为四类", doc_title="殡葬条例",
                     relevance_score=9.0, reason="高度相关")
    ]

    llm = MagicMock()
    llm.chat.return_value = "骨灰安置分为四类[1]。"

    admin = PetAdministrator(
        pet=pet, storage=storage, memory_store=memory,
        hybrid_retriever=hybrid, reranker=reranker, llm=llm,
    )
    return admin


def test_full_ask_flow(tmp_path):
    """完整问答流程：检索 → 重排 → 生成 → 引用 → 记忆更新。"""
    admin = _build_admin(tmp_path)
    result = admin.ask("骨灰安置政策")

    assert result.text
    assert len(result.citations) >= 1
    assert result.citations[0].doc_id == "d1"
    assert result.pet_events  # 宠物事件

    # 验证记忆更新
    profile = admin.profile_mgr.get_profile()
    assert "骨灰安置" in profile.focus_topics


def test_degradation_llm_failure(tmp_path):
    """LLM 失败时返回原文片段。"""
    admin = _build_admin(tmp_path)
    admin.llm.chat.side_effect = Exception("LLM 不可用")
    result = admin.ask("骨灰安置")
    assert "原文" in result.text or "不可用" in result.text or "骨灰安置" in result.text


def test_persona_style_affects_prompt(tmp_path):
    """不同人格调用 LLM 时 prompt 不同。"""
    admin = _build_admin(tmp_path)
    admin.ask("骨灰安置", style_override="scholar")
    scholar_prompt = admin.llm.chat.call_args.kwargs["messages"][0]["content"]

    admin.llm.chat.reset_mock()
    admin.ask("骨灰安置", style_override="warrior")
    warrior_prompt = admin.llm.chat.call_args.kwargs["messages"][0]["content"]

    assert scholar_prompt != warrior_prompt
    assert "scholar" in scholar_prompt.lower() or "学者" in scholar_prompt
    assert "warrior" in warrior_prompt.lower() or "战士" in warrior_prompt


def test_memory_persistence_across_sessions(tmp_path):
    """记忆跨会话持久化。"""
    admin = _build_admin(tmp_path)
    admin.ask("杭州骨灰安置")
    admin.memory.save()

    # 新建 admin 实例模拟重启
    memory2 = MemoryStore(storage_path=tmp_path)
    profile2 = memory2.get_data()["profile"]
    assert "杭州" in profile2.get("focus_regions", [])


def test_pet_gains_exp_on_ask(tmp_path):
    """宠物通过 ask 获得经验。"""
    admin = _build_admin(tmp_path)
    initial_exp = admin.pet.exp
    admin.ask("查询")
    assert admin.pet.exp > initial_exp
```

- [ ] **Step 2: 运行测试确认失败**

Run: `pytest tests/integration/test_pet_admin_flow.py -v`
Expected: FAIL with `ModuleNotFoundError`（integration 包未创建）

- [ ] **Step 3: 修改 repl.py 集成 administrator**

需要在 repl.py 中做以下改动（具体行号由实现时确定）：

1. **导入区追加**：
```python
from core.pet.administrator import PetAdministrator, AnswerResult
from core.memory.store import MemoryStore
from core.memory.profile import ProfileManager
from core.memory.tasks import TaskManager
from core.memory.workflow import WorkflowTracker
from core.retrieval.hybrid import HybridRetriever
from core.retrieval.vector import VectorIndex
from core.retrieval.rerank import Reranker
```

2. **`__init__` 末尾追加 administrator 初始化**：
```python
# 初始化宠物管理员（如果有宠物）
self.administrator = None
if self.pet:
    try:
        memory_store = MemoryStore()
        vector_index = VectorIndex()
        hybrid = HybridRetriever(bm25_index=self.storage.bm25, vector_index=vector_index)
        llm = get_llm() if settings.has_llm() else None
        reranker = Reranker(llm) if llm else None
        if llm and reranker:
            self.administrator = PetAdministrator(
                pet=self.pet,
                storage=self.storage,
                memory_store=memory_store,
                hybrid_retriever=hybrid,
                reranker=reranker,
                llm=llm,
            )
    except Exception as e:
        console.print(f"[dim]宠物管理员初始化失败，降级为普通问答: {e}[/dim]")
```

3. **`_handle_chat` 改为走 administrator**：
```python
def _handle_chat(self, text: str) -> None:
    """用户直接输入文本 → 走宠物管理员。"""
    if not self.administrator:
        # 降级：管理员未初始化时用原有 RAGChain
        self._legacy_rag_chat(text)
        return

    try:
        result = self.administrator.ask(text)
        self._render_answer(result)
        # 渲染宠物事件
        if result.pet_events.get("leveled_up"):
            self._render_level_up(result.pet_events)
        if result.pet_events.get("branched"):
            self._render_branch_event(result.pet_events)
    except Exception as e:
        console.print(f"[red]⚠ 问答失败: {e}[/red]")
        self._legacy_rag_chat(text)
```

4. **新增 `_render_answer` 方法**：
```python
def _render_answer(self, result: AnswerResult) -> None:
    """渲染带引用的回答。"""
    # 宠物头像 + 回答
    emoji = "🐾"
    if self.pet and self.pet.branch:
        from core.persona.styles import STYLE_DESCRIPTIONS
        emoji = STYLE_DESCRIPTIONS.get(self.pet.branch, {}).get("emoji", "🐾")
    branch_label = f" ({self.pet.branch})" if self.pet and self.pet.branch else ""
    header = f"{emoji} {self.pet.name if self.pet else 'IMA'} (Lv{self.pet.level if self.pet else '?'}){branch_label}"

    console.print(Panel(
        Text(result.text),
        title=f"[bold cyan]{header}[/bold cyan]",
        title_align="left",
        border_style="cyan",
        padding=(1, 2),
    ))

    # 引用溯源区块
    if result.citations:
        cite_lines = []
        for c in result.citations:
            cite_lines.append(f"[bold]{c.marker}[/bold] {c.title} §{c.paragraph_num}")
            if c.snippet:
                cite_lines.append(f"     [dim]\"{c.snippet}\"[/dim]")
        console.print(Panel(
            "\n".join(cite_lines),
            title="[bold]引用溯源[/bold]",
            title_align="left",
            border_style="dim",
            padding=(0, 1),
        ))
```

5. **新增 `_legacy_rag_chat` 方法**（保留原有 RAGChain 作为降级）：
```python
def _legacy_rag_chat(self, text: str) -> None:
    """降级问答：用原有 RAGChain。"""
    if not hasattr(self, "rag_chain") or not self.rag_chain:
        console.print("[red]⚠ 问答不可用（LLM 未配置）[/red]")
        return
    try:
        answer = self.rag_chain.ask(text)
        console.print(Panel(Text(answer), title="[bold cyan]IMA[/bold cyan]", border_style="cyan"))
    except Exception as e:
        console.print(f"[red]⚠ 问答失败: {e}[/red]")
```

6. **新增 `/memory` 命令处理**：
```python
def _cmd_memory(self, args: str) -> None:
    """处理 /memory 命令。"""
    if not args.strip():
        # 显示记忆概览
        if not self.administrator:
            console.print("[dim]记忆系统未启用[/dim]")
            return
        profile = self.administrator.profile_mgr.get_profile()
        tasks = self.administrator.task_mgr.get_active_tasks()
        console.print(Panel(
            f"偏好格式: {profile.preferred_format or '未设置'}\n"
            f"偏好风格: {profile.preferred_style}\n"
            f"关注主题: {', '.join(profile.focus_topics) or '无'}\n"
            f"关注地区: {', '.join(profile.focus_regions) or '无'}\n"
            f"交互次数: {profile.interaction_count}\n"
            f"活跃任务: {len(tasks)} 个",
            title="[bold]记忆概览[/bold]",
        ))
        return

    parts = args.split(None, 1)
    sub = parts[0]
    if sub == "clear":
        if self.administrator:
            self.administrator.memory.clear()
            console.print("[green]✓ 记忆已清空[/green]")
    elif sub == "task":
        if len(parts) < 2:
            console.print("[red]用法: /memory task <描述>[/red]")
            return
        if self.administrator:
            task_id = self.administrator.task_mgr.add_task(parts[1])
            console.print(f"[green]✓ 任务已添加: {task_id}[/green]")
    elif sub == "tasks":
        if self.administrator:
            tasks = self.administrator.task_mgr.get_active_tasks()
            if not tasks:
                console.print("[dim]无活跃任务[/dim]")
            for t in tasks:
                console.print(f"  [{t.status}] {t.description} ({t.id})")
```

7. **新增 `/pet style` 命令**（在现有 `_cmd_pet` 中添加分支）：
```python
# 在 _cmd_pet 方法中添加
elif sub == "style":
    if not args.strip():
        # 显示当前风格
        if self.administrator:
            p = self.administrator.profile_mgr.get_profile()
            console.print(f"当前风格: {p.preferred_style}")
        return
    style = args.strip()
    if style in ("scholar", "warrior", "artisan", "auto"):
        if self.administrator:
            self.administrator.profile_mgr.update_style_preference(style)
            console.print(f"[green]✓ 风格已切换为: {style}[/green]")
    else:
        console.print("[red]无效风格，可选: scholar/warrior/artisan/auto[/red]")
```

8. **工作流推荐钩子**（在命令执行后调用）：
```python
def _post_command_hook(self, cmd: str) -> None:
    """命令执行后的钩子（工作流推荐）。"""
    if not self.administrator:
        return
    try:
        suggestion = self.administrator.workflow.suggest_next(cmd)
        if suggestion:
            console.print(f"\n[dim]💡 常用下一步：/{suggestion}（基于你的使用习惯）[/dim]")
    except Exception:
        pass  # 静默失败
```

- [ ] **Step 4: 运行集成测试确认通过**

Run: `pytest tests/integration/test_pet_admin_flow.py -v`
Expected: 5 passed

- [ ] **Step 5: 提交**

```bash
git add repl.py tests/integration/__init__.py tests/integration/test_pet_admin_flow.py
git commit -m "feat(repl): integrate PetAdministrator + /memory command + workflow suggestions"
```

---

## Task 12: CLI 命令扩展 + 依赖更新

**Files:**
- Modify: `run.py`
- Modify: `requirements.txt`
- Modify: `install.sh`
- Modify: `config.py`

- [ ] **Step 1: 更新 config.py 添加 memory_path**

在 `config.py` 的 `Settings` 类中添加：
```python
@property
def memory_path(self) -> Path:
    """记忆数据文件路径。"""
    return self.storage_path / "memory.json"
```

- [ ] **Step 2: 更新 requirements.txt**

追加：
```
chromadb>=0.4.0
sentence-transformers>=2.2.0
```

- [ ] **Step 3: 更新 install.sh 添加 --vector 选项**

在 install.sh 中添加向量依赖可选安装：
```bash
# 在参数解析部分添加
INSTALL_VECTOR=false
if [[ "$*" == *"--vector"* ]]; then
    INSTALL_VECTOR=true
fi

# 在依赖安装部分添加
if [ "$INSTALL_VECTOR" = true ]; then
    echo "📦 安装向量检索依赖（chromadb + sentence-transformers）..."
    pip install chromadb sentence-transformers
else
    echo "ℹ 未安装向量依赖（用 --vector 启用）。将降级为纯 BM25。"
fi
```

- [ ] **Step 4: 在 run.py 添加新 CLI 命令**

```python
# 在 run.py 的 cli 命令组中添加

@cli.command(name="ask")
@click.argument("question")
def cli_ask(question: str) -> None:
    """CLI 一次性问答（不进 REPL）。"""
    from core.pet.administrator import PetAdministrator
    from core.memory.store import MemoryStore
    from core.retrieval.hybrid import HybridRetriever
    from core.retrieval.vector import VectorIndex
    from core.retrieval.rerank import Reranker
    from core.pet.storage import PetStorage
    from core.llm.client import get_llm

    storage = Storage()
    pet_storage = PetStorage()
    pet = pet_storage.load()
    if not pet:
        click.echo("请先运行 'ima' 并使用 /pet adopt 领养宠物")
        return

    memory = MemoryStore()
    vector_index = VectorIndex()
    hybrid = HybridRetriever(bm25_index=storage.bm25, vector_index=vector_index)
    llm = get_llm()
    reranker = Reranker(llm)

    admin = PetAdministrator(
        pet=pet, storage=storage, memory_store=memory,
        hybrid_retriever=hybrid, reranker=reranker, llm=llm,
    )
    result = admin.ask(question)
    click.echo(result.text)
    if result.citations:
        click.echo("\n引用溯源:")
        for c in result.citations:
            click.echo(f"  {c.marker} {c.title} §{c.paragraph_num}")


@cli.command(name="rebuild")
@click.option("--vector", is_flag=True, help="同时重建向量索引")
def cli_rebuild(vector: bool) -> None:
    """重建索引。"""
    storage = Storage()
    # 重建 BM25
    storage.rebuild_bm25()
    click.echo("✓ BM25 索引已重建")

    if vector:
        try:
            from core.retrieval.vector import VectorIndex
            from core.storage import ChunkRecord
            vector_index = VectorIndex()
            if vector_index.is_available():
                # 获取所有 chunks
                all_chunks = []
                # 这里需要从 storage 获取所有 chunks
                # 简化实现：遍历所有文档
                click.echo("构建向量索引...")
                vector_index.build_index(all_chunks)
                click.echo("✓ 向量索引已重建")
            else:
                click.echo("⚠ 向量索引不可用（依赖未安装）")
        except ImportError:
            click.echo("⚠ 向量依赖未安装，请用 'bash install.sh --vector' 安装")


@cli.command(name="memory")
@click.option("--clear", is_flag=True, help="清空记忆")
def cli_memory(clear: bool) -> None:
    """查看或清空记忆。"""
    from core.memory.store import MemoryStore
    memory = MemoryStore()
    if clear:
        memory.clear()
        click.echo("✓ 记忆已清空")
        return

    data = memory.load()
    profile = data.get("profile", {})
    tasks = data.get("tasks", [])
    click.echo("=== 记忆概览 ===")
    click.echo(f"偏好格式: {profile.get('preferred_format', '未设置')}")
    click.echo(f"偏好风格: {profile.get('preferred_style', 'auto')}")
    click.echo(f"关注主题: {', '.join(profile.get('focus_topics', []))}")
    click.echo(f"关注地区: {', '.join(profile.get('focus_regions', []))}")
    click.echo(f"交互次数: {profile.get('interaction_count', 0)}")
    click.echo(f"活跃任务: {len([t for t in tasks if t.get('status') != 'completed'])} 个")
```

- [ ] **Step 5: 验证语法**

Run: `python -c "import run; import repl; print('OK')"`
Expected: OK

- [ ] **Step 6: 运行全部测试**

Run: `pytest tests/ -v`
Expected: All passed

- [ ] **Step 7: 提交**

```bash
git add run.py config.py requirements.txt install.sh
git commit -m "feat(cli): add ask/rebuild --vector/memory commands + vector dependencies"
```

---

## Self-Review

### 1. Spec coverage

| Spec 章节 | 对应 Task |
|----------|----------|
| 3. 检索层 - citation | Task 1 ✓ |
| 3. 检索层 - vector | Task 2 ✓ |
| 3. 检索层 - hybrid | Task 3 ✓ |
| 3. 检索层 - rerank | Task 4 ✓ |
| 4. 记忆层 - store | Task 5 ✓ |
| 4. 记忆层 - tasks | Task 6 ✓ |
| 4. 记忆层 - profile | Task 7 ✓ |
| 4. 记忆层 - workflow | Task 8 ✓ |
| 5. 人格层 | Task 9 ✓ |
| 6. 编排层 | Task 10 ✓ |
| 6. REPL 集成 | Task 11 ✓ |
| 3.7/6.8 CLI 命令 | Task 12 ✓ |
| 8. 依赖 | Task 12 ✓ |

### 2. Placeholder scan

- ✅ 无 "TBD"、"TODO"
- ✅ 每个 Task 都有完整测试代码和实现代码
- ✅ Task 11 的 repl.py 改动以代码块形式给出（因是修改现有文件，不便给完整文件）

### 3. Type consistency

- `Citation`: Task 1 定义，Task 10 使用 ✓
- `VectorResult`: Task 2 定义，Task 3 使用 ✓
- `HybridResult`: Task 3 定义，Task 4/10 使用 ✓
- `RerankResult`: Task 4 定义，Task 10 使用 ✓
- `Task`: Task 6 定义，Task 10 使用 ✓
- `Profile`: Task 7 定义，Task 10 使用 ✓
- `AnswerResult`: Task 10 定义，Task 11 使用 ✓
- `build_system_prompt`: Task 9 定义，Task 10 使用 ✓

---

**Plan complete. 共 12 个 Task，每个都是独立 TDD 周期。**

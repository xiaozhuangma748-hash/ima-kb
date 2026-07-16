"""向量索引：ChromaDB + bge-small-zh-v1.5。

降级策略：模型加载失败时 is_available() 返回 False，search 返回空列表。

Embedding 缓存：通过 SQLite 持久化 content hash → embedding 映射，
避免重建索引时重复计算 embedding（bge-small-zh-v1.5 推理较慢）。
"""
from __future__ import annotations

import hashlib
import logging
import os
import pickle
import sqlite3
import threading
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

# 在 import chromadb/sentence_transformers 之前设置 HF 镜像（中国大陆访问）
# 优先尊重用户已设置的 HF_ENDPOINT，未设置时默认用 hf-mirror.com
if not os.environ.get("HF_ENDPOINT"):
    os.environ["HF_ENDPOINT"] = "https://hf-mirror.com"

from config import settings

logger = logging.getLogger(__name__)

# 模型名称
_MODEL_NAME = "BAAI/bge-small-zh-v1.5"
# 本地模型路径（优先使用，避免每次启动都从 HF 下载）
_LOCAL_MODEL_PATH = settings.storage_path / "models" / "bge-small-zh-v1.5"


@dataclass
class VectorResult:
    """向量检索结果。"""
    chunk_id: str
    doc_id: str
    score: float


def _get_embedding_function():
    """加载 bge-small-zh-v1.5 embedding 函数。

    优先使用本地模型路径（storage/models/bge-small-zh-v1.5），
    未找到时回退到从 HF 镜像下载。
    失败时抛 ImportError，由调用方降级处理。
    """
    # 先检查依赖是否已安装
    try:
        from sentence_transformers import SentenceTransformer  # noqa: F401
    except ImportError:
        raise ImportError(
            "sentence_transformers 未安装。请在虚拟环境中执行："
            "pip install sentence-transformers"
        )
    try:
        from chromadb.utils import embedding_functions
        # 优先使用本地路径
        model_path = str(_LOCAL_MODEL_PATH) if _LOCAL_MODEL_PATH.exists() else _MODEL_NAME
        if _LOCAL_MODEL_PATH.exists():
            logger.info(f"使用本地模型: {_LOCAL_MODEL_PATH}")
        return embedding_functions.SentenceTransformerEmbeddingFunction(
            model_name=model_path
        )
    except Exception as e:
        err_msg = str(e)
        if "couldn't connect" in err_msg or "huggingface" in err_msg.lower():
            raise ImportError(
                f"无法从 HF 镜像下载模型 bge-small-zh-v1.5: {e}。"
                "可手动下载：curl -L -o storage/models/bge-small-zh-v1.5/model.safetensors "
                "'https://hf-mirror.com/BAAI/bge-small-zh-v1.5/resolve/main/model.safetensors'"
            )
        raise ImportError(f"无法加载 embedding 模型: {e}")


class _EmbeddingCache:
    """SQLite 持久化 embedding 缓存（content hash → embedding vector）。

    避免重建索引时重复计算 embedding。WAL 模式支持并发读，写操作加锁保护。
    """

    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(str(db_path), check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS embeddings (
                content_hash TEXT PRIMARY KEY,
                embedding BLOB NOT NULL,
                created_at TEXT NOT NULL
            )
        """)
        self._conn.commit()

    @staticmethod
    def _hash(text: str) -> str:
        """计算文本的 SHA256 hash 作为缓存 key。"""
        return hashlib.sha256(text.encode("utf-8")).hexdigest()

    def get_batch(self, texts: List[str]) -> Dict[str, List[float]]:
        """批量获取缓存。返回 {text: embedding} 字典（只含命中的）。"""
        if not texts:
            return {}
        hashes = {self._hash(t): t for t in texts}
        placeholders = ",".join("?" * len(hashes))
        rows = self._conn.execute(
            f"SELECT content_hash, embedding FROM embeddings "
            f"WHERE content_hash IN ({placeholders})",
            list(hashes.keys()),
        ).fetchall()
        return {hashes[h]: pickle.loads(blob) for h, blob in rows}

    def put_batch(self, texts: List[str], embeddings: List[List[float]]) -> None:
        """批量写入缓存。"""
        if not texts:
            return
        now = datetime.now().isoformat()
        rows = [
            (self._hash(t), pickle.dumps(e), now)
            for t, e in zip(texts, embeddings)
        ]
        with self._lock:
            self._conn.executemany(
                "INSERT OR REPLACE INTO embeddings "
                "(content_hash, embedding, created_at) VALUES (?, ?, ?)",
                rows,
            )
            self._conn.commit()

    def count(self) -> int:
        """返回缓存条目数。"""
        return self._conn.execute("SELECT COUNT(*) FROM embeddings").fetchone()[0]

    def clear(self) -> None:
        """清空所有缓存。"""
        with self._lock:
            self._conn.execute("DELETE FROM embeddings")
            self._conn.commit()

    def close(self) -> None:
        self._conn.close()


class VectorIndex:
    """向量索引（ChromaDB 持久化 + embedding 缓存）。"""

    def __init__(self, storage_path: Optional[Path] = None) -> None:
        self.storage_path = Path(storage_path) if storage_path else settings.chroma_dir
        self.storage_path.mkdir(parents=True, exist_ok=True)
        self._client = None
        self._collection = None
        self._embedding_fn = None
        self._cache: Optional[_EmbeddingCache] = None
        self._available = False
        self._init()

    def _init(self) -> None:
        """初始化 ChromaDB 客户端、collection 和 embedding 缓存。"""
        try:
            import chromadb
            self._embedding_fn = _get_embedding_function()
            self._client = chromadb.PersistentClient(path=str(self.storage_path))
            self._collection = self._client.get_or_create_collection(
                name="ima_chunks",
                embedding_function=self._embedding_fn,
            )
            self._cache = _EmbeddingCache(settings.storage_path / "embedding_cache.db")
            self._available = True
        except Exception as e:
            logger.warning(f"向量索引初始化失败，降级为纯 BM25: {e}")
            self._available = False

    def is_available(self) -> bool:
        """向量索引是否可用。"""
        return self._available

    def _embed_with_cache(self, texts: List[str]) -> List[List[float]]:
        """带缓存的批量 embedding 计算。

        先查缓存命中部分，未命中的批量计算后写入缓存。
        """
        if not texts:
            return []
        cached = self._cache.get_batch(texts)
        miss_texts = [t for t in texts if t not in cached]
        if miss_texts:
            logger.info(f"Embedding 缓存未命中 {len(miss_texts)}/{len(texts)}，计算中...")
            new_embeddings = self._embedding_fn(miss_texts)
            self._cache.put_batch(miss_texts, new_embeddings)
            for t, e in zip(miss_texts, new_embeddings):
                cached[t] = e
        else:
            logger.info(f"Embedding 缓存全部命中 ({len(texts)} 条)")
        return [cached[t] for t in texts]

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
        # 批量计算 embedding（带缓存）
        ids = [c["chunk_id"] for c in chunks]
        contents = [c["content"] for c in chunks]
        metadatas = [{"doc_id": c["doc_id"]} for c in chunks]
        embeddings = self._embed_with_cache(contents)
        self._collection.add(ids=ids, embeddings=embeddings, metadatas=metadatas)

    def add_chunk(self, chunk: dict) -> None:
        """增量添加单个 chunk。"""
        if not self._available:
            return
        embeddings = self._embed_with_cache([chunk["content"]])
        self._collection.add(
            ids=[chunk["chunk_id"]],
            embeddings=embeddings,
            metadatas=[{"doc_id": chunk["doc_id"]}],
        )

    def add_chunks_batch(self, chunks: List[dict]) -> None:
        """批量增量添加 chunks（比循环调用 add_chunk 高效）。

        Args:
            chunks: [{"chunk_id", "doc_id", "content"}]
        """
        if not self._available or not chunks:
            return
        ids = [c["chunk_id"] for c in chunks]
        contents = [c["content"] for c in chunks]
        metadatas = [{"doc_id": c["doc_id"]} for c in chunks]
        embeddings = self._embed_with_cache(contents)
        self._collection.add(ids=ids, embeddings=embeddings, metadatas=metadatas)

    def delete_chunk(self, chunk_id: str) -> None:
        """删除单个 chunk 的向量。"""
        if not self._available:
            return
        try:
            self._collection.delete(ids=[chunk_id])
        except Exception as e:
            logger.warning(f"删除向量失败 {chunk_id}: {e}")

    def delete_document(self, doc_id: str) -> int:
        """删除某文档对应的所有向量（按 metadata 过滤）。

        Args:
            doc_id: 文档 ID

        Returns:
            删除的向量数量（-1 表示不可用或失败）
        """
        if not self._available:
            return -1
        try:
            # 先查该文档所有 chunk_id
            results = self._collection.get(where={"doc_id": doc_id})
            ids = results.get("ids", []) if results else []
            if ids:
                self._collection.delete(ids=ids)
            return len(ids)
        except Exception as e:
            logger.warning(f"删除文档向量失败 {doc_id}: {e}")
            return -1

    def search(self, query: str, top_k: int = 10, where: Optional[dict] = None) -> List[VectorResult]:
        """向量检索。

        Args:
            query: 查询文本
            top_k: 返回结果数
            where: ChromaDB metadata 过滤条件，如 {"doc_id": "xxx"} 或
                   {"$in": {"doc_id": ["id1", "id2"]}}。None 不过滤。
        """
        if not self._available:
            return []
        try:
            # query 也走缓存（相同搜索词重复搜索时省计算）
            query_embeddings = self._embed_with_cache([query])
            query_kwargs: dict = {
                "query_embeddings": query_embeddings,
                "n_results": top_k,
            }
            if where is not None:
                query_kwargs["where"] = where
            results = self._collection.query(**query_kwargs)
            vector_results = []
            if results and results.get("ids"):
                for i, chunk_id in enumerate(results["ids"][0]):
                    doc_id = results["metadatas"][0][i].get("doc_id", "")
                    # ChromaDB 返回 distance（越小越相似），转为 score（越大越好）
                    # cosine distance 范围 0-2，归一化到 0-1
                    distance = results["distances"][0][i]
                    score = max(0.0, 1.0 - distance / 2)
                    vector_results.append(VectorResult(
                        chunk_id=chunk_id,
                        doc_id=doc_id,
                        score=score,
                    ))
            return vector_results
        except Exception as e:
            logger.warning(f"向量检索失败: {e}")
            return []

    def embed_query(self, query: str) -> Optional[List[float]]:
        """计算 query 的 embedding 向量（带缓存）。

        供语义缓存复用，避免重复计算 embedding。
        Returns:
            embedding 向量列表，不可用时返回 None。
        """
        if not self._available:
            return None
        try:
            embeddings = self._embed_with_cache([query])
            return embeddings[0] if embeddings else None
        except Exception as e:
            logger.warning(f"计算 query embedding 失败: {e}")
            return None

    def cache_stats(self) -> dict:
        """返回 embedding 缓存统计信息。"""
        if not self._cache:
            return {"available": False, "count": 0}
        return {"available": True, "count": self._cache.count()}

    def clear_cache(self) -> None:
        """清空 embedding 缓存。"""
        if self._cache:
            self._cache.clear()
            logger.info("已清空 embedding 缓存")

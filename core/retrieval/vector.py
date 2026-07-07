"""向量索引：ChromaDB + bge-small-zh-v1.5。

降级策略：模型加载失败时 is_available() 返回 False，search 返回空列表。
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

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

    def add_chunks_batch(self, chunks: List[dict]) -> None:
        """批量增量添加 chunks（比循环调用 add_chunk 高效）。

        Args:
            chunks: [{"chunk_id", "doc_id", "content"}]
        """
        if not self._available or not chunks:
            return
        ids = [c["chunk_id"] for c in chunks]
        documents = [c["content"] for c in chunks]
        metadatas = [{"doc_id": c["doc_id"]} for c in chunks]
        self._collection.add(ids=ids, documents=documents, metadatas=metadatas)

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

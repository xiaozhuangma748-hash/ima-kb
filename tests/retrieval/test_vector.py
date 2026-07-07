"""向量索引测试。"""
from unittest.mock import patch
from core.retrieval.vector import VectorIndex, VectorResult


class _MockEmbeddingFunction:
    """兼容 chromadb 1.5.x 签名校验的 mock embedding 函数。

    chromadb 1.5.x 会校验 __call__ 签名必须为 (self, input)，
    并调用 name()/is_legacy()/default_space()/supported_spaces() 等方法，
    MagicMock 无法满足，因此用真实类。
    """

    def __init__(self, return_vector=None):
        self.return_vector = return_vector or [0.1, 0.2, 0.3]

    def __call__(self, input):
        # input 是文本列表，返回等长的向量列表
        return [self.return_vector for _ in input]

    def embed_query(self, input):
        # chromadb 1.5.x 查询时调用此方法（默认调用 __call__）
        return self.__call__(input)

    def embed_documents(self, input):
        # chromadb 1.5.x 文档入库时调用此方法（默认调用 __call__）
        return self.__call__(input)

    @staticmethod
    def name() -> str:
        return "mock_embedding"

    @staticmethod
    def is_legacy() -> bool:
        return False

    @staticmethod
    def default_space() -> str:
        return "l2"

    @staticmethod
    def supported_spaces():
        return ["cosine", "l2", "ip"]

    @staticmethod
    def build_from_config(config):
        return _MockEmbeddingFunction()

    @staticmethod
    def get_config():
        return {}


def test_vector_result_dataclass():
    """VectorResult 包含 chunk_id/doc_id/score。"""
    r = VectorResult(chunk_id="chunk_1", doc_id="doc_1", score=0.95)
    assert r.chunk_id == "chunk_1"
    assert r.doc_id == "doc_1"
    assert r.score == 0.95


@patch("core.retrieval.vector._get_embedding_function")
def test_build_index_empty_chunks(mock_get_ef, tmp_path):
    """空 chunks 列表构建索引不报错。"""
    mock_ef = _MockEmbeddingFunction()
    mock_get_ef.return_value = mock_ef
    index = VectorIndex(storage_path=tmp_path)
    index.build_index([])
    assert index.is_available()


@patch("core.retrieval.vector._get_embedding_function")
def test_add_and_search(mock_get_ef, tmp_path):
    """添加 chunk 后能搜索到。"""
    mock_ef = _MockEmbeddingFunction(return_vector=[0.1, 0.2, 0.3])
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
    mock_ef = _MockEmbeddingFunction()
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

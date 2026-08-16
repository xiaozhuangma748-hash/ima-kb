"""临时脚本：对比不同检索模式下 hybrid.search 的召回差异。"""
import os
os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")

from config import settings
from core.storage import Storage
from core.retrieval.hybrid import HybridRetriever

storage = Storage(settings.storage_path)
from core.retrieval.vector import VectorIndex
vi = VectorIndex(settings.storage_path)
hybrid = HybridRetriever(bm25_index=storage.bm25, vector_index=vi, storage=storage)

query = "杭州市节地生态安葬奖补标准"

for use_vector in (True, False):
    # 关闭 use_cache，避免缓存掩盖差异
    res = hybrid.search(query, top_k=10, use_cache=False, use_vector=use_vector)
    print(f"\n===== use_vector={use_vector} =====")
    for r in res[:5]:
        print(f"  [{r.source}] {r.doc_title} §{r.paragraph_num} score={r.score:.3f} :: {r.content[:40]}")

print("\n向量可用:", vi.is_available())
"""SimHash 近似去重：检测内容相似的 chunk。

SimHash 是一种局部敏感哈希，相似文本的哈希值汉明距离小。
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

# SimHash 位数
_SIMHASH_BITS = 64
# 汉明距离阈值（≤3 判定为近似重复）
_DEFAULT_HAMMING_THRESHOLD = 3
# 相似度阈值（similarity = 1 - hamming / 64）
_DEFAULT_SIMILARITY_THRESHOLD = 0.85

# 中文分词（简单按字符 + 标点切分）
_TOKEN_PATTERN = re.compile(r'[\u4e00-\u9fff]|[a-zA-Z]+|[0-9]+')


class SimHash:
    """SimHash 计算。"""

    @staticmethod
    def compute(text: str, hash_bits: int = _SIMHASH_BITS) -> int:
        """计算文本的 SimHash 值。

        Args:
            text: 输入文本
            hash_bits: 哈希位数（默认 64）

        Returns:
            SimHash 值（整数）
        """
        if not text.strip():
            return 0

        # 分词
        tokens = _TOKEN_PATTERN.findall(text)
        if not tokens:
            return 0

        # 初始化权重向量
        v = [0] * hash_bits

        for token in tokens:
            # 对每个 token 计算普通哈希
            h = int(hashlib.md5(token.encode("utf-8")).hexdigest(), 16)
            # 对每一位加权
            for i in range(hash_bits):
                bit = (h >> i) & 1
                if bit:
                    v[i] += 1
                else:
                    v[i] -= 1

        # 生成指纹
        fingerprint = 0
        for i in range(hash_bits):
            if v[i] > 0:
                fingerprint |= (1 << i)

        return fingerprint

    @staticmethod
    def hamming_distance(hash1: int, hash2: int) -> int:
        """计算两个 SimHash 的汉明距离。"""
        xor = hash1 ^ hash2
        distance = 0
        while xor:
            distance += xor & 1
            xor >>= 1
        return distance

    @staticmethod
    def similarity(hash1: int, hash2: int, hash_bits: int = _SIMHASH_BITS) -> float:
        """计算相似度（0-1）。"""
        distance = SimHash.hamming_distance(hash1, hash2)
        return 1.0 - distance / hash_bits


@dataclass
class DedupResult:
    """去重结果。"""
    chunk_id: str
    doc_id: str
    duplicate_of: str = ""
    similarity: float = 0.0
    hamming_distance: int = 64

    @property
    def is_duplicate(self) -> bool:
        """是否为近似重复。"""
        return self.similarity >= _DEFAULT_SIMILARITY_THRESHOLD and bool(self.duplicate_of)


class DedupScanner:
    """近似重复扫描器。"""

    def __init__(
        self,
        threshold: float = _DEFAULT_SIMILARITY_THRESHOLD,
        hamming_threshold: int = _DEFAULT_HAMMING_THRESHOLD,
    ) -> None:
        self.threshold = threshold
        self.hamming_threshold = hamming_threshold
        # chunk_id → (doc_id, simhash)
        self._chunks: Dict[str, Tuple[str, int]] = {}

    def add_chunk(self, chunk_id: str, doc_id: str, content: str) -> None:
        """添加待扫描的 chunk。"""
        sh = SimHash.compute(content)
        self._chunks[chunk_id] = (doc_id, sh)

    def scan(self) -> List[DedupResult]:
        """扫描所有 chunk，找出近似重复。

        每个 chunk 只与第一个相似的 chunk 建立重复关系。
        """
        results: List[DedupResult] = []
        chunk_ids = list(self._chunks.keys())

        for i, cid in enumerate(chunk_ids):
            doc_id, sh = self._chunks[cid]
            best_match = ""
            best_sim = 0.0
            best_dist = 64

            # 只与前面的 chunk 比较（避免双向重复）
            for j in range(i):
                other_id = chunk_ids[j]
                _, other_sh = self._chunks[other_id]
                dist = SimHash.hamming_distance(sh, other_sh)
                sim = SimHash.similarity(sh, other_sh)

                if sim >= self.threshold and sim > best_sim:
                    best_match = other_id
                    best_sim = sim
                    best_dist = dist

            results.append(DedupResult(
                chunk_id=cid,
                doc_id=doc_id,
                duplicate_of=best_match,
                similarity=best_sim if best_match else 0.0,
                hamming_distance=best_dist if best_match else 64,
            ))

        return results

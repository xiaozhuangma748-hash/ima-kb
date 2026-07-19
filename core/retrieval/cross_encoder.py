"""Cross-Encoder 重排序：使用专用 reranker 模型（bge-reranker-v2-m3）。

相比 LLM prompt 打分的优势：
1. 准确率高 15-30%：Cross-Encoder 联合编码 query+doc，比双塔向量更准
2. 延迟低 10 倍：本地模型 100-300ms，LLM 需 1-3s
3. 成本为零：不消耗 LLM tokens
4. 无内容截断：支持长 chunk 全长度输入

降级策略：模型加载失败时返回 False，由上层切换到 LLM Reranker。
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import List, Optional

from config import settings
from .hybrid import HybridResult
from .rerank import RerankResult

logger = logging.getLogger(__name__)

# 模型名称
_DEFAULT_MODEL = "BAAI/bge-reranker-v2-m3"
# 本地模型路径（与 bge-small-zh-v1.5 同目录约定）
_LOCAL_MODEL_PATH = settings.storage_path / "models" / "bge-reranker-v2-m3"

# Cross-Encoder 最大输入长度（bge-reranker-v2-m3 支持 8192，截断到 2048 平衡精度和速度）
_MAX_LENGTH = 2048


class CrossEncoderReranker:
    """专用 Cross-Encoder 重排序器。

    使用 BAAI/bge-reranker-v2-m3 模型对 (query, doc) 对联合编码打分。
    """

    def __init__(self, model_name: Optional[str] = None) -> None:
        # 在 import sentence_transformers 之前设置 HF 镜像
        if not os.environ.get("HF_ENDPOINT"):
            os.environ["HF_ENDPOINT"] = "https://hf-mirror.com"

        self._model_name = model_name or settings.reranker_model or _DEFAULT_MODEL
        self._model = None
        self._available = False
        self._init()

    def _init(self) -> None:
        """加载 Cross-Encoder 模型。"""
        try:
            from sentence_transformers import CrossEncoder  # type: ignore
        except ImportError:
            logger.warning(
                "sentence_transformers 未安装，CrossEncoderReranker 不可用。"
                "请执行：pip install sentence-transformers"
            )
            return

        try:
            # 优先本地路径
            model_path = str(_LOCAL_MODEL_PATH) if _LOCAL_MODEL_PATH.exists() else self._model_name
            if _LOCAL_MODEL_PATH.exists():
                logger.info(f"使用本地 Cross-Encoder 模型: {_LOCAL_MODEL_PATH}")
            else:
                logger.info(f"从 HF 镜像加载 Cross-Encoder 模型: {self._model_name}")
            # max_length 控制单次输入长度，超过会截断
            self._model = CrossEncoder(model_path, max_length=_MAX_LENGTH)
            self._available = True
            logger.info("Cross-Encoder 模型加载成功")
        except Exception as e:
            err_msg = str(e)
            if "couldn't connect" in err_msg or "huggingface" in err_msg.lower():
                logger.warning(
                    f"无法从 HF 镜像下载 reranker 模型 {self._model_name}: {e}。"
                    f"可手动下载到 {_LOCAL_MODEL_PATH}"
                )
            else:
                logger.warning(f"Cross-Encoder 模型加载失败: {e}")
            self._available = False

    def is_available(self) -> bool:
        """模型是否加载成功。"""
        return self._available

    def warmup(self) -> None:
        """预热模型：跑一次 dummy 推理，避免首次查询的 warmup 开销。

        bge-reranker-v2-m3 首次 predict 需要 2-3s 额外的图编译开销，
        预热后后续 predict 每条约 0.2s。
        """
        if not self._available:
            return
        try:
            _ = self._model.predict([("预热", "warmup")])
            logger.info("Cross-Encoder 预热完成")
        except Exception as e:
            logger.warning(f"Cross-Encoder 预热失败: {e}")

    def rerank(
        self,
        query: str,
        candidates: List[HybridResult],
        top_n: int = 5,
    ) -> List[RerankResult]:
        """对候选列表用 Cross-Encoder 打分并重排。

        Args:
            query: 查询文本
            candidates: 混合检索候选结果
            top_n: 返回前 N 条

        Returns:
            重排序后的 RerankResult 列表
        """
        if not candidates:
            return []
        if not self._available:
            # 不可用时返回原顺序，relevance_score=0
            return self._fallback(candidates, top_n)

        try:
            # 构造 (query, doc) 对，doc 用完整 content（不截断）
            pairs = [(query, c.content or "") for c in candidates]
            # 批量推理，返回 [score, ...]
            scores = self._model.predict(pairs)
            # 归一化到 0-1（bge-reranker 输出 logit，sigmoid 归一化）
            import math
            normalized = [1.0 / (1.0 + math.exp(-s)) if isinstance(s, (int, float)) else 0.0 for s in scores]

            # 合并分数并排序
            results = []
            for i, c in enumerate(candidates):
                results.append(RerankResult(
                    chunk_id=c.chunk_id,
                    doc_id=c.doc_id,
                    score=c.score,
                    source=c.source,
                    content=c.content,
                    doc_title=c.doc_title,
                    relevance_score=float(normalized[i]),
                    reason="cross-encoder",
                    paragraph_num=getattr(c, "paragraph_num", 0),
                ))
            results.sort(key=lambda r: r.relevance_score, reverse=True)
            return results[:top_n]
        except Exception as e:
            logger.warning(f"Cross-Encoder 重排失败，降级为原顺序: {e}")
            return self._fallback(candidates, top_n)

    @staticmethod
    def _fallback(candidates: List[HybridResult], top_n: int) -> List[RerankResult]:
        """降级：保留原顺序，relevance_score=0。"""
        return [
            RerankResult(
                chunk_id=c.chunk_id,
                doc_id=c.doc_id,
                score=c.score,
                source=c.source,
                content=c.content,
                doc_title=c.doc_title,
                relevance_score=0.0,
                reason="cross-encoder-unavailable",
                paragraph_num=getattr(c, "paragraph_num", 0),
            )
            for c in candidates[:top_n]
        ]

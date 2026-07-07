"""数据质量检查：检测低质量 chunk（过短/乱码/纯符号）。"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from typing import Dict, List, Optional


# 质量阈值
MIN_CHUNK_LENGTH = 20  # 最少 20 字符
MAX_SYMBOL_RATIO = 0.5  # 符号占比超过 50% 判定为低质量
MAX_GARBLE_RATIO = 0.3  # 乱码字符占比超过 30% 判定为 OCR 乱码

# 乱码字符集（OCR 常见错误输出）
_GARBLE_CHARS = set("□◇△▲▽▼☆★○●◎⊙¤§※△▽◇□")

# 中文字符范围
_CJK_PATTERN = re.compile(r'[\u4e00-\u9fff\u3400-\u4dbf]')
# 可打印文字（中日韩 + 字母；纯数字不算有效文本内容）
_TEXT_PATTERN = re.compile(r'[\u4e00-\u9fff\u3400-\u4dbfa-zA-Z]')


@dataclass
class ChunkQuality:
    """单个 chunk 的质量评估。"""
    chunk_id: str
    doc_id: str
    score: float              # 0-1，越高越好
    issues: List[str] = field(default_factory=list)
    is_low_quality: bool = False


@dataclass
class QualityReport:
    """质量报告汇总。"""
    total_chunks: int = 0
    normal: int = 0
    low_quality: int = 0
    ocr_poor: int = 0
    issues_detail: Dict[str, int] = field(default_factory=dict)

    @property
    def normal_pct(self) -> float:
        """正常占比。"""
        if self.total_chunks == 0:
            return 0.0
        return round(self.normal / self.total_chunks * 100, 1)

    @property
    def health_score(self) -> float:
        """健康分（0-100）。"""
        if self.total_chunks == 0:
            return 100.0
        return round(self.normal / self.total_chunks * 100, 1)


class QualityChecker:
    """数据质量检查器。"""

    def check_chunk(self, chunk_id: str, doc_id: str, content: str) -> ChunkQuality:
        """检查单个 chunk 的质量。

        Args:
            chunk_id: chunk ID
            doc_id: 文档 ID
            content: chunk 文本内容

        Returns:
            ChunkQuality 质量评估结果
        """
        issues: List[str] = []
        text = content.strip()

        if not text:
            return ChunkQuality(
                chunk_id=chunk_id, doc_id=doc_id,
                score=0.0, issues=["empty"], is_low_quality=True,
            )

        # 1. 长度检查
        if len(text) < MIN_CHUNK_LENGTH:
            issues.append("too_short")

        # 2. 纯数字/符号检查
        text_chars = _TEXT_PATTERN.findall(text)
        if len(text_chars) == 0 or len(text_chars) < len(text) * 0.3:
            issues.append("no_text_content")

        # 3. OCR 乱码检查
        garble_count = sum(1 for c in text if c in _GARBLE_CHARS)
        if len(text) > 0 and garble_count / len(text) > MAX_GARBLE_RATIO:
            issues.append("ocr_garbage")

        # 4. 符号占比检查
        symbol_count = sum(1 for c in text if not c.isalnum() and not _CJK_PATTERN.match(c) and c.isspace() is False)
        if len(text) > 0 and symbol_count / len(text) > MAX_SYMBOL_RATIO:
            issues.append("high_symbol_ratio")

        # 计算质量分
        score = self._calculate_score(text, issues)
        # 任意一项 issue 即判定为低质量
        is_low = len(issues) > 0

        return ChunkQuality(
            chunk_id=chunk_id,
            doc_id=doc_id,
            score=score,
            issues=issues,
            is_low_quality=is_low,
        )

    def _calculate_score(self, text: str, issues: List[str]) -> float:
        """计算质量分（0-1）。"""
        score = 1.0
        for issue in issues:
            if issue == "empty":
                score = 0.0
            elif issue == "no_text_content":
                score -= 0.6
            elif issue == "ocr_garbage":
                score -= 0.5
            elif issue == "too_short":
                score -= 0.3
            elif issue == "high_symbol_ratio":
                score -= 0.2
        return max(0.0, min(1.0, score))

    def check_document(self, chunks: List) -> List[ChunkQuality]:
        """检查一个文档的所有 chunk。

        Args:
            chunks: ChunkRecord 列表（有 id, doc_id, content 属性）

        Returns:
            ChunkQuality 列表
        """
        return [
            self.check_chunk(c.id, c.doc_id, c.content)
            for c in chunks
        ]

    def generate_report(self, results: List[ChunkQuality]) -> QualityReport:
        """生成质量报告。"""
        report = QualityReport(total_chunks=len(results))
        for r in results:
            if r.is_low_quality:
                report.low_quality += 1
                if "ocr_garbage" in r.issues:
                    report.ocr_poor += 1
            else:
                report.normal += 1
            for issue in r.issues:
                report.issues_detail[issue] = report.issues_detail.get(issue, 0) + 1
        return report

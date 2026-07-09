"""知识图谱抽取器：用 LLM 从文档中提取实体和关系。

抽取的实体类型：
- region（地区）：杭州市、滨江区、钱塘区等
- agency（机构）：民政局、退役军人事务局等
- topic（主题）：殡葬政策、抚恤金、生态安葬等

抽取的关系类型：
- published_in（政策发布于地区）
- published_by（政策由机构发布）
- covers_topic（政策涉及主题）

LLM 一次调用，输入文档标题+内容预览，输出 JSON。
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from core.llm.client import LLMError, get_llm
from core.ingestion.parser import ParsedDocument


# ============================================================
# 数据模型
# ============================================================

@dataclass
class Entity:
    """实体（图谱节点）。"""
    name: str           # 实体名（如"杭州市民政局"）
    type: str           # 类型：region / agency / topic
    doc_id: str = ""    # 来源文档 ID


@dataclass
class Relation:
    """关系（图谱边）。"""
    source: str         # 源实体名（通常是文档标题）
    target: str         # 目标实体名
    relation: str       # 关系类型：published_in / published_by / covers_topic
    doc_id: str = ""    # 来源文档 ID


@dataclass
class ExtractionResult:
    """单文档抽取结果。"""
    doc_id: str
    doc_title: str
    entities: List[Entity] = field(default_factory=list)
    relations: List[Relation] = field(default_factory=list)


# ============================================================
# LLM 抽取
# ============================================================

EXTRACTOR_SYSTEM_PROMPT = """你是一个信息抽取专家。请从给定文档中提取实体和关系。

## 实体类型
- region（地区）：文档涉及的地理区域，如"杭州市"、"滨江区"、"钱塘区"、"浙江省"
- agency（机构）：提及的组织机构，如"民政局"、"退役军人事务局"、"财政局"、"公司"、"委员会"
- topic（主题）：文档核心主题，如"殡葬政策"、"抚恤金"、"生态安葬"、"收费管理"、"技术方案"

## 关系类型
- published_in：文档内容适用于/涉及某地区
- published_by：文档由某机构发布/制作
- covers_topic：文档涉及某主题

## 输出格式（严格 JSON）
{
  "entities": [
    {"name": "杭州市", "type": "region"},
    {"name": "民政局", "type": "agency"},
    {"name": "殡葬政策", "type": "topic"}
  ],
  "relations": [
    {"source": "文档标题", "target": "杭州市", "relation": "published_in"},
    {"source": "文档标题", "target": "民政局", "relation": "published_by"},
    {"source": "文档标题", "target": "殡葬政策", "relation": "covers_topic"}
  ]
}

## 重要规则
1. 实体名简洁（2-10 字），不要包含编号或修饰词
2. 关系的 source 总是文档标题
3. 严格输出 JSON，不要任何解释文字
4. **如果文档内容极少或无实质性信息，返回空实体和空关系**：{"entities": [], "relations": []}
"""

MAX_CONTENT_PREVIEW = 1200  # 内容预览长度


class GraphExtractor:
    """知识图谱抽取器。"""

    def __init__(self) -> None:
        self.llm = get_llm()

    def extract_from_document(
        self,
        doc_id: str,
        doc_title: str,
        content: str,
    ) -> ExtractionResult:
        """从单个文档提取实体和关系。

        Args:
            doc_id: 文档 ID
            doc_title: 文档标题
            content: 文档全文（或预览）

        Returns:
            ExtractionResult
        """
        content_preview = content[:MAX_CONTENT_PREVIEW].strip()
        if not content_preview:
            return ExtractionResult(doc_id=doc_id, doc_title=doc_title)

        user_prompt = (
            f"文档标题：{doc_title}\n\n"
            f"文档内容：\n{content_preview}\n\n"
            f"请提取实体和关系，严格输出 JSON。"
        )

        try:
            raw = self.llm.chat(
                messages=[
                    {"role": "system", "content": EXTRACTOR_SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0.1,
                max_tokens=512,
            )
        except LLMError:
            return ExtractionResult(doc_id=doc_id, doc_title=doc_title)

        return self._parse_result(raw, doc_id, doc_title)

    def extract_from_parsed(self, parsed: ParsedDocument, doc_id: str = "") -> ExtractionResult:
        """从 ParsedDocument 提取（便利方法）。"""
        return self.extract_from_document(
            doc_id=doc_id,
            doc_title=parsed.title,
            content=parsed.text,
        )

    # ---- 解析 ----

    @staticmethod
    def _parse_result(raw: str, doc_id: str, doc_title: str) -> ExtractionResult:
        """解析 LLM 输出为 ExtractionResult。

        Args:
            raw: LLM 原始输出
            doc_id: 文档 ID
            doc_title: 文档标题

        Returns:
            ExtractionResult
        """
        data = GraphExtractor._extract_json(raw)
        if data is None:
            return ExtractionResult(doc_id=doc_id, doc_title=doc_title)

        entities: List[Entity] = []
        for e in data.get("entities", []):
            name = str(e.get("name", "")).strip()
            etype = str(e.get("type", "topic")).strip().lower()
            if name and etype in ("region", "agency", "topic"):
                entities.append(Entity(name=name, type=etype, doc_id=doc_id))

        relations: List[Relation] = []
        for r in data.get("relations", []):
            source = str(r.get("source", doc_title)).strip()
            target = str(r.get("target", "")).strip()
            rel = str(r.get("relation", "")).strip().lower()
            if source and target and rel in ("published_in", "published_by", "covers_topic"):
                relations.append(Relation(
                    source=source, target=target, relation=rel, doc_id=doc_id,
                ))

        return ExtractionResult(
            doc_id=doc_id, doc_title=doc_title,
            entities=entities, relations=relations,
        )

    @staticmethod
    def _extract_json(raw: str) -> Optional[dict]:
        """从 LLM 输出中提取 JSON 对象（容错处理）。

        支持：
        - 纯 JSON
        - ```json ... ``` 包裹
        - 混杂其他文字中的 JSON
        """
        raw = raw.strip()
        # 1. 尝试直接解析
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            pass
        # 2. 提取 ```json ... ``` 块
        m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", raw, re.DOTALL)
        if m:
            try:
                return json.loads(m.group(1))
            except json.JSONDecodeError:
                pass
        # 3. 提取第一个 { ... } 块
        m = re.search(r"\{[^{}]*\}", raw, re.DOTALL)
        if m:
            try:
                return json.loads(m.group(0))
            except json.JSONDecodeError:
                pass
        return None

"""知识图谱存储：用 networkx 管理图谱，持久化到 JSON。

节点属性：
- id：实体名（唯一）
- label：显示名
- type：region / agency / topic / document
- doc_count：关联文档数
- doc_ids：关联文档 ID 列表

边属性：
- relation：published_in / published_by / covers_topic
- doc_id：来源文档 ID
"""
from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import networkx as nx

from config import settings
from core.graph.extractor import ExtractionResult, Entity, Relation

logger = logging.getLogger(__name__)


# 节点类型颜色（用于可视化）
NODE_COLORS = {
    "document": "#FFA500",  # 橙色（政策文档）
    "region":   "#00CED1",  # 青色（地区）
    "agency":   "#FF6347",  # 番茄红（机构）
    "topic":    "#9370DB",  # 紫色（主题）
}

# 关系类型中文标签
RELATION_LABELS = {
    "published_in": "发布于",
    "published_by": "发布机构",
    "covers_topic": "涉及主题",
}


class GraphStore:
    """知识图谱存储（networkx + JSON 持久化）。"""

    def __init__(self, storage_path: Optional[Path] = None) -> None:
        self.storage_path = storage_path or settings.storage_path
        self.graph_path = self.storage_path / "graph.json"
        self.graph: nx.Graph = nx.Graph()
        self._load()

    # ---- 持久化 ----

    def _load(self) -> None:
        """从 JSON 加载图谱。"""
        if not self.graph_path.exists():
            return
        try:
            data = json.loads(self.graph_path.read_text(encoding="utf-8"))
            # 重建图
            self.graph = nx.Graph()
            for node in data.get("nodes", []):
                self.graph.add_node(
                    node["id"],
                    label=node.get("label", node["id"]),
                    type=node.get("type", "topic"),
                    doc_count=node.get("doc_count", 0),
                    doc_ids=node.get("doc_ids", []),
                )
            for edge in data.get("edges", []):
                self.graph.add_edge(
                    edge["source"],
                    edge["target"],
                    relation=edge.get("relation", ""),
                    doc_id=edge.get("doc_id", ""),
                )
        except (json.JSONDecodeError, KeyError) as e:
            # 备份损坏文件后重置空图（与 MemoryStore/PetStorage 保持一致）
            bak = self.graph_path.parent / f"{self.graph_path.name}.bak.{int(time.time())}"
            try:
                self.graph_path.rename(bak)
                logger.warning(f"图谱文件损坏（{type(e).__name__}: {e}），已备份到 {bak}")
            except Exception:
                pass
            self.graph = nx.Graph()

    def save(self) -> None:
        """保存图谱到 JSON。"""
        data = {
            "nodes": [
                {
                    "id": n,
                    "label": d.get("label", n),
                    "type": d.get("type", "topic"),
                    "doc_count": d.get("doc_count", 0),
                    "doc_ids": d.get("doc_ids", []),
                }
                for n, d in self.graph.nodes(data=True)
            ],
            "edges": [
                {
                    "source": u,
                    "target": v,
                    "relation": d.get("relation", ""),
                    "doc_id": d.get("doc_id", ""),
                }
                for u, v, d in self.graph.edges(data=True)
            ],
        }
        self.storage_path.mkdir(parents=True, exist_ok=True)
        self.graph_path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    # ---- 写入 ----

    def add_extraction(self, result: ExtractionResult) -> None:
        """把一次抽取结果加入图谱。

        Args:
            result: ExtractionResult
        """
        # 1. 文档节点（中心节点）
        doc_node = result.doc_title
        if doc_node not in self.graph:
            self.graph.add_node(
                doc_node,
                label=doc_node,
                type="document",
                doc_count=0,
                doc_ids=[],
            )
        # 关联 doc_id
        doc_ids: List[str] = self.graph.nodes[doc_node].get("doc_ids", [])
        if result.doc_id and result.doc_id not in doc_ids:
            doc_ids.append(result.doc_id)
            self.graph.nodes[doc_node]["doc_ids"] = doc_ids
        self.graph.nodes[doc_node]["doc_count"] = len(doc_ids)

        # 2. 实体节点
        for entity in result.entities:
            if entity.name not in self.graph:
                self.graph.add_node(
                    entity.name,
                    label=entity.name,
                    type=entity.type,
                    doc_count=0,
                    doc_ids=[],
                )
            # 累加 doc_id
            e_doc_ids: List[str] = self.graph.nodes[entity.name].get("doc_ids", [])
            if entity.doc_id and entity.doc_id not in e_doc_ids:
                e_doc_ids.append(entity.doc_id)
                self.graph.nodes[entity.name]["doc_ids"] = e_doc_ids
            self.graph.nodes[entity.name]["doc_count"] = len(e_doc_ids)

        # 3. 关系边
        for rel in result.relations:
            # 确保两端节点都存在
            for endpoint in (rel.source, rel.target):
                if endpoint not in self.graph:
                    self.graph.add_node(
                        endpoint,
                        label=endpoint,
                        type="topic",  # 默认类型
                        doc_count=0,
                        doc_ids=[],
                    )
            self.graph.add_edge(
                rel.source,
                rel.target,
                relation=rel.relation,
                doc_id=rel.doc_id,
            )

    def clear(self) -> None:
        """清空图谱。"""
        self.graph.clear()
        if self.graph_path.exists():
            self.graph_path.unlink()

    def delete_node(self, node_name: str) -> bool:
        """删除单个节点（及其所有连边）。

        Args:
            node_name: 节点 ID（实体名）

        Returns:
            True 表示删除成功，False 表示节点不存在
        """
        if node_name not in self.graph:
            return False
        self.graph.remove_node(node_name)
        return True

    def rename_node(self, old_name: str, new_name: str) -> bool:
        """重命名节点（保留所有连边和属性）。

        Args:
            old_name: 原节点 ID
            new_name: 新节点 ID

        Returns:
            True 表示成功，False 表示原节点不存在或新名称已存在
        """
        if old_name not in self.graph:
            return False
        if new_name == old_name:
            return True
        if new_name in self.graph:
            return False
        # networkx 没有直接的 rename，用 relabel_node
        nx.relabel_nodes(self.graph, {old_name: new_name}, copy=False)
        return True

    # ---- 查询 ----

    def stats(self) -> Dict[str, Any]:
        """图谱统计信息。"""
        nodes_by_type: Dict[str, int] = {}
        for n, d in self.graph.nodes(data=True):
            ntype = d.get("type", "unknown")
            nodes_by_type[ntype] = nodes_by_type.get(ntype, 0) + 1

        edges_by_relation: Dict[str, int] = {}
        for u, v, d in self.graph.edges(data=True):
            rel = d.get("relation", "unknown")
            edges_by_relation[rel] = edges_by_relation.get(rel, 0) + 1

        return {
            "nodes": self.graph.number_of_nodes(),
            "edges": self.graph.number_of_edges(),
            "nodes_by_type": nodes_by_type,
            "edges_by_relation": edges_by_relation,
        }

    def list_nodes(self, node_type: Optional[str] = None) -> List[Dict[str, Any]]:
        """列出节点（可按类型筛选）。"""
        result = []
        for n, d in self.graph.nodes(data=True):
            if node_type and d.get("type") != node_type:
                continue
            result.append({
                "id": n,
                "label": d.get("label", n),
                "type": d.get("type", "topic"),
                "doc_count": d.get("doc_count", 0),
                "degree": self.graph.degree(n),
            })
        # 按连接数倒序
        result.sort(key=lambda x: x["degree"], reverse=True)
        return result

    def list_edges(self) -> List[Dict[str, Any]]:
        """列出所有边。"""
        return [
            {
                "source": u,
                "target": v,
                "relation": d.get("relation", ""),
                "relation_label": RELATION_LABELS.get(d.get("relation", ""), d.get("relation", "")),
                "doc_id": d.get("doc_id", ""),
            }
            for u, v, d in self.graph.edges(data=True)
        ]

    def neighbors(self, node_name: str) -> List[Dict[str, Any]]:
        """查询某节点的邻居。"""
        if node_name not in self.graph:
            return []
        result = []
        for neighbor in self.graph.neighbors(node_name):
            edge_data = self.graph.get_edge_data(node_name, neighbor) or {}
            node_data = self.graph.nodes[neighbor]
            result.append({
                "node": neighbor,
                "type": node_data.get("type", "topic"),
                "relation": edge_data.get("relation", ""),
                "relation_label": RELATION_LABELS.get(edge_data.get("relation", ""), ""),
            })
        return result

    def search_nodes(self, keyword: str) -> List[Dict[str, Any]]:
        """按关键词搜索节点。"""
        keyword = keyword.lower()
        result = []
        for n, d in self.graph.nodes(data=True):
            if keyword in n.lower() or keyword in d.get("label", "").lower():
                result.append({
                    "id": n,
                    "label": d.get("label", n),
                    "type": d.get("type", "topic"),
                    "doc_count": d.get("doc_count", 0),
                    "degree": self.graph.degree(n),
                })
        result.sort(key=lambda x: x["degree"], reverse=True)
        return result

    # ---- 导出 ----

    def to_cytoscape(self) -> Dict[str, Any]:
        """导出为 Cytoscape.js 标准 JSON 格式（前端可视化用）。

        返回 ``{elements: {nodes: [...], edges: [...]}}`` 结构，
        可直接喂给 Cytoscape.js / Gephi 等工具。
        """
        return {
            "elements": {
                "nodes": [
                    {
                        "data": {
                            "id": n,
                            "label": d.get("label", n),
                            "type": d.get("type", "topic"),
                            "color": NODE_COLORS.get(d.get("type", "topic"), "#888888"),
                            "doc_count": d.get("doc_count", 0),
                            "degree": self.graph.degree(n),
                        }
                    }
                    for n, d in self.graph.nodes(data=True)
                ],
                "edges": [
                    {
                        "data": {
                            "id": f"e{i}",
                            "source": u,
                            "target": v,
                            "relation": d.get("relation", ""),
                            "label": RELATION_LABELS.get(d.get("relation", ""), ""),
                        }
                    }
                    for i, (u, v, d) in enumerate(self.graph.edges(data=True))
                ],
            }
        }

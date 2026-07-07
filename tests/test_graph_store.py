"""GraphStore 节点管理测试（Group 2: 展示但没设置入口）。"""
import pytest
from pathlib import Path

from core.graph.store import GraphStore
from core.graph.extractor import ExtractionResult, Entity, Relation


def _make_result(doc_title="测试文档", doc_id="doc_001") -> ExtractionResult:
    """构造一个抽取结果用于测试。"""
    return ExtractionResult(
        doc_title=doc_title,
        doc_id=doc_id,
        entities=[
            Entity(name="杭州市", type="region", doc_id=doc_id),
            Entity(name="民政局", type="agency", doc_id=doc_id),
            Entity(name="骨灰安置", type="topic", doc_id=doc_id),
        ],
        relations=[
            Relation(source=doc_title, target="杭州市", relation="published_in", doc_id=doc_id),
            Relation(source=doc_title, target="民政局", relation="published_by", doc_id=doc_id),
            Relation(source=doc_title, target="骨灰安置", relation="covers_topic", doc_id=doc_id),
        ],
    )


def test_delete_node_removes_node_and_edges(tmp_path):
    """delete_node 删除节点及其所有连边。"""
    gs = GraphStore(storage_path=tmp_path)
    gs.add_extraction(_make_result())
    assert "杭州市" in gs.graph
    assert gs.graph.number_of_edges() == 3

    ok = gs.delete_node("杭州市")
    assert ok is True
    assert "杭州市" not in gs.graph
    # 与杭州市相连的边也删除
    assert gs.graph.number_of_edges() == 2


def test_delete_node_not_exists(tmp_path):
    """删除不存在的节点返回 False。"""
    gs = GraphStore(storage_path=tmp_path)
    ok = gs.delete_node("不存在的节点")
    assert ok is False


def test_delete_node_persists_after_save(tmp_path):
    """删除后 save 再加载，节点确实没了。"""
    gs = GraphStore(storage_path=tmp_path)
    gs.add_extraction(_make_result())
    gs.delete_node("杭州市")
    gs.save()

    gs2 = GraphStore(storage_path=tmp_path)
    assert "杭州市" not in gs2.graph


def test_rename_node_preserves_edges(tmp_path):
    """rename_node 保留所有连边和属性。"""
    gs = GraphStore(storage_path=tmp_path)
    gs.add_extraction(_make_result())
    old_degree = gs.graph.degree("杭州市")

    ok = gs.rename_node("杭州市", "杭州")
    assert ok is True
    assert "杭州市" not in gs.graph
    assert "杭州" in gs.graph
    assert gs.graph.degree("杭州") == old_degree


def test_rename_node_old_not_exists(tmp_path):
    """原节点不存在时返回 False。"""
    gs = GraphStore(storage_path=tmp_path)
    ok = gs.rename_node("不存在", "新名")
    assert ok is False


def test_rename_node_new_exists(tmp_path):
    """新名称已存在时返回 False。"""
    gs = GraphStore(storage_path=tmp_path)
    gs.add_extraction(_make_result())
    # "民政局" 已存在
    ok = gs.rename_node("杭州市", "民政局")
    assert ok is False


def test_rename_node_same_name(tmp_path):
    """新旧名称相同时返回 True（无操作）。"""
    gs = GraphStore(storage_path=tmp_path)
    gs.add_extraction(_make_result())
    ok = gs.rename_node("杭州市", "杭州市")
    assert ok is True

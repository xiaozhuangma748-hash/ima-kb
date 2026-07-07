"""知识图谱页面：交互式可视化 + 节点查询。"""
from __future__ import annotations

import json
from pathlib import Path

import streamlit as st
import streamlit.components.v1 as components

from core.storage import Storage
from core.graph.store import GraphStore, NODE_COLORS, RELATION_LABELS


def render(storage: Storage) -> None:
    """渲染知识图谱页面。"""
    st.title("🌐 知识图谱")

    gs = GraphStore()

    # ---- 空图谱提示 ----
    if gs.graph.number_of_nodes() == 0:
        st.warning("图谱为空")
        st.info("💡 在终端运行 `ima graph build` 从文档中抽取实体和关系，构建知识图谱。")
        st.code("ima graph build --force", language="bash")
        return

    # ---- 统计卡片 ----
    stats = gs.stats()
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("节点总数", stats["nodes"])
    with col2:
        st.metric("边总数", stats["edges"])
    with col3:
        st.metric("政策文档", stats["nodes_by_type"].get("document", 0))
    with col4:
        st.metric("主题数", stats["nodes_by_type"].get("topic", 0))

    # ---- 标签筛选 ----
    st.subheader("图谱可视化")
    type_filter = st.selectbox(
        "按类型筛选节点",
        ["全部", "政策文档", "地区", "机构", "主题"],
        index=0,
    )
    type_map = {
        "全部": None,
        "政策文档": "document",
        "地区": "region",
        "机构": "agency",
        "主题": "topic",
    }
    selected_type = type_map[type_filter]

    # ---- 可视化 ----
    _render_vis_network(gs, selected_type)

    # ---- 节点列表 ----
    st.subheader("节点列表（按连接数排序）")
    nodes = gs.list_nodes(node_type=selected_type)
    if nodes:
        type_names = {"document": "文档", "region": "地区", "agency": "机构", "topic": "主题"}
        node_data = [
            {
                "名称": n["label"],
                "类型": type_names.get(n["type"], n["type"]),
                "连接数": n["degree"],
                "关联文档": n["doc_count"],
            }
            for n in nodes
        ]
        st.dataframe(node_data, width="stretch", height=300)

    # ---- 节点查询 ----
    st.subheader("节点关系查询")
    all_nodes = sorted([n["label"] for n in gs.list_nodes()])
    if all_nodes:
        selected = st.selectbox("选择节点查看邻居", [""] + all_nodes)
        if selected:
            neighbors = gs.neighbors(selected)
            node_data = gs.graph.nodes[selected]
            type_names = {"document": "政策文档", "region": "地区", "agency": "机构", "topic": "主题"}

            st.write(f"**{selected}** · {type_names.get(node_data.get('type', ''), '')}")
            st.write(f"关联文档 {node_data.get('doc_count', 0)} · 连接数 {len(neighbors)}")

            if neighbors:
                nb_data = [
                    {
                        "邻居节点": nb["node"],
                        "类型": type_names.get(nb["type"], nb["type"]),
                        "关系": nb["relation_label"],
                    }
                    for nb in neighbors
                ]
                st.dataframe(nb_data, width="stretch")
            else:
                st.info("该节点没有邻居")

    # ---- 导出 ----
    st.subheader("导出")
    col1, col2 = st.columns(2)
    with col1:
        if st.button("📁 导出 HTML 可视化"):
            from core.graph.visualizer import generate_html
            html_path = generate_html(gs)
            st.success(f"已导出到: {html_path}")
            with open(html_path, "r", encoding="utf-8") as f:
                html_content = f.read()
            st.download_button(
                label="下载 HTML 文件",
                data=html_content,
                file_name="ima_graph.html",
                mime="text/html",
            )
    with col2:
        # 导出 Cytoscape JSON
        if st.button("📋 导出 JSON 数据"):
            cyto = gs.to_cytoscape()
            json_str = json.dumps(cyto, ensure_ascii=False, indent=2)
            st.download_button(
                label="下载 JSON",
                data=json_str,
                file_name="ima_graph.json",
                mime="application/json",
            )


def _render_vis_network(gs: GraphStore, node_type: str | None = None) -> None:
    """用 vis.js 渲染交互式网络图（嵌入 iframe）。

    Args:
        gs: GraphStore 实例
        node_type: 筛选节点类型（None=全部）
    """
    # 准备节点和边数据
    nodes_data = []
    for n, d in gs.graph.nodes(data=True):
        ntype = d.get("type", "topic")
        if node_type and ntype != node_type:
            continue
        degree = gs.graph.degree(n)
        size = min(35, max(12, 12 + degree * 2))
        nodes_data.append({
            "id": n,
            "label": d.get("label", n),
            "color": NODE_COLORS.get(ntype, "#888888"),
            "size": size,
            "title": f"{d.get('label', n)}\n类型: {ntype}\n连接数: {degree}",
        })

    # 过滤后的节点集合
    visible_nodes = {n["id"] for n in nodes_data}

    edges_data = []
    for i, (u, v, d) in enumerate(gs.graph.edges(data=True)):
        # 只显示两端都可见的边
        if u not in visible_nodes or v not in visible_nodes:
            continue
        rel = d.get("relation", "")
        edges_data.append({
            "id": f"e{i}",
            "from": u,
            "to": v,
            "label": RELATION_LABELS.get(rel, rel),
        })

    # HTML 模板（vis.js CDN）
    html = f"""
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <script src="https://unpkg.com/vis-network/standalone/umd/vis-network.min.js"></script>
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{
            font-family: -apple-system, "PingFang SC", sans-serif;
            background: #1a1a2e;
            height: 100vh;
            overflow: hidden;
        }}
        #network {{
            width: 100%;
            height: 100%;
        }}
    </style>
</head>
<body>
    <div id="network"></div>
    <script>
        const nodes = new vis.DataSet({json.dumps(nodes_data, ensure_ascii=False)});
        const edges = new vis.DataSet({json.dumps(edges_data, ensure_ascii=False)});
        const container = document.getElementById('network');
        const data = {{ nodes, edges }};
        const options = {{
            nodes: {{
                shape: 'dot',
                font: {{ color: '#e0e0e0', size: 13, face: 'PingFang SC' }},
                borderWidth: 2,
            }},
            edges: {{
                color: {{ color: '#555', highlight: '#FFA500' }},
                font: {{ color: '#888', size: 10, face: 'PingFang SC' }},
                arrows: {{ to: {{ enabled: true, scaleFactor: 0.5 }} }},
                smooth: {{ type: 'continuous' }},
            }},
            physics: {{
                barnesHut: {{
                    gravitationalConstant: -8000,
                    springConstant: 0.04,
                    springLength: 150,
                }},
                stabilization: {{ iterations: 200 }},
            }},
            interaction: {{ hover: true, tooltipDelay: 200 }},
        }};
        new vis.Network(container, data, options);
    </script>
</body>
</html>
"""
    components.html(html, height=600)

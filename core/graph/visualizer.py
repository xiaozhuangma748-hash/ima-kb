"""知识图谱可视化：用 pyvis 生成交互式 HTML。

pyvis 基于 vis.js，生成自包含的 HTML 文件，浏览器直接打开即可。
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from config import settings
from core.graph.store import GraphStore, NODE_COLORS, RELATION_LABELS


# HTML 模板（自包含，含 vis.js CDN）
HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <title>IMA 知识图谱</title>
    <script src="https://unpkg.com/vis-network/standalone/umd/vis-network.min.js"></script>
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{
            font-family: -apple-system, BlinkMacSystemFont, "PingFang SC", sans-serif;
            background: #1a1a2e;
            color: #e0e0e0;
            height: 100vh;
            display: flex;
            flex-direction: column;
        }}
        .header {{
            background: #16213e;
            padding: 16px 24px;
            border-bottom: 1px solid #0f3460;
        }}
        .header h1 {{
            color: #FFA500;
            font-size: 20px;
            margin-bottom: 4px;
        }}
        .header .stats {{
            color: #888;
            font-size: 13px;
        }}
        .container {{
            display: flex;
            flex: 1;
            overflow: hidden;
        }}
        #network {{
            flex: 1;
            background: #1a1a2e;
        }}
        .sidebar {{
            width: 280px;
            background: #16213e;
            border-left: 1px solid #0f3460;
            padding: 16px;
            overflow-y: auto;
        }}
        .sidebar h2 {{
            color: #00CED1;
            font-size: 14px;
            margin-bottom: 12px;
            text-transform: uppercase;
            letter-spacing: 1px;
        }}
        .legend-item {{
            display: flex;
            align-items: center;
            margin-bottom: 8px;
            font-size: 13px;
        }}
        .legend-color {{
            width: 16px;
            height: 16px;
            border-radius: 50%;
            margin-right: 10px;
            display: inline-block;
        }}
        .info-panel {{
            margin-top: 20px;
            padding: 12px;
            background: #0f3460;
            border-radius: 6px;
            font-size: 12px;
            display: none;
        }}
        .info-panel.visible {{ display: block; }}
        .info-panel h3 {{
            color: #FFA500;
            margin-bottom: 8px;
        }}
        .info-panel .neighbor {{
            padding: 4px 0;
            border-bottom: 1px solid #1a1a3e;
        }}
        .info-panel .neighbor:last-child {{ border: none; }}
    </style>
</head>
<body>
    <div class="header">
        <h1>📚 IMA 知识图谱</h1>
        <div class="stats">{stats}</div>
    </div>
    <div class="container">
        <div id="network"></div>
        <div class="sidebar">
            <h2>图例</h2>
            <div class="legend-item"><span class="legend-color" style="background:#FFA500"></span>政策文档</div>
            <div class="legend-item"><span class="legend-color" style="background:#00CED1"></span>地区</div>
            <div class="legend-item"><span class="legend-color" style="background:#FF6347"></span>机构</div>
            <div class="legend-item"><span class="legend-color" style="background:#9370DB"></span>主题</div>

            <div class="info-panel" id="infoPanel">
                <h3 id="infoTitle"></h3>
                <div id="infoNeighbors"></div>
            </div>
        </div>
    </div>

    <script>
        // 节点和边数据
        const nodes = new vis.DataSet({nodes_json});
        const edges = new vis.DataSet({edges_json});

        // 创建网络
        const container = document.getElementById('network');
        const data = {{ nodes: nodes, edges: edges }};
        const options = {{
            nodes: {{
                shape: 'dot',
                size: 16,
                font: {{
                    color: '#e0e0e0',
                    size: 13,
                    face: 'PingFang SC',
                }},
                borderWidth: 2,
            }},
            edges: {{
                color: {{ color: '#444', highlight: '#FFA500', hover: '#888' }},
                font: {{
                    color: '#888',
                    size: 10,
                    strokeWidth: 0,
                    face: 'PingFang SC',
                }},
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
            interaction: {{
                hover: true,
                tooltipDelay: 200,
            }},
        }};

        const network = new vis.Network(container, data, options);

        // 点击节点显示信息
        network.on('click', function(params) {{
            if (params.nodes.length > 0) {{
                const nodeId = params.nodes[0];
                const node = nodes.get(nodeId);
                document.getElementById('infoTitle').textContent = node.label;
                const neighbors = network.getConnectedNodes(nodeId);
                const neighborInfo = neighbors.map(n => {{
                    const nb = nodes.get(n);
                    const edge = edges.get(network.getConnectedEdges(nodeId).filter(e => {{
                        const ed = edges.get(e);
                        return ed.from === nodeId && ed.to === n || ed.to === nodeId && ed.from === n;
                    }})[0]);
                    const relLabel = edge ? edge.label : '';
                    return '<div class="neighbor"><span style="color:#00CED1">' + nb.label +
                           '</span> <span style="color:#888">(' + relLabel + ')</span></div>';
                }}).join('');
                document.getElementById('infoNeighbors').innerHTML = neighborInfo;
                document.getElementById('infoPanel').classList.add('visible');
            }} else {{
                document.getElementById('infoPanel').classList.remove('visible');
            }}
        }});
    </script>
</body>
</html>
"""


def generate_html(
    store: GraphStore,
    output_path: Optional[Path] = None,
    title: str = "IMA 知识图谱",
) -> Path:
    """生成交互式 HTML 可视化。

    Args:
        store: GraphStore 实例
        output_path: 输出路径（默认 storage/graph.html）
        title: 页面标题

    Returns:
        HTML 文件路径
    """
    output_path = output_path or (store.storage_path / "graph.html")

    # 准备节点数据
    nodes_data = []
    for n, d in store.graph.nodes(data=True):
        ntype = d.get("type", "topic")
        degree = store.graph.degree(n)
        # 节点大小：基于连接数（最小 10，最大 35）
        size = min(35, max(10, 10 + degree * 2))
        nodes_data.append({
            "id": n,
            "label": d.get("label", n),
            "color": {
                "background": NODE_COLORS.get(ntype, "#888888"),
                "border": NODE_COLORS.get(ntype, "#888888"),
                "highlight": {
                    "background": NODE_COLORS.get(ntype, "#888888"),
                    "border": "#FFA500",
                },
            },
            "size": size,
            "title": f"{d.get('label', n)}\n类型: {ntype}\n关联文档: {d.get('doc_count', 0)}\n连接数: {degree}",
        })

    # 准备边数据
    edges_data = []
    for i, (u, v, d) in enumerate(store.graph.edges(data=True)):
        rel = d.get("relation", "")
        edges_data.append({
            "id": f"e{i}",
            "from": u,
            "to": v,
            "label": RELATION_LABELS.get(rel, rel),
            "title": f"{u} → {RELATION_LABELS.get(rel, rel)} → {v}",
        })

    # 统计信息
    s = store.stats()
    stats_str = (
        f"节点 {s['nodes']} · 边 {s['edges']} · "
        f"文档 {s['nodes_by_type'].get('document', 0)} · "
        f"地区 {s['nodes_by_type'].get('region', 0)} · "
        f"机构 {s['nodes_by_type'].get('agency', 0)} · "
        f"主题 {s['nodes_by_type'].get('topic', 0)}"
    )

    # 渲染 HTML
    import json
    html = HTML_TEMPLATE.format(
        stats=stats_str,
        nodes_json=json.dumps(nodes_data, ensure_ascii=False),
        edges_json=json.dumps(edges_data, ensure_ascii=False),
    )

    output_path.write_text(html, encoding="utf-8")
    return output_path

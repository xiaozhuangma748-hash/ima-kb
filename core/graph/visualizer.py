"""知识图谱可视化：生成自包含 HTML（vis.js 力导向图）。

样式特征：
- 白色背景，浅色边
- 节点大小按 degree 对数缩放
- 标签大小跟随 degree
- 边使用 cubicBezier 曲线
- 节点按社区聚类着色（同簇同色相）
"""
from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Optional

from config import settings
from core.graph.store import GraphStore, NODE_COLORS, RELATION_LABELS


# 聚类色相环（HSL 色相，饱和度 70%，亮度 55%）
CLUSTER_HUES = [
    0, 30, 60, 120, 180, 210, 240, 270, 300, 330,
    15, 75, 150, 195, 225, 255, 285, 315,
]


def _cluster_color(cluster_idx: int) -> str:
    """根据聚类索引返回 HSL 颜色字符串。"""
    if cluster_idx < 0:
        return "hsl(0, 0%, 70%)"
    hue = CLUSTER_HUES[cluster_idx % len(CLUSTER_HUES)]
    return f"hsl({hue}, 70%, 55%)"


def _cluster_color_light(cluster_idx: int) -> str:
    """聚类浅色（节点填充）。"""
    if cluster_idx < 0:
        return "hsl(0, 0%, 92%)"
    hue = CLUSTER_HUES[cluster_idx % len(CLUSTER_HUES)]
    return f"hsl({hue}, 50%, 88%)"


HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <title>IMA 知识图谱</title>
    <script src="https://unpkg.com/vis-network/standalone/umd/vis-network.min.js"></script>
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{
            font-family: -apple-system, BlinkMacSystemFont, "PingFang SC", "Segoe UI", sans-serif;
            background: #f8f9fa;
            color: #333;
            height: 100vh;
            display: flex;
            flex-direction: column;
        }}
        .header {{
            background: #fff;
            padding: 16px 24px;
            border-bottom: 1px solid #e9ecef;
            display: flex;
            align-items: baseline;
            gap: 16px;
        }}
        .header h1 {{
            color: #212529;
            font-size: 18px;
            font-weight: 600;
        }}
        .header .stats {{
            color: #868e96;
            font-size: 13px;
        }}
        .container {{
            display: flex;
            flex: 1;
            overflow: hidden;
        }}
        #network {{
            flex: 1;
            background: #f8f9fa;
        }}
        .sidebar {{
            width: 260px;
            background: #fff;
            border-left: 1px solid #e9ecef;
            padding: 16px;
            overflow-y: auto;
        }}
        .sidebar h2 {{
            color: #495057;
            font-size: 12px;
            font-weight: 600;
            margin-bottom: 12px;
            text-transform: uppercase;
            letter-spacing: 0.5px;
        }}
        .legend-item {{
            display: flex;
            align-items: center;
            margin-bottom: 8px;
            font-size: 13px;
            color: #495057;
        }}
        .legend-color {{
            width: 14px;
            height: 14px;
            border-radius: 50%;
            margin-right: 10px;
            display: inline-block;
            border: 1px solid rgba(0,0,0,0.1);
        }}
        .info-panel {{
            margin-top: 20px;
            padding: 12px;
            background: #f8f9fa;
            border-radius: 8px;
            font-size: 12px;
            display: none;
        }}
        .info-panel.visible {{ display: block; }}
        .info-panel h3 {{
            color: #212529;
            margin-bottom: 8px;
            font-size: 14px;
        }}
        .info-panel .neighbor {{
            padding: 4px 0;
            border-bottom: 1px solid #e9ecef;
        }}
        .info-panel .neighbor:last-child {{ border: none; }}
    </style>
</head>
<body>
    <div class="header">
        <h1>IMA 知识图谱</h1>
        <div class="stats">{stats}</div>
    </div>
    <div class="container">
        <div id="network"></div>
        <div class="sidebar">
            <h2>图例</h2>
            <div class="legend-item"><span class="legend-color" style="background:#F59E0B"></span>政策文档</div>
            <div class="legend-item"><span class="legend-color" style="background:#06B6D4"></span>地区</div>
            <div class="legend-item"><span class="legend-color" style="background:#EF4444"></span>机构</div>
            <div class="legend-item"><span class="legend-color" style="background:#8B5CF6"></span>主题</div>

            <div class="info-panel" id="infoPanel">
                <h3 id="infoTitle"></h3>
                <div id="infoNeighbors"></div>
            </div>
        </div>
    </div>

    <script>
        const nodes = new vis.DataSet({nodes_json});
        const edges = new vis.DataSet({edges_json});

        const container = document.getElementById('network');
        const data = {{ nodes: nodes, edges: edges }};
        const options = {{
            nodes: {{
                shape: 'dot',
                borderWidth: 1,
                borderWidthSelected: 2,
                font: {{
                    color: '#333',
                    face: 'PingFang SC, -apple-system, sans-serif',
                }},
            }},
            edges: {{
                color: {{ color: '#ddd', highlight: '#F59E0B', hover: '#aaa' }},
                font: {{
                    color: '#adb5bd',
                    size: 9,
                    strokeWidth: 0,
                    face: 'PingFang SC, sans-serif',
                }},
                arrows: {{ to: {{ enabled: true, scaleFactor: 0.4 }} }},
                smooth: {{ type: 'cubicBezier', forceDirection: 'horizontal', roundness: 0.3 }},
            }},
            physics: {{
                barnesHut: {{
                    gravitationalConstant: -3000,
                    centralGravity: 0.3,
                    springLength: 120,
                    springConstant: 0.04,
                    damping: 0.09,
                }},
                stabilization: {{ iterations: 300 }},
            }},
            interaction: {{
                hover: true,
                tooltipDelay: 200,
                zoomView: true,
                dragView: true,
            }},
        }};

        const network = new vis.Network(container, data, options);

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
                    return '<div class="neighbor"><span style="color:#06B6D4">' + nb.label +
                           '</span> <span style="color:#adb5bd">(' + relLabel + ')</span></div>';
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

    clusters = store.get_clusters()

    # 准备节点数据（对数大小 + 聚类着色 + 动态标签）
    nodes_data = []
    for n, d in store.graph.nodes(data=True):
        ntype = d.get("type", "topic")
        degree = store.graph.degree(n)
        cluster = clusters.get(n, -1)
        size = 8 + math.log(degree + 1) * 12
        font_size = min(24, max(10, 10 + int(math.log(degree + 1) * 5)))
        node_color = _cluster_color(cluster)
        node_bg = _cluster_color_light(cluster)

        nodes_data.append({
            "id": n,
            "label": d.get("label", n),
            "color": {
                "background": node_bg,
                "border": node_color,
                "highlight": {
                    "background": node_bg,
                    "border": "#F59E0B",
                },
                "hover": {
                    "background": node_bg,
                    "border": "#F59E0B",
                },
            },
            "size": size,
            "font": {"size": font_size},
            "title": (
                f"{d.get('label', n)}\n"
                f"类型: {ntype}\n"
                f"关联文档: {d.get('doc_count', 0)}\n"
                f"连接数: {degree}"
            ),
        })

    # 准备边数据（曲线边）
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
    num_clusters = len(set(clusters.values())) if clusters else 0
    stats_str = (
        f"节点 {s['nodes']} · 边 {s['edges']} · "
        f"聚类 {num_clusters} 组 · "
        f"文档 {s['nodes_by_type'].get('document', 0)} · "
        f"地区 {s['nodes_by_type'].get('region', 0)} · "
        f"机构 {s['nodes_by_type'].get('agency', 0)} · "
        f"主题 {s['nodes_by_type'].get('topic', 0)}"
    )

    html = HTML_TEMPLATE.format(
        stats=stats_str,
        nodes_json=json.dumps(nodes_data, ensure_ascii=False),
        edges_json=json.dumps(edges_data, ensure_ascii=False),
    )

    output_path.write_text(html, encoding="utf-8")
    return output_path

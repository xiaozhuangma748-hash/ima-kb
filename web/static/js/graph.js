// 知识图谱 · vis.js
// 样式：白色背景 + 聚类着色 + 曲线边 + 动态标签大小
import { state } from './state.js';
import { escapeHtml, showError } from './utils.js';

// 聚类色相环（与后端 CLUSTER_HUES 保持一致）
const CLUSTER_HUES = [
  0, 30, 60, 120, 180, 210, 240, 270, 300, 330,
  15, 75, 150, 195, 225, 255, 285, 315,
];

function clusterBorder(idx) {
  if (idx < 0) return '#aaa';
  return `hsl(${CLUSTER_HUES[idx % CLUSTER_HUES.length]}, 70%, 55%)`;
}

function clusterBg(idx) {
  if (idx < 0) return '#f0f0f0';
  return `hsl(${CLUSTER_HUES[idx % CLUSTER_HUES.length]}, 50%, 88%)`;
}

// 类型颜色（用于图例和邻居面板）
const TYPE_COLORS = { document: '#F59E0B', region: '#06B6D4', agency: '#EF4444', topic: '#8B5CF6' };

export function loadGraph() {
  fetch('/api/graph/data')
    .then(r => r.json())
    .then(data => {
      const elements = data.elements;
      if (!elements?.nodes?.length) {
        document.getElementById('graph-canvas').innerHTML =
          '<div style="display:flex;align-items:center;justify-content:center;height:100%;color:#868e96">图谱为空，请先构建知识图谱</div>';
        return;
      }

      const nodes = new vis.DataSet(elements.nodes.map(n => {
        const d = n.data || n;
        const cluster = d.cluster ?? -1;
        return {
          id: d.id || n.id,
          label: d.label || n.label,
          color: {
            background: clusterBg(cluster),
            border: clusterBorder(cluster),
            highlight: { background: clusterBg(cluster), border: '#F59E0B' },
            hover: { background: clusterBg(cluster), border: '#F59E0B' },
          },
          size: d.size || 16,
          font: {
            color: '#333',
            size: d.font_size || 12,
            face: 'PingFang SC, -apple-system, sans-serif',
          },
          shape: 'dot',
          borderWidth: 1,
          borderWidthSelected: 2,
          type: d.type,
          title: `${d.label || n.label}\n类型: ${d.type}\n关联文档: ${d.doc_count || 0}\n连接数: ${d.degree || 0}`,
        };
      }));

      const edges = new vis.DataSet((elements.edges || []).map(e => {
        const d = e.data || e;
        return {
          from: d.source || e.source,
          to: d.target || e.target,
          label: d.label || e.label || '',
          arrows: 'to',
          color: { color: '#ddd', highlight: '#F59E0B', hover: '#aaa' },
          font: { color: '#adb5bd', size: 9, strokeWidth: 0 },
          smooth: { type: 'cubicBezier', forceDirection: 'horizontal', roundness: 0.3 },
        };
      }));

      const container = document.getElementById('graph-canvas');
      const network = new vis.Network(container, { nodes, edges }, {
        physics: {
          barnesHut: {
            gravitationalConstant: -3000,
            centralGravity: 0.3,
            springLength: 120,
            springConstant: 0.04,
            damping: 0.09,
          },
          stabilization: { iterations: 300 },
        },
        interaction: { hover: true, tooltipDelay: 200, zoomView: true, dragView: true },
      });

      // 点击节点查看邻居
      network.on('click', function(params) {
        const detailPanel = document.getElementById('graph-node-detail');
        const statsPanel = document.getElementById('graph-stats-panel');

        if (params.nodes.length) {
          const nodeId = params.nodes[0];
          const nodeData = nodes.get(nodeId);

          // 填充节点详情
          document.getElementById('detail-name').textContent = nodeData.label;
          document.getElementById('detail-type').textContent = nodeData.type || '';
          document.getElementById('detail-degree').textContent = nodeData.degree || 0;
          document.getElementById('detail-docs').textContent = nodeData.doc_count || 0;

          // 切换面板
          detailPanel.style.display = 'block';
          statsPanel.style.display = 'none';

          // 加载邻居
          fetch(`/api/graph/neighbors/${encodeURIComponent(nodeId)}`)
            .then(r => r.json())
            .then(nd => {
              const div = document.getElementById('graph-neighbors');
              if (nd.found && nd.neighbors && nd.neighbors.length) {
                div.innerHTML = nd.neighbors.map(n =>
                  `<div class="neighbor-item">` +
                  `<span class="neighbor-name" style="color:${TYPE_COLORS[n.type] || '#06B6D4'}">${escapeHtml(n.node)}</span>` +
                  `<span class="neighbor-rel">${escapeHtml(n.relation_label || '')}</span></div>`
                ).join('');
              } else {
                div.innerHTML = '<div class="empty-hint">无邻居节点</div>';
              }
            });
        } else {
          // 点击空白处，恢复概览面板
          detailPanel.style.display = 'none';
          statsPanel.style.display = 'block';
        }
      });

      state.graphNetwork = network;
    });
}

// 图谱统计更新
export function loadGraphStats() {
  fetch('/api/stats').then(r => r.json()).then(data => {
    document.getElementById('graph-node-count').textContent = data.graph_nodes;
    document.getElementById('graph-edge-count').textContent = data.graph_edges;
  });
}

export function initGraph() {
  // 重建图谱
  document.getElementById('btn-rebuild-graph')?.addEventListener('click', () => {
    if (!confirm('确定重建知识图谱？这将调用 LLM 重新抽取实体关系。')) return;
    fetch('/api/graph/build', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ force: true }),
    }).then(r => r.json()).then(data => {
      alert(`构建完成: 处理 ${data.processed} 个文档`);
      loadGraph();
      loadGraphStats();
    }).catch(err => {
      console.error('图谱构建失败:', err);
      showError('graph-canvas', err.message);
    });
  });
}

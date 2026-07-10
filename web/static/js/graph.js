// 知识图谱 · vis.js
import { state } from './state.js';
import { escapeHtml, showError } from './utils.js';

export function loadGraph() {
  fetch('/api/graph/data')
    .then(r => r.json())
    .then(data => {
      const elements = data.elements;
      if (!elements?.nodes?.length) {
        document.getElementById('graph-canvas').innerHTML =
          '<div style="display:flex;align-items:center;justify-content:center;height:100%;color:var(--text-muted)">图谱为空，请先构建知识图谱</div>';
        return;
      }

      // 颜色映射
      const colorMap = { document: '#F59E0B', region: '#06B6D4', agency: '#EF4444', topic: '#8B5CF6' };

      const nodes = new vis.DataSet(elements.nodes.map(n => ({
        id: n.data?.id || n.id,
        label: n.data?.label || n.label,
        color: { background: (colorMap[n.data?.type] || '#999') + '20', border: colorMap[n.data?.type] || '#999' },
        font: { color: colorMap[n.data?.type] || '#333', size: 12 },
        shape: 'box',
        type: n.data?.type,
      })));

      const edges = new vis.DataSet((elements.edges || []).map(e => ({
        from: e.data?.source || e.source,
        to: e.data?.target || e.target,
        label: e.data?.label || e.label || '',
        arrows: 'to',
      })));

      const container = document.getElementById('graph-canvas');
      const network = new vis.Network(container, { nodes, edges }, {
        physics: { solver: 'forceAtlas2Based' },
        interaction: { hover: true, tooltipDelay: 200 },
      });

      // 点击节点查看邻居
      network.on('click', function(params) {
        if (params.nodes.length) {
          const nodeId = params.nodes[0];
          fetch(`/api/graph/neighbors/${encodeURIComponent(nodeId)}`)
            .then(r => r.json())
            .then(nd => {
              const div = document.getElementById('graph-neighbors');
              if (nd.found && nd.neighbors) {
                div.innerHTML = nd.neighbors.map(n =>
                  `<div>→ <span style="color:${colorMap[n.type] || 'var(--accent-cyan)'}">${escapeHtml(n.node)}</span> (${escapeHtml(n.relation_label)})</div>`
                ).join('');
              } else {
                div.innerHTML = '<div style="color:var(--text-muted)">未找到邻居</div>';
              }
            });
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

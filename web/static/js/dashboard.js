// 仪表盘
import { escapeHtml } from './utils.js';

export function loadDashboard() {
  fetch('/api/stats')
    .then(r => r.json())
    .then(data => {
      document.getElementById('dash-documents').textContent = data.documents;
      document.getElementById('dash-chunks').textContent = data.chunks;
      document.getElementById('dash-tags').textContent = data.tags_count;
      document.getElementById('dash-graph').textContent = data.graph_nodes;

      // 标签分布
      const chartDiv = document.getElementById('tag-chart');
      if (chartDiv && data.top_tags) {
        const maxCount = Math.max(...data.top_tags.map(t => t.count), 1);
        chartDiv.innerHTML = data.top_tags.map(t => {
          // 标签名截断
          const labelName = t.name.length > 4 ? t.name.slice(0, 4) + '...' : t.name;
          return `<div class="chart-bar" style="height:${(t.count/maxCount*100).toFixed(0)}%" data-label="${escapeHtml(labelName)}"></div>`;
        }).join('');
      }

      // 告警
      const alertsDiv = document.getElementById('alerts-list');
      if (alertsDiv && data.alerts) {
        alertsDiv.innerHTML = data.alerts.map(a =>
          `<div class="alert-item ${a.severity}"><strong>${a.severity === 'error' ? '❌' : '⚠️'} ${a.severity}</strong><br>${escapeHtml(a.message)}</div>`
        ).join('');
      }

      // 最近文档
      const recentDiv = document.getElementById('recent-docs');
      if (recentDiv && data.recent_docs) {
        recentDiv.innerHTML = data.recent_docs.map(d =>
          `<tr><td>${escapeHtml(d.title)}</td><td>${escapeHtml(d.file_type)}</td><td>${(d.tags||[]).map(t=>`<span class="tag tag-orange">${escapeHtml(t)}</span>`).join(' ')}</td><td>${d.chunk_count}</td><td>${d.created_at}</td></tr>`
        ).join('');
      }
    });
}

export function initDashboard() {
  // 刷新按钮（替代原 onclick="loadDashboard()"）
  document.getElementById('btn-refresh-dashboard')?.addEventListener('click', loadDashboard);
}

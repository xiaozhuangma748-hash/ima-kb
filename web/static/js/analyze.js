// 数据分析
import { showError } from './utils.js';

export function renderAnalyze(data) {
  const container = document.getElementById('analyze-content');
  const sheetTabs = data.sheets?.map((s, i) =>
    `<div class="sheet-tab ${i===0 ? 'active' : ''}" onclick="switchSheet('${s}')">${s}</div>`
  ).join('') || '';

  const statsHtml = (data.columns || []).map(col => `
    <div class="stat-card">
      <div class="stat-header">
        <div class="stat-name">${col.name}</div>
        <div class="stat-type">${col.dtype}</div>
      </div>
      <div class="stat-rows">
        ${Object.entries(col).filter(([k]) => !['name','dtype','top_values'].includes(k)).map(([k,v]) => `<div><span class="label">${k}</span>${v}</div>`).join('')}
      </div>
    </div>
  `).join('');

  const tableHeaders = data.columns?.map(c => `<th>${c.name}</th>`).join('') || '';
  const tableRows = (data.preview_rows || []).map(row =>
    `<tr>${data.columns?.map(c => `<td>${row[c.name] ?? ''}</td>`).join('')}</tr>`
  ).join('');

  container.innerHTML = `
    ${sheetTabs ? `<div class="sheet-tabs">${sheetTabs}</div>` : ''}
    <div class="stats-grid">${statsHtml}</div>
    ${tableRows ? `<div class="card" style="margin-top:16px">
      <div class="card-title" style="margin-bottom:12px">数据预览</div>
      <div class="data-table"><table><thead><tr>${tableHeaders}</tr></thead><tbody>${tableRows}</tbody></table></div>
    </div>` : ''}
    ${data.ai_insight ? `<div class="card" style="margin-top:16px;border-left:3px solid var(--accent-cyan)">
      <div class="card-title" style="margin-bottom:12px;color:var(--accent-cyan)">🤖 AI 解读</div>
      <div style="font-size:13px;line-height:1.8;color:var(--text-secondary)">${data.ai_insight}</div>
    </div>` : ''}
  `;

  // 存储缓存 key 用于导出
  container.dataset.cacheKey = data.cache_key;
}

export function initAnalyze() {
  document.getElementById('btn-analyze')?.addEventListener('click', () => {
    const fileInput = document.getElementById('analyze-file');
    const file = fileInput?.files?.[0];
    if (!file) return alert('请先选择文件');

    const formData = new FormData();
    formData.append('file', file);

    const container = document.getElementById('analyze-content');
    container.innerHTML = '<div style="text-align:center;color:var(--text-muted);padding:40px">分析中...</div>';

    fetch('/api/analyze?ai_insight=true', { method: 'POST', body: formData })
      .then(r => r.json())
      .then(data => {
        renderAnalyze(data);
      })
      .catch(err => {
        console.error('分析失败:', err);
        showError('analyze-content', err.message);
      });
  });

  // 选择文件按钮（替代原 onclick="document.getElementById('analyze-file').click()"）
  document.getElementById('btn-analyze-file')?.addEventListener('click', () => {
    document.getElementById('analyze-file')?.click();
  });
}

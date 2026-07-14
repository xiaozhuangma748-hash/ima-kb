// 数据分析
import { showError, showToast, formatSize, escapeHtml } from './utils.js';

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

  const summaryCard = `
    <div class="card analyze-summary-card" style="margin-bottom:16px;border-left:3px solid var(--accent-orange)">
      <div class="analyze-summary-row">
        <div class="analyze-summary-main">
          <div class="analyze-summary-name">${escapeHtml(data.filename || '未命名文件')}</div>
          <div class="analyze-summary-meta">
            ${data.current_sheet ? `<span class="tag tag-cyan">Sheet: ${escapeHtml(data.current_sheet)}</span>` : ''}
            <span class="tag">${data.rows || 0} 行 × ${data.cols || 0} 列</span>
            <span class="tag tag-success">分析完成</span>
          </div>
        </div>
        <button class="btn btn-sm" id="btn-export-analysis" data-cache-key="${escapeHtml(data.cache_key || '')}">导出报告</button>
      </div>
    </div>
  `;

  container.innerHTML = `
    ${summaryCard}
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

  document.getElementById('btn-export-analysis')?.addEventListener('click', () => {
    const key = data.cache_key;
    if (!key) return;
    window.open(`/api/analyze/export?key=${encodeURIComponent(key)}`, '_blank');
  });

  // 存储缓存 key 用于导出
  container.dataset.cacheKey = data.cache_key;
}

function getAnalyzeFileInfo() {
  let info = document.getElementById('analyze-file-info');
  if (!info) {
    const page = document.getElementById('page-analyze');
    const header = page?.querySelector('.page-header');
    if (!page || !header) return null;
    info = document.createElement('div');
    info.id = 'analyze-file-info';
    info.className = 'analyze-file-info';
    header.after(info);
  }
  return info;
}

export function initAnalyze() {
  const fileInput = document.getElementById('analyze-file');
  const analyzeBtn = document.getElementById('btn-analyze');
  const fileBtn = document.getElementById('btn-analyze-file');

  // 选择文件按钮
  fileBtn?.addEventListener('click', () => {
    fileInput?.click();
  });

  // 显示已选文件信息
  fileInput?.addEventListener('change', (e) => {
    const file = e.target.files?.[0];
    const info = getAnalyzeFileInfo();
    if (!info) return;
    if (!file) {
      info.innerHTML = '';
      info.style.display = 'none';
      return;
    }
    info.style.display = 'block';
    info.innerHTML = `
      <div class="analyze-file-icon">📄</div>
      <div class="analyze-file-main">
        <div class="analyze-file-name">${escapeHtml(file.name)}</div>
        <div class="analyze-file-meta">大小 ${formatSize(file.size)} · 等待分析</div>
      </div>
    `;
  });

  analyzeBtn?.addEventListener('click', () => {
    const file = fileInput?.files?.[0];
    if (!file) {
      showToast('请先选择文件', 'error', 2500);
      return;
    }

    analyzeBtn.disabled = true;
    if (fileBtn) fileBtn.disabled = true;

    const info = getAnalyzeFileInfo();
    if (info) {
      info.style.display = 'block';
      info.innerHTML = `
        <div class="analyze-file-icon">📄</div>
        <div class="analyze-file-main">
          <div class="analyze-file-name">${escapeHtml(file.name)}</div>
          <div class="analyze-file-meta">分析中，请稍候...</div>
        </div>
      `;
    }

    const container = document.getElementById('analyze-content');
    container.innerHTML = `
      <div class="analyze-loading">
        <div class="analyze-loading-spinner"></div>
        <div class="analyze-loading-text">正在分析数据...</div>
      </div>
    `;

    const formData = new FormData();
    formData.append('file', file);

    fetch('/api/analyze?ai_insight=true', { method: 'POST', body: formData })
      .then(async r => {
        const data = await r.json();
        if (!r.ok) {
          throw new Error(data.detail || '分析失败');
        }
        renderAnalyze(data);
        showToast(`分析完成：${data.filename || file.name}`, 'success');
        if (info) {
          info.innerHTML = `
            <div class="analyze-file-icon analyze-file-icon-success">✓</div>
            <div class="analyze-file-main">
              <div class="analyze-file-name">${escapeHtml(data.filename || file.name)}</div>
              <div class="analyze-file-meta">${data.rows || 0} 行 × ${data.cols || 0} 列 · 分析完成</div>
            </div>
          `;
        }
      })
      .catch(err => {
        console.error('分析失败:', err);
        container.innerHTML = `
          <div class="card empty-card">
            <div class="empty-icon">⚠️</div>
            <div style="color:var(--accent-red)">分析失败：${escapeHtml(err.message)}</div>
          </div>
        `;
        showToast(`分析失败：${err.message}`, 'error');
        if (info) {
          info.innerHTML = `
            <div class="analyze-file-icon analyze-file-icon-error">✗</div>
            <div class="analyze-file-main">
              <div class="analyze-file-name">${escapeHtml(file.name)}</div>
              <div class="analyze-file-meta" style="color:var(--accent-red)">分析失败：${escapeHtml(err.message)}</div>
            </div>
          `;
        }
      })
      .finally(() => {
        analyzeBtn.disabled = false;
        if (fileBtn) fileBtn.disabled = false;
      });
  });
}

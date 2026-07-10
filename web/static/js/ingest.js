// 文档入库
import { loadDashboard } from './dashboard.js';
import { escapeHtml, formatSize, showError } from './utils.js';

export function handleFiles(files) {
  if (!files.length) return;
  const queue = document.getElementById('upload-queue');
  const formData = new FormData();
  for (const f of files) {
    formData.append('files', f);
    // 占位项
    const div = document.createElement('div');
    div.className = 'upload-item';
    div.innerHTML = `<div class="file-icon">...</div><div class="file-info"><div class="file-name">${escapeHtml(f.name)}</div><div class="file-meta">${formatSize(f.size)}</div><div class="progress-bar"><div class="progress-fill" style="width: 20%"></div></div></div><div class="file-status status-processing">⏳ 上传中...</div>`;
    div.dataset.filename = f.name;
    queue.appendChild(div);
  }

  fetch('/api/ingest/upload', { method: 'POST', body: formData })
    .then(r => r.json())
    .then(data => {
      let hasSuccess = false;
      for (const r of data.results || []) {
        const item = queue.querySelector(`[data-filename="${r.filename}"]`);
        if (!item) continue;
        if (r.status === 'success') {
          hasSuccess = true;
          item.querySelector('.progress-fill').style.width = '100%';
          item.querySelector('.file-status').className = 'file-status status-success';
          item.querySelector('.file-status').textContent = r.tags?.length ? '✓ ' + r.tags.join(', ') : '✓ 已入库';
        } else {
          item.querySelector('.file-status').className = 'file-status';
          item.querySelector('.file-status').textContent = '✗ ' + (r.error || '失败');
        }
      }
      // 文件上传成功后刷新仪表盘统计
      if (hasSuccess) loadDashboard();
    })
    .catch(err => {
      console.error('上传失败:', err);
      showError('upload-queue', err.message);
    });
}

export function initIngest() {
  const dropzone = document.getElementById('dropzone');
  const fileInput = document.getElementById('file-input');

  if (dropzone) {
    dropzone.addEventListener('click', () => fileInput.click());
    dropzone.addEventListener('dragover', (e) => { e.preventDefault(); dropzone.style.borderColor = 'var(--accent-orange)'; });
    dropzone.addEventListener('dragleave', () => { dropzone.style.borderColor = ''; });
    dropzone.addEventListener('drop', (e) => {
      e.preventDefault();
      dropzone.style.borderColor = '';
      handleFiles(e.dataTransfer.files);
    });
  }

  if (fileInput) {
    fileInput.addEventListener('change', () => handleFiles(fileInput.files));
  }

  // URL 入库
  document.getElementById('btn-url-ingest')?.addEventListener('click', () => {
    const url = document.getElementById('input-url')?.value?.trim();
    if (!url) return;
    fetch('/api/ingest/url', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ url }),
    }).then(r => r.json()).then(data => {
      if (data.status === 'success') {
        alert(`入库成功: ${data.title}`);
        loadDashboard();  // URL 入库成功后刷新统计
      } else {
        alert(`失败: ${data.error || '未知错误'}`);
      }
    }).catch(err => {
      console.error('URL 入库失败:', err);
      showError('upload-queue', err.message);
    });
  });

  // 入库 Tab 切换（文件/URL/剪贴板）
  document.querySelectorAll('.ingest-tab, .sheet-tab').forEach(tab => {
    tab.addEventListener('click', function() {
      const cls = this.classList[0];
      this.parentElement.querySelectorAll('.' + cls).forEach(s => s.classList.remove('active'));
      this.classList.add('active');
      // ingest tab 面板切换
      if (cls === 'ingest-tab') {
        const tabs = Array.from(this.parentElement.querySelectorAll('.ingest-tab'));
        const idx = tabs.indexOf(this);
        document.querySelectorAll('.ingest-panel').forEach((p, i) => {
          p.style.display = i === idx ? '' : 'none';
        });
      }
    });
  });
}

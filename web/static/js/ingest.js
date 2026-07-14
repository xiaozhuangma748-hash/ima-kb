// 文档入库 — 完整状态机 + Toast 通知 + 队列管理
import { loadDashboard } from './dashboard.js';
import { escapeHtml, formatSize, showToast } from './utils.js';

// ============ 队列管理 ============
function hideEmptyHint() {
  const empty = document.getElementById('queue-empty');
  if (empty) empty.style.display = 'none';
}

function addQueueItem(filename, size, source = 'file') {
  hideEmptyHint();
  const queue = document.getElementById('upload-queue');
  const id = `q-${Date.now()}-${Math.random().toString(36).slice(2, 6)}`;
  const div = document.createElement('div');
  div.className = 'upload-item item-processing';
  div.id = id;
  div.dataset.filename = filename;
  const iconText = filename.split('.').pop().slice(0, 4).toUpperCase();
  const sizeText = size > 0 ? formatSize(size) : source === 'url' ? '网页' : source === 'clip' ? '文本' : '';
  div.innerHTML = `
    <div class="file-icon">${escapeHtml(iconText)}</div>
    <div class="file-info">
      <div class="file-name">${escapeHtml(filename)}</div>
      <div class="file-meta"><span>${sizeText}</span><span class="tag-mini">解析中</span></div>
      <div class="progress-bar"><div class="progress-fill" style="width:30%"></div></div>
    </div>
    <div class="file-status status-processing">处理中</div>
  `;
  queue.appendChild(div);
  return id;
}

function updateQueueItem(id, result) {
  const item = document.getElementById(id);
  if (!item) return;

  const status = result.status;
  const icon = item.querySelector('.file-icon');
  const fill = item.querySelector('.progress-fill');
  const statusEl = item.querySelector('.file-status');
  const metaEl = item.querySelector('.file-meta');

  if (status === 'success') {
    item.className = 'upload-item item-success';
    icon.className = 'file-icon icon-success';
    icon.textContent = 'OK';
    fill.className = 'progress-fill fill-success';
    fill.style.width = '100%';
    statusEl.className = 'file-status status-success';
    statusEl.textContent = '已入库';
    const tags = result.tags || [];
    const chunks = result.chunks || 0;
    const tokens = result.tokens || 0;
    let metaHtml = `<span>${chunks} 块</span><span>${tokens} tokens</span>`;
    if (tags.length) {
      metaHtml += tags.slice(0, 3).map(t => `<span class="tag-mini">${escapeHtml(t)}</span>`).join('');
      if (tags.length > 3) metaHtml += `<span class="tag-mini">+${tags.length - 3}</span>`;
    }
    metaEl.innerHTML = metaHtml;
  } else if (status === 'skipped') {
    item.className = 'upload-item item-skipped';
    icon.className = 'file-icon icon-skipped';
    icon.textContent = '--';
    fill.className = 'progress-fill fill-skipped';
    fill.style.width = '100%';
    statusEl.className = 'file-status status-skipped';
    statusEl.textContent = '跳过';
    metaEl.innerHTML = `<span>${escapeHtml(result.error || '已存在')}</span>`;
  } else {
    item.className = 'upload-item item-failed';
    icon.className = 'file-icon icon-failed';
    icon.textContent = '!';
    fill.className = 'progress-fill fill-failed';
    fill.style.width = '100%';
    statusEl.className = 'file-status status-failed';
    statusEl.textContent = '失败';
    metaEl.innerHTML = `<span>${escapeHtml(result.error || '未知错误')}</span>`;
  }
}

// ============ 文件上传 ============
export function handleFiles(files) {
  if (!files.length) return;
  const formData = new FormData();
  const itemIds = [];
  for (const f of files) {
    formData.append('files', f);
    const id = addQueueItem(f.name, f.size, 'file');
    itemIds.push({ id, name: f.name });
  }

  showToast(`正在上传 ${files.length} 个文件...`, 'info', 2000);

  fetch('/api/ingest/upload', { method: 'POST', body: formData })
    .then(r => r.json())
    .then(data => {
      const results = data.results || [];
      let successCount = 0, skipCount = 0, failCount = 0;

      // 按文件名匹配（后端已返回原始文件名）
      for (const r of results) {
        const matched = itemIds.find(it => it.name === r.filename);
        if (matched) {
          updateQueueItem(matched.id, r);
        } else {
          // 没匹配上，直接加到队列末尾
          const id = addQueueItem(r.filename, 0, 'file');
          updateQueueItem(id, r);
        }
        if (r.status === 'success') successCount++;
        else if (r.status === 'skipped') skipCount++;
        else failCount++;
      }

      // Toast 汇总
      if (successCount > 0) {
        showToast(`成功入库 ${successCount} 个文档`, 'success');
        loadDashboard();
        refreshSideStats();
      }
      if (skipCount > 0) {
        showToast(`${skipCount} 个文件被跳过（重复或不支持）`, 'info');
      }
      if (failCount > 0) {
        showToast(`${failCount} 个文件入库失败`, 'error');
      }
    })
    .catch(err => {
      console.error('上传失败:', err);
      itemIds.forEach(it => {
        updateQueueItem(it.id, { status: 'failed', error: '网络错误' });
      });
      showToast('上传失败：网络错误', 'error');
    });
}

// ============ URL 入库 ============
function handleUrlIngest() {
  const url = document.getElementById('input-url')?.value?.trim();
  if (!url) {
    showToast('请输入 URL', 'error', 2000);
    return;
  }
  const btn = document.getElementById('btn-url-ingest');
  const originalText = btn.textContent;
  btn.disabled = true;
  btn.textContent = '抓取中...';

  const id = addQueueItem(url, 0, 'url');

  fetch('/api/ingest/url', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ url }),
  })
    .then(r => r.json())
    .then(data => {
      updateQueueItem(id, data);
      if (data.status === 'success') {
        showToast(`入库成功: ${data.title}`, 'success');
        loadDashboard();
        refreshSideStats();
      } else if (data.status === 'skipped') {
        showToast(`已跳过: ${data.error || '重复内容'}`, 'info');
      } else {
        showToast(`入库失败: ${data.error || '未知错误'}`, 'error');
      }
      document.getElementById('input-url').value = '';
    })
    .catch(err => {
      console.error('URL 入库失败:', err);
      updateQueueItem(id, { status: 'failed', error: '网络错误' });
      showToast('URL 入库失败：网络错误', 'error');
    })
    .finally(() => {
      btn.disabled = false;
      btn.textContent = originalText;
    });
}

// ============ 手动录入入库 ============
function updateClipCounter() {
  const textarea = document.getElementById('input-clip-content');
  const counter = document.getElementById('clip-counter');
  if (textarea && counter) {
    const len = textarea.value.length;
    counter.textContent = `${len} 字`;
  }
}

function resetClipForm() {
  const textarea = document.getElementById('input-clip-content');
  const titleInput = document.getElementById('input-clip-title');
  if (textarea) textarea.value = '';
  if (titleInput) titleInput.value = '';
  updateClipCounter();
}

function handleClipIngest() {
  const textarea = document.getElementById('input-clip-content');
  const titleInput = document.getElementById('input-clip-title');
  const content = textarea?.value?.trim() || '';
  const title = titleInput?.value?.trim() || '';
  console.log('[IMA] handleClipIngest 触发, 内容长度:', content.length);
  if (!content) {
    showToast('请输入内容', 'error', 2000);
    return;
  }
  const btn = document.getElementById('btn-clip-ingest');
  const originalText = btn.textContent;
  btn.disabled = true;
  btn.textContent = '入库中...';

  const displayName = title || `手动录入_${content.slice(0, 20)}...`;
  const id = addQueueItem(displayName, content.length, 'clip');

  fetch('/api/ingest/clip', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ title, content }),
  })
    .then(r => r.json())
    .then(data => {
      updateQueueItem(id, data);
      if (data.status === 'success') {
        showToast(`入库成功: ${data.title}`, 'success');
        loadDashboard();
        refreshSideStats();
        resetClipForm();
      } else if (data.status === 'skipped') {
        showToast(`已跳过: ${data.error || '重复内容'}`, 'info');
      } else {
        showToast(`入库失败: ${data.error || '未知错误'}`, 'error');
      }
    })
    .catch(err => {
      console.error('手动录入入库失败:', err);
      updateQueueItem(id, { status: 'failed', error: '网络错误' });
      showToast('手动录入入库失败：网络错误', 'error');
    })
    .finally(() => {
      btn.disabled = false;
      btn.textContent = originalText;
    });
}

// ============ 刷新侧边栏统计 ============
function refreshSideStats() {
  fetch('/api/stats')
    .then(r => r.json())
    .then(data => {
      const set = (id, val) => { const el = document.getElementById(id); if (el) el.textContent = val; };
      set('side-stat-docs', data.documents ?? '');
      set('side-stat-chunks', data.chunks ?? '');
      set('side-stat-tokens', data.total_tokens ?? '');
    })
    .catch(() => {});
}

// ============ 初始化 ============
export function initIngest() {
  console.log('[IMA] ingest.js v3 初始化');
  const dropzone = document.getElementById('dropzone');
  const fileInput = document.getElementById('file-input');

  if (dropzone) {
    dropzone.addEventListener('click', () => fileInput.click());
    dropzone.addEventListener('dragover', (e) => {
      e.preventDefault();
      dropzone.classList.add('dragging');
    });
    dropzone.addEventListener('dragleave', () => dropzone.classList.remove('dragging'));
    dropzone.addEventListener('drop', (e) => {
      e.preventDefault();
      dropzone.classList.remove('dragging');
      handleFiles(e.dataTransfer.files);
    });
  }

  if (fileInput) {
    fileInput.addEventListener('change', () => {
      handleFiles(fileInput.files);
      fileInput.value = '';  // 允许重复选择同一文件
    });
  }

  // URL 入库
  document.getElementById('btn-url-ingest')?.addEventListener('click', handleUrlIngest);
  document.getElementById('input-url')?.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') handleUrlIngest();
  });

  // 手动录入入库
  const clipBtn = document.getElementById('btn-clip-ingest');
  const clipTextarea = document.getElementById('input-clip-content');
  const clipResetBtn = document.getElementById('btn-clip-reset');

  if (clipTextarea) {
    clipTextarea.addEventListener('input', updateClipCounter);
    clipTextarea.addEventListener('paste', () => {
      // 粘贴后 DOM 更新有延迟，延迟更新字数
      setTimeout(updateClipCounter, 0);
    });
    updateClipCounter();
  }

  if (clipResetBtn) {
    clipResetBtn.addEventListener('click', (e) => {
      e.preventDefault();
      resetClipForm();
    });
  }

  if (clipBtn) {
    clipBtn.addEventListener('click', (e) => {
      e.preventDefault();
      e.stopPropagation();
      handleClipIngest();
    });
    console.log('[IMA] 手动录入入库按钮已绑定:', clipBtn);
  } else {
    console.warn('[IMA] 未找到手动录入入库按钮');
  }

  // Tab 切换
  document.querySelectorAll('.ingest-tab').forEach(tab => {
    tab.addEventListener('click', function() {
      const target = this.dataset.tab;
      if (!target) return;
      document.querySelectorAll('.ingest-tab').forEach(t => t.classList.remove('active'));
      this.classList.add('active');
      document.querySelectorAll('.ingest-panel').forEach(p => p.style.display = 'none');
      const panel = document.getElementById(`panel-${target}`);
      if (panel) panel.style.display = '';
    });
  });

  // 清空队列
  document.getElementById('btn-clear-queue')?.addEventListener('click', () => {
    const queue = document.getElementById('upload-queue');
    // 只清空已完成/跳过/失败的，保留处理中的
    const removable = queue.querySelectorAll('.item-success, .item-failed, .item-skipped');
    if (removable.length === 0) {
      showToast('没有可清空的记录', 'info', 2000);
      return;
    }
    removable.forEach(el => el.remove());
    // 如果队列空了，显示空提示
    if (!queue.querySelector('.upload-item')) {
      const empty = document.getElementById('queue-empty');
      if (empty) empty.style.display = '';
    }
    showToast(`已清空 ${removable.length} 条记录`, 'info', 2000);
  });
}

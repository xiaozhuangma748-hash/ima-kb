// IMA Web 后台 · 前端交互
// ============================

// 导航切换
const navItems = document.querySelectorAll('.nav-item[data-page]');
const pages = document.querySelectorAll('.page');
const breadcrumb = document.getElementById('breadcrumb-current');
const pageNames = {
  qa: 'AI 问答', ingest: '文档入库', search: '搜索',
  analyze: '数据分析', dashboard: '仪表盘', graph: '知识图谱', pet: '宠物管理'
};

navItems.forEach(item => {
  item.addEventListener('click', () => {
    const target = item.dataset.page;
    navItems.forEach(n => n.classList.remove('active'));
    item.classList.add('active');
    pages.forEach(p => p.classList.remove('active'));
    document.getElementById('page-' + target).classList.add('active');
    breadcrumb.textContent = pageNames[target];

    // 按需加载数据
    if (target === 'dashboard') loadDashboard();
    if (target === 'graph') loadGraph();
    if (target === 'pet') loadPet();
  });
});

// 人格切换
document.querySelectorAll('.persona-chip').forEach(chip => {
  chip.addEventListener('click', () => {
    document.querySelectorAll('.persona-chip').forEach(c => c.classList.remove('active'));
    chip.classList.add('active');
  });
});

// 开关切换
document.querySelectorAll('.toggle').forEach(t => {
  t.addEventListener('click', () => t.classList.toggle('on'));
});

// Tab 切换
document.querySelectorAll('.ingest-tab, .sheet-tab').forEach(tab => {
  tab.addEventListener('click', function() {
    const cls = this.classList[0];
    this.parentElement.querySelectorAll('.' + cls).forEach(s => s.classList.remove('active'));
    this.classList.add('active');
  });
});

// 清空对话
document.getElementById('btn-clear-chat')?.addEventListener('click', () => {
  const chatArea = document.getElementById('chat-messages');
  chatArea.innerHTML = `
    <div class="chat-empty">
      <div class="qa-hero-title">今天有什么想了解的？</div>
      <div class="qa-suggestions">
        <div class="qa-suggestion" onclick="setQuestion('骨灰安置有哪些生态安葬方式？')">骨灰安置有哪些生态安葬方式？</div>
        <div class="qa-suggestion" onclick="setQuestion('殡葬服务收费标准是什么？')">殡葬服务收费标准是什么？</div>
        <div class="qa-suggestion" onclick="setQuestion('杭州市殡葬改革最新政策？')">杭州市殡葬改革最新政策？</div>
      </div>
    </div>
  `;
  chatArea.classList.add('empty');
  const sourcesPanel = document.getElementById('sources-panel');
  if (sourcesPanel) sourcesPanel.innerHTML = '<div style="font-size:12px;color:var(--text-muted);text-align:center;padding:20px">等待 AI 回答...</div>';
});

// ===== AI 问答 · SSE 流式 =====
const chatSend = document.getElementById('chat-send');
const chatInput = document.getElementById('chat-textarea');
const chatMessages = document.getElementById('chat-messages');
const sourcesPanel = document.getElementById('sources-panel');
const qaLayout = document.getElementById('qa-layout');
const qaSidebar = document.getElementById('qa-sidebar');
const sidebarToggle = document.getElementById('sidebar-toggle');

function setSidebarCollapsed(collapsed) {
  if (!qaLayout || !qaSidebar || !sidebarToggle) return;
  qaSidebar.classList.toggle('collapsed', collapsed);
  qaLayout.classList.toggle('collapsed-sidebar', collapsed);
  sidebarToggle.textContent = collapsed ? '▶' : '◀';
  sidebarToggle.title = collapsed ? '展开引用来源' : '折叠引用来源';
}

if (sidebarToggle && qaLayout && qaSidebar) {
  sidebarToggle.addEventListener('click', () => {
    setSidebarCollapsed(!qaSidebar.classList.contains('collapsed'));
  });
}

if (chatSend) {
  chatSend.addEventListener('click', sendMessage);
}
if (chatInput) {
  chatInput.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) {
      e.preventDefault();
      sendMessage();
    }
  });
}

function setQuestion(text) {
  const textarea = document.getElementById('chat-textarea');
  if (textarea) {
    textarea.value = text;
    textarea.focus();
  }
  sendMessage();
}

function sendMessage() {
  const text = chatInput.value.trim();
  if (!text) return;

  // 添加用户消息
  appendMessage('user', text);
  chatInput.value = '';

  // 重置引用面板
  if (sourcesPanel) sourcesPanel.innerHTML = '<div style="font-size:12px;color:var(--text-muted);text-align:center;padding:20px">正在检索...</div>';

  // 添加 AI 占位
  const aiMsg = appendMessage('ai', '', true);

  // 获取人格
  const personaChip = document.querySelector('.persona-input-bar .persona-chip.active');
  const persona = personaChip ? (personaChip.dataset.persona || 'auto') : 'auto';

  // SSE 流式请求
  const params = new URLSearchParams({ q: text, persona });
  const url = '/api/qa/stream?' + params.toString();

  fetch(url).then(resp => {
    const reader = resp.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';

    function process() {
      reader.read().then(({ done, value }) => {
        if (done) return;
        buffer += decoder.decode(value, { stream: true });

        // 解析 SSE 事件
        while (buffer.includes('\n\n')) {
          const idx = buffer.indexOf('\n\n');
          const block = buffer.slice(0, idx);
          buffer = buffer.slice(idx + 2);

          const lines = block.split('\n');
          let event = 'message', data = '';
          for (const line of lines) {
            if (line.startsWith('event: ')) event = line.slice(7);
            else if (line.startsWith('data: ')) data = line.slice(6);
          }
          if (!data) continue;

          try {
            const parsed = JSON.parse(data);
            if (event === 'token') {
              const contentEl = aiMsg.querySelector('.msg-content');
              contentEl.textContent += parsed.text;
            } else if (event === 'citation') {
              addSource(parsed);
            } else if (event === 'done') {
              aiMsg.classList.remove('msg-streaming');
              // Markdown 渲染 + 引用编号可点击
              const contentEl = aiMsg.querySelector('.msg-content');
              let html = marked.parse(contentEl.textContent);
              html = html.replace(/\[(\d+)\]\(?(?!\w)/g, (_, n) =>
                `<span class="citation" data-marker="[${n}]" style="cursor:pointer">[${n}]</span>`
              );
              contentEl.innerHTML = html;
            } else if (event === 'error') {
              const contentEl = aiMsg.querySelector('.msg-content');
              contentEl.textContent = '错误: ' + parsed.message;
              aiMsg.classList.remove('msg-streaming');
            }
          } catch (e) {}
        }
        process();
      });
    }
    process();
  }).catch(err => {
    const contentEl = aiMsg.querySelector('.msg-content');
    contentEl.textContent = '请求失败: ' + err.message;
    aiMsg.classList.remove('msg-streaming');
  });
}

function appendMessage(role, content, streaming = false) {
  // 首次发消息时清空空状态
  if (chatMessages.classList.contains('empty')) {
    chatMessages.classList.remove('empty');
    chatMessages.innerHTML = '';
  }
  const div = document.createElement('div');
  div.className = 'msg msg-' + role + (streaming ? ' msg-streaming' : '');
  div.innerHTML = `<div class="msg-content">${content}</div>`;
  chatMessages.appendChild(div);
  chatMessages.scrollTop = chatMessages.scrollHeight;
  return div;
}

function addSource(citation) {
  // 首次添加引用时清空提示
  if (sourcesPanel.querySelector('div:only-child')?.textContent.includes('等待 AI 回答')) {
    sourcesPanel.innerHTML = '';
  }
  const div = document.createElement('div');
  div.className = 'source-card';
  div.dataset.marker = citation.marker || '';
  div.innerHTML = `
    <div class="source-card-title">${citation.marker || ''} ${citation.title || '未知文档'}</div>
    <div class="source-card-snippet">${citation.snippet || ''}</div>
    <div class="source-card-meta">
      <span>相关度 ${(citation.score * 100).toFixed(0)}%</span>
    </div>
  `;
  sourcesPanel.appendChild(div);
}

// 回答中的引用编号点击高亮对应卡片
let _activeSourceCard = null;
function highlightSourceCard(marker) {
  document.querySelectorAll('.source-card').forEach(card => {
    card.classList.remove('source-card-active');
  });
  _activeSourceCard = null;
  if (!marker) return;
  const target = Array.from(document.querySelectorAll('.source-card')).find(card =>
    card.dataset.marker === marker
  );
  if (target) {
    target.classList.add('source-card-active');
    target.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    _activeSourceCard = target;
  }
}

document.getElementById('chat-messages')?.addEventListener('click', (e) => {
  const cite = e.target.closest('.citation');
  if (cite) {
    const marker = cite.dataset.marker || cite.textContent.trim();
    highlightSourceCard(marker);
  }
});

document.getElementById('sources-panel')?.addEventListener('click', (e) => {
  const card = e.target.closest('.source-card');
  if (card) {
    const marker = card.dataset.marker;
    highlightSourceCard(marker);
  }
});

// ===== 文档入库 =====
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

function handleFiles(files) {
  if (!files.length) return;
  const queue = document.getElementById('upload-queue');
  const formData = new FormData();
  for (const f of files) {
    formData.append('files', f);
    // 占位项
    const div = document.createElement('div');
    div.className = 'upload-item';
    div.innerHTML = `<div class="file-icon">...</div><div class="file-info"><div class="file-name">${f.name}</div><div class="file-meta">${formatSize(f.size)}</div><div class="progress-bar"><div class="progress-fill" style="width: 20%"></div></div></div><div class="file-status status-processing">⏳ 上传中...</div>`;
    div.dataset.filename = f.name;
    queue.appendChild(div);
  }

  fetch('/api/ingest/upload', { method: 'POST', body: formData })
    .then(r => r.json())
    .then(data => {
      for (const r of data.results || []) {
        const item = queue.querySelector(`[data-filename="${r.filename}"]`);
        if (!item) continue;
        if (r.status === 'success') {
          item.querySelector('.progress-fill').style.width = '100%';
          item.querySelector('.file-status').className = 'file-status status-success';
          item.querySelector('.file-status').textContent = r.tags?.length ? '✓ ' + r.tags.join(', ') : '✓ 已入库';
        } else {
          item.querySelector('.file-status').className = 'file-status';
          item.querySelector('.file-status').textContent = '✗ ' + (r.error || '失败');
        }
      }
    })
    .catch(err => {
      console.error('上传失败:', err);
    });
}

function formatSize(bytes) {
  if (bytes < 1024) return bytes + ' B';
  if (bytes < 1024*1024) return (bytes/1024).toFixed(1) + ' KB';
  return (bytes/(1024*1024)).toFixed(1) + ' MB';
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
    alert(data.status === 'success' ? `入库成功: ${data.title}` : `失败: ${data.error || '未知错误'}`);
  });
});

// ===== 搜索 =====
document.getElementById('search-btn')?.addEventListener('click', doSearch);
document.getElementById('search-input')?.addEventListener('keydown', (e) => {
  if (e.key === 'Enter') doSearch();
});

function doSearch() {
  const q = document.getElementById('search-input')?.value?.trim();
  if (!q) return;

  const resultsContainer = document.getElementById('search-results');
  const resultCount = document.getElementById('result-count');
  resultsContainer.innerHTML = '<div style="text-align:center;color:var(--text-muted);padding:40px">搜索中...</div>';

  fetch(`/api/search?q=${encodeURIComponent(q)}&limit=10`)
    .then(r => r.json())
    .then(data => {
      resultCount.textContent = `找到 ${data.total} 个结果 · 用时 ${data.time_ms} 秒`;
      resultsContainer.innerHTML = '';

      if (!data.results?.length) {
        resultsContainer.innerHTML = '<div style="text-align:center;color:var(--text-muted);padding:40px">未找到结果</div>';
        return;
      }

      for (const r of data.results) {
        // 高亮
        let snippet = escapeHtml(r.snippet || r.content || '');
        const keywords = q.split(/\s+/).filter(k => k.length >= 2);
        for (const kw of keywords) {
          const escaped = kw.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
          snippet = snippet.replace(new RegExp(escaped, 'gi'), m => `<mark>${m}</mark>`);
        }

        const tagsHtml = (r.tags || []).map(t => `<span class="tag tag-orange">${t}</span>`).join(' ');
        const div = document.createElement('div');
        div.className = 'result-item';
        div.innerHTML = `
          <div class="result-title">${r.doc_title} ${tagsHtml}</div>
          <div class="result-snippet">${snippet}</div>
          <div class="result-meta">
            <span>相关度 <span class="score-bar"><span class="score-fill" style="width:${(r.score*100).toFixed(0)}%"></span></span> ${(r.score*100).toFixed(0)}%</span>
          </div>`;
        resultsContainer.appendChild(div);
      }
    });
}

function escapeHtml(str) {
  const d = document.createElement('div');
  d.textContent = str;
  return d.innerHTML;
}

// ===== 数据分析 =====
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
      container.innerHTML = `<div style="color:var(--accent-red);padding:20px">分析失败: ${err.message}</div>`;
    });
});

function renderAnalyze(data) {
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

// ===== 仪表盘 =====
function loadDashboard() {
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
        chartDiv.innerHTML = data.top_tags.map(t =>
          `<div class="chart-bar" style="height:${(t.count/maxCount*100).toFixed(0)}%" data-label="${t.name}"></div>`
        ).join('');
      }

      // 告警
      const alertsDiv = document.getElementById('alerts-list');
      if (alertsDiv && data.alerts) {
        alertsDiv.innerHTML = data.alerts.map(a =>
          `<div class="alert-item ${a.severity}"><strong>${a.severity === 'error' ? '❌' : '⚠️'} ${a.severity}</strong><br>${a.message}</div>`
        ).join('');
      }

      // 最近文档
      const recentDiv = document.getElementById('recent-docs');
      if (recentDiv && data.recent_docs) {
        recentDiv.innerHTML = data.recent_docs.map(d =>
          `<tr><td>${d.title}</td><td>${d.file_type}</td><td>${(d.tags||[]).map(t=>`<span class="tag tag-orange">${t}</span>`).join(' ')}</td><td>${d.chunk_count}</td><td>${d.created_at}</td></tr>`
        ).join('');
      }
    });
}

// ===== 知识图谱 · vis.js =====
let graphNetwork = null;

function loadGraph() {
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
                  `<div>→ <span style="color:${colorMap[n.type] || 'var(--accent-cyan)'}">${n.node}</span> (${n.relation_label})</div>`
                ).join('');
              } else {
                div.innerHTML = '<div style="color:var(--text-muted)">未找到邻居</div>';
              }
            });
        }
      });

      graphNetwork = network;
    });
}

// 图谱统计更新
function loadGraphStats() {
  fetch('/api/stats').then(r => r.json()).then(data => {
    document.getElementById('graph-node-count').textContent = data.graph_nodes;
    document.getElementById('graph-edge-count').textContent = data.graph_edges;
  });
}

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
  });
});

// ===== 宠物管理 =====
function loadPet() {
  fetch('/api/pet/status')
    .then(r => r.json())
    .then(data => {
      if (!data.found) {
        document.getElementById('pet-status').innerHTML =
          '<div style="text-align:center;padding:40px"><p>尚未领养宠物</p><button class="btn btn-primary" onclick="adoptPet()">领养宠物</button></div>';
        return;
      }

      document.getElementById('pet-name').textContent = data.name;
      document.getElementById('pet-level').textContent = `Lv.${data.level} · ${data.style} 风格`;
      document.getElementById('pet-mood').style.width = data.mood + '%';
      document.getElementById('pet-hunger').style.width = data.hunger + '%';
      document.getElementById('pet-energy').style.width = data.energy + '%';
      document.getElementById('pet-intellect').style.width = data.intellect + '%';

      // 人格卡片高亮
      document.querySelectorAll('.persona-card-style').forEach(card => {
        card.classList.toggle('active', card.dataset.style === data.style);
      });
    });
}

function adoptPet() {
  const name = prompt('给宠物起个名字:') || '小白';
  fetch('/api/pet/adopt', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ name }),
  }).then(r => r.json()).then(data => {
    if (data.ascii_art) {
      document.getElementById('pet-ascii').textContent = data.ascii_art;
    }
    loadPet();
  });
}

document.querySelectorAll('.pet-interact-btn').forEach(btn => {
  btn.addEventListener('click', () => {
    const action = btn.dataset.action;
    fetch('/api/pet/interact', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ action }),
    }).then(r => r.json()).then(() => loadPet());
  });
});

// 人格卡片切换
document.querySelectorAll('.persona-card-style').forEach(card => {
  card.addEventListener('click', () => {
    const style = card.dataset.style;
    fetch('/api/pet/style', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ style }),
    }).then(r => r.json()).then(() => loadPet());
  });
});

// ===== 初始加载 =====
document.addEventListener('DOMContentLoaded', () => {
  loadDashboard();
});

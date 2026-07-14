// 顶栏搜索 + 搜索页
import { switchPage } from './nav.js';
import { escapeHtml, showError } from './utils.js';

export function initTopbarSearch() {
  const topbarSearch = document.getElementById('topbar-search');
  const topbarSearchInput = document.getElementById('topbar-search-input');

  if (topbarSearch) {
    topbarSearch.addEventListener('click', (e) => {
      // 点击 kbd 或外层容器时聚焦输入框;点击 input 自身不重复处理
      if (e.target === topbarSearchInput) return;
      switchPage('search');
      const searchInput = document.getElementById('search-input');
      if (topbarSearchInput && searchInput) {
        const v = topbarSearchInput.value.trim();
        if (v) searchInput.value = v;
        searchInput.focus();
      }
    });
  }

  if (topbarSearchInput) {
    topbarSearchInput.addEventListener('keydown', (e) => {
      if (e.key === 'Enter') {
        e.preventDefault();
        switchPage('search');
        const searchInput = document.getElementById('search-input');
        if (searchInput) {
          searchInput.value = topbarSearchInput.value.trim();
          searchInput.focus();
          doSearch();
        }
      }
    });
  }

  // 全局 "/" 快捷键: 跳转搜索页并聚焦
  document.addEventListener('keydown', (e) => {
    if (e.key !== '/') return;
    const tag = (e.target && e.target.tagName) ? e.target.tagName.toLowerCase() : '';
    if (tag === 'input' || tag === 'textarea') return;
    // 已在搜索页则不拦截
    const searchPage = document.getElementById('page-search');
    if (searchPage && searchPage.classList.contains('active')) return;
    e.preventDefault();
    switchPage('search');
    const searchInput = document.getElementById('search-input');
    if (searchInput) searchInput.focus();
  });

  // 搜索按钮/输入框
  document.getElementById('search-btn')?.addEventListener('click', doSearch);
  document.getElementById('search-input')?.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') doSearch();
  });
}

let searchAbortController = null;
let loadingTimer = null;
let progressTimer = null;

function renderResults(data, q) {
  const resultsContainer = document.getElementById('search-results');
  const resultCount = document.getElementById('result-count');

  resultCount.textContent = `找到 ${data.total} 个结果 · 用时 ${(data.time_ms / 1000).toFixed(2)} 秒`;
  resultsContainer.innerHTML = '';

  if (!data.results?.length) {
    resultsContainer.innerHTML = '<div class="empty-state">未找到结果</div>';
    return;
  }

  for (const r of data.results) {
    let snippet = escapeHtml(r.snippet || r.content || '');
    const keywords = q.split(/\s+/).filter(k => k.length >= 2);
    for (const kw of keywords) {
      const escaped = kw.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
      snippet = snippet.replace(new RegExp(escaped, 'gi'), m => `<mark>${m}</mark>`);
    }

    const tagsHtml = (r.tags || []).map(t => `<span class="tag tag-orange">${escapeHtml(t)}</span>`).join(' ');
    const div = document.createElement('div');
    div.className = 'result-item';
    div.innerHTML = `
      <div class="result-title">${escapeHtml(r.doc_title)} ${tagsHtml}</div>
      <div class="result-snippet">${snippet}</div>
      <div class="result-meta">
        <span>相关度 <span class="score-bar"><span class="score-fill" style="width:${(r.score*100).toFixed(0)}%"></span></span> ${(r.score*100).toFixed(0)}%</span>
      </div>`;
    resultsContainer.appendChild(div);
  }
}

function startLoading(useVector, useRerank) {
  const loading = document.getElementById('search-loading');
  const results = document.getElementById('search-results');
  const stage = document.getElementById('loading-stage');
  const bar = document.getElementById('loading-progress-bar');

  loading.style.display = '';
  results.style.display = 'none';

  const stages = [
    { text: 'BM25 关键词检索中...', progress: 15 },
    { text: useVector ? '向量语义检索中...' : '混合检索配置中...', progress: 40 },
    { text: 'RRF 融合排序中...', progress: 65 },
    { text: useRerank ? 'LLM 重排序中...' : '结果精炼中...', progress: 85 },
    { text: '结果生成中...', progress: 95 },
  ];

  let current = 0;
  let progress = 0;

  function update() {
    const target = stages[current].progress;
    progress += (target - progress) * 0.15;
    if (bar) bar.style.width = `${progress}%`;
    if (stage) stage.textContent = stages[current].text;

    if (Math.abs(progress - target) < 1 && current < stages.length - 1) {
      current++;
    }
  }

  update();
  progressTimer = setInterval(update, 180);
}

function finishLoading() {
  const loading = document.getElementById('search-loading');
  const results = document.getElementById('search-results');
  const bar = document.getElementById('loading-progress-bar');

  if (bar) bar.style.width = '100%';

  setTimeout(() => {
    loading.style.display = 'none';
    results.style.display = '';
  }, 250);

  if (progressTimer) {
    clearInterval(progressTimer);
    progressTimer = null;
  }
  if (loadingTimer) {
    clearTimeout(loadingTimer);
    loadingTimer = null;
  }
}

function stopLoading() {
  const loading = document.getElementById('search-loading');
  const results = document.getElementById('search-results');
  if (loading) loading.style.display = 'none';
  if (results) results.style.display = '';
  if (progressTimer) { clearInterval(progressTimer); progressTimer = null; }
  if (loadingTimer) { clearTimeout(loadingTimer); loadingTimer = null; }
}

export function doSearch() {
  const q = document.getElementById('search-input')?.value?.trim();
  if (!q) return;

  // 取消之前的搜索
  if (searchAbortController) {
    searchAbortController.abort();
  }
  searchAbortController = new AbortController();

  const resultsContainer = document.getElementById('search-results');
  const resultCount = document.getElementById('result-count');
  const searchBtn = document.getElementById('search-btn');
  const originalBtnText = searchBtn?.textContent || '搜索';

  if (searchBtn) {
    searchBtn.disabled = true;
    searchBtn.textContent = '搜索中';
  }

  resultCount.textContent = '搜索中...';
  resultsContainer.style.display = 'none';

  // 读取开关状态
  const toggles = document.querySelectorAll('.search-filters .toggle');
  const useVector = toggles[0]?.classList.contains('on') ?? true;
  const useRerank = toggles[1]?.classList.contains('on') ?? true;

  // 如果搜索很快，避免闪烁 loading；超过 250ms 才显示动态加载
  let loadingShown = false;
  loadingTimer = setTimeout(() => {
    startLoading(useVector, useRerank);
    loadingShown = true;
  }, 250);

  fetch(`/api/search?q=${encodeURIComponent(q)}&limit=10&use_vector=${useVector}&use_rerank=${useRerank}`, {
    signal: searchAbortController.signal,
  })
    .then(r => r.json())
    .then(data => {
      if (loadingShown) {
        renderResults(data, q);
        finishLoading();
      } else {
        stopLoading();
        renderResults(data, q);
      }
    })
    .catch(err => {
      if (err.name === 'AbortError') return;
      console.error('搜索失败:', err);
      stopLoading();
      resultsContainer.innerHTML = '';
      showError('search-results', err.message);
    })
    .finally(() => {
      if (searchBtn) {
        searchBtn.disabled = false;
        searchBtn.textContent = originalBtnText;
      }
      searchAbortController = null;
    });
}

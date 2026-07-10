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

export function doSearch() {
  const q = document.getElementById('search-input')?.value?.trim();
  if (!q) return;

  const resultsContainer = document.getElementById('search-results');
  const resultCount = document.getElementById('result-count');
  resultsContainer.innerHTML = '<div style="text-align:center;color:var(--text-muted);padding:40px">搜索中...</div>';

  // 读取开关状态
  const toggles = document.querySelectorAll('.search-filters .toggle');
  const useVector = toggles[0]?.classList.contains('on') ?? true;
  const useRerank = toggles[1]?.classList.contains('on') ?? true;

  fetch(`/api/search?q=${encodeURIComponent(q)}&limit=10&use_vector=${useVector}&use_rerank=${useRerank}`)
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
    })
    .catch(err => {
      console.error('搜索失败:', err);
      showError('search-results', err.message);
    });
}

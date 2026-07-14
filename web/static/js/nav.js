// 导航切换 + 通用 UI 控件
import { state } from './state.js';
import { loadDashboard } from './dashboard.js';
import { loadGraph } from './graph.js';
import { loadPet } from './pet.js';

const pageNames = {
  qa: 'AI 问答', ingest: '文档入库', search: '搜索',
  analyze: '数据分析', dashboard: '仪表盘', graph: '知识图谱', pet: '宠物管理'
};

export function switchPage(target) {
  // 切换离开 QA 页面时取消正在进行的 SSE 流
  if (target !== 'qa' && state.abortController) {
    state.abortController.abort();
    state.abortController = null;
  }

  const navItems = document.querySelectorAll('.nav-item[data-page]');
  navItems.forEach(n => n.classList.remove('active'));
  const navTarget = document.querySelector(`.nav-item[data-page="${target}"]`);
  if (navTarget) navTarget.classList.add('active');
  document.querySelectorAll('.page').forEach(p => p.classList.remove('active'));
  const pageEl = document.getElementById('page-' + target);
  if (pageEl) pageEl.classList.add('active');
  document.querySelector('.main')?.classList.toggle('main-qa-active', target === 'qa');
  const breadcrumb = document.getElementById('breadcrumb-current');
  if (breadcrumb) breadcrumb.textContent = pageNames[target] || '';

  // 按需加载数据
  if (target === 'dashboard') loadDashboard();
  if (target === 'graph') loadGraph();
  if (target === 'pet') loadPet();
}

export function initNav() {
  // 导航项点击
  document.querySelectorAll('.nav-item[data-page]').forEach(item => {
    item.addEventListener('click', () => switchPage(item.dataset.page));
  });

  // 人格切换（输入栏 chips）
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
}

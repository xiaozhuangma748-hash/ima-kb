// IMA Web 后台 · 前端入口
// 聚合各模块初始化
import { initNav } from './nav.js';
import { initTopbarSearch } from './search.js';
import { initQA } from './qa.js';
import { initIngest } from './ingest.js';
import { initAnalyze } from './analyze.js';
import { initDashboard, loadDashboard } from './dashboard.js';
import { initGraph } from './graph.js';
import { initPet } from './pet.js';

document.addEventListener('DOMContentLoaded', () => {
  initNav();
  initTopbarSearch();
  initQA();
  initIngest();
  initAnalyze();
  initDashboard();
  initGraph();
  initPet();
  // 初始加载仪表盘数据（仪表盘为默认激活页）
  loadDashboard();
});

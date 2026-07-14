// IMA Web 后台 · 前端入口
// 动态导入带版本号，彻底绕过浏览器模块缓存
const staticVersion = document.querySelector('meta[name="static-version"]')?.content || Date.now();

Promise.all([
  import(`./nav.js?v=${staticVersion}`),
  import(`./search.js?v=${staticVersion}`),
  import(`./qa.js?v=${staticVersion}`),
  import(`./ingest.js?v=${staticVersion}`),
  import(`./analyze.js?v=${staticVersion}`),
  import(`./dashboard.js?v=${staticVersion}`),
  import(`./graph.js?v=${staticVersion}`),
  import(`./pet.js?v=${staticVersion}`),
])
  .then(([
    { initNav },
    { initTopbarSearch },
    { initQA },
    { initIngest },
    { initAnalyze },
    { initDashboard, loadDashboard },
    { initGraph },
    { initPet },
  ]) => {
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
  })
  .catch(err => {
    console.error('IMA 前端模块加载失败:', err);
  });

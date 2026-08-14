// 顶部 Tab 条：6 个功能页入口；QA 模式隐藏
const TABS = [
  { key: 'ingest', label: '入库', icon: '⇪' },
  { key: 'search', label: '搜索', icon: '⌕' },
  { key: 'analyze', label: '分析', icon: '▤' },
  { key: 'dashboard', label: '仪表盘', icon: '▥' },
  { key: 'graph', label: '图谱', icon: '◈' },
  { key: 'pet', label: '宠物', icon: '♥' },
]

export default function TopTabs({ currentPage, setCurrentPage, hidden }) {
  if (hidden) return <div className="toptabs toptabs-hidden" />
  return (
    <div className="toptabs">
      {TABS.map(t => (
        <button
          key={t.key}
          className={`tab ${currentPage === t.key ? 'active' : ''}`}
          onClick={() => setCurrentPage(t.key)}
        >
          <span className="tab-icon">{t.icon}</span>
          <span>{t.label}</span>
        </button>
      ))}
    </div>
  )
}
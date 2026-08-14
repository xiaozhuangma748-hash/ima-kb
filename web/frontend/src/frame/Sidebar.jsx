import { useQA } from '../store/qa.jsx'
import { Btn } from '../ui/Base.jsx'

// 侧栏：品牌 + 新会话 + 会话历史 + 底部设置；collapsed 时收敛为 56px icon rail
export default function Sidebar({ collapsed, width, onToggle, onOpenSettings, currentPage, setCurrentPage }) {
  const {
    sessions, currentSessionId, beginNewSession, restoreSession, deleteSession,
    streamingSessionIds, avatarHtml,
  } = useQA()

  const startNew = () => {
    beginNewSession()
    if (currentPage !== 'qa') setCurrentPage('qa')
  }

  const openSession = (id) => {
    restoreSession(id)
    if (currentPage !== 'qa') setCurrentPage('qa')
  }

  return (
    <aside className={`sidebar ${collapsed ? 'sidebar-collapsed' : ''}`} style={{ width }}>
      {collapsed ? (
        <div className="rail">
          <button className="rail-btn" title="新会话" onClick={() => { startNew(); onToggle() }}>
            <span className="icon-plus">+</span>
          </button>
          <div className="rail-grow" />
          <button className="rail-btn" title="设置" onClick={onOpenSettings}>
            <span className="icon-gear">⚙</span>
          </button>
        </div>
      ) : (
        <>
          <div className="sidebar-head">
            <div className="brand">
              <div className="brand-logo" aria-hidden="true" dangerouslySetInnerHTML={{ __html: avatarHtml }} />
              <div className="brand-text">
                <span className="brand-name">IMA 知识库</span>
                <span className="brand-sub">智能问答助手</span>
              </div>
            </div>
            <Btn className="new-session-btn" variant="primary" onClick={startNew}>
              <span className="icon-plus">+</span>
              <span>新会话</span>
            </Btn>
            <button className="collapse-btn" onClick={onToggle} title="折叠侧栏">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M15 18l-6-6 6-6"/></svg>
            </button>
          </div>

          <div className="sidebar-section-title">会话历史</div>
          <div className="sidebar-sessions">
            {sessions.length === 0 ? (
              <div className="sessions-empty">暂无历史会话</div>
            ) : (
              sessions.map(s => (
                <div
                  key={s.id}
                  className={`session-item ${s.id === currentSessionId ? 'active' : ''}`}
                  onClick={() => openSession(s.id)}
                >
                  <span className={`session-dot ${streamingSessionIds.includes(s.id) ? 'generating' : ''}`} />
                  {streamingSessionIds.includes(s.id) && (
                    <span className="session-generating" title="正在后台生成…" />
                  )}
                  <span className="session-title" title={s.title}>{s.title}</span>
                  <button
                    className="session-del"
                    title="删除会话"
                    onClick={(e) => { e.stopPropagation(); deleteSession(s.id) }}
                  >×</button>
                </div>
              ))
            )}
          </div>

          <div className="sidebar-footer">
            <button className="footer-btn" onClick={onOpenSettings}>
              <span className="icon-gear">⚙</span>
              <span>设置</span>
            </button>
          </div>
        </>
      )}
    </aside>
  )
}
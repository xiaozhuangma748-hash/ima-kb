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
            <svg className="icon-gear" width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1 0 2.83 2 2 0 0 1-2.83 0l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-2 2 2 2 0 0 1-2-2v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83 0 2 2 0 0 1 0-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1-2-2 2 2 0 0 1 2-2h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 0-2.83 2 2 0 0 1 2.83 0l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 2-2 2 2 0 0 1 2 2v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 0 2 2 0 0 1 0 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 2 2 2 2 0 0 1-2 2h-.09a1.65 1.65 0 0 0-1.51 1z"/></svg>
          </button>
        </div>
      ) : (
        <>
          <div className="sidebar-head">
            <div className="brand">
              <div className="brand-logo" aria-hidden="true" dangerouslySetInnerHTML={{ __html: avatarHtml }} />
              <div className="brand-text">
                <span className="brand-name">IMA 知识库</span>
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
              <svg className="icon-gear" width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1 0 2.83 2 2 0 0 1-2.83 0l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-2 2 2 2 0 0 1-2-2v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83 0 2 2 0 0 1 0-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1-2-2 2 2 0 0 1 2-2h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 0-2.83 2 2 0 0 1 2.83 0l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 2-2 2 2 0 0 1 2 2v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 0 2 2 0 0 1 0 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 2 2 2 2 0 0 1-2 2h-.09a1.65 1.65 0 0 0-1.51 1z"/></svg>
              <span>设置</span>
            </button>
          </div>
        </>
      )}
    </aside>
  )
}
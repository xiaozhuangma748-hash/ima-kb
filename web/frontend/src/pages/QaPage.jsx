import React, { useEffect, useRef, useState } from 'react'
import { useQA, RETRIEVAL_MODES } from '../store/qa.jsx'
import { api } from '../api.js'
import TrajectoryView from '../components/TrajectoryView.jsx'

const PERSONAS = [
  { key: 'neutral', label: '综合模式', desc: '平衡回答质量与速度' },
  { key: 'scholar', label: '深度分析模式', desc: '多角度分析，引用详尽' },
  { key: 'warrior', label: '直接行动模式', desc: '简洁直接，快速给出结论' },
  { key: 'artisan', label: '结构化模式', desc: '条理清晰，分点分步输出' },
]

const STEPS = [
  { key: '检索', label: 'Retrieve', icon: 'M21 21l-4.35-4.35M11 19a8 8 0 1 0 0-16 8 8 0 0 0 0 16z' },
  { key: '重排', label: 'Rerank', icon: 'M12 2l2.4 4.86 5.37.78-3.88 3.79.92 5.36L12 14.9l-4.81 2.53.92-5.36-3.88-3.79 5.37-.78z' },
  { key: '注入', label: 'Inject', icon: 'M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z M14 2v6h6 M12 18v-6 M9 15l6-6' },
  { key: '生成', label: 'Generate', icon: 'M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z' },
]

const KB_NAME = '34-知识库'

// 输入框左下角加号指令菜单：插入文档 / 清空上下文
function CmdMenu({ setCurrentPage, beginNewSession }) {
  const [open, setOpen] = useState(false)
  return (
    <div className="cmd-menu-wrap">
      <button
        className="cmd-menu-trigger"
        onClick={(e) => { e.stopPropagation(); setOpen(o => !o) }}
        title="更多操作"
      >
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M12 5v14M5 12h14" /></svg>
      </button>
      {open && (
        <div className="cmd-menu" onClick={(e) => e.stopPropagation()}>
          <button
            className="cmd-menu-item"
            onMouseDown={(e) => { e.preventDefault(); setOpen(false); setCurrentPage && setCurrentPage('ingest') }}
          >
            插入文档
          </button>
          <button
            className="cmd-menu-item"
            onMouseDown={(e) => { e.preventDefault(); setOpen(false); beginNewSession() }}
          >
            清空上下文
          </button>
        </div>
      )}
    </div>
  )
}

function renderAnswer(content) {
  if (typeof marked === 'undefined') return content
  // 压缩连续空行：LLM 输出常带多个连续换行，markdown 会渲染成一堆空段落
  // 这里把 3 个及以上连续换行压缩为 1 个空行（保留段落分隔），使输出紧凑
  const clean = (content || '').replace(/\n{3,}/g, '\n\n')
  let html = marked.parse(clean)
  // 移除中文/数字/右括号/百分号等与引用标记 [n] 之间的空格，避免出现"  [5]"的空隙
  // （LLM 输出常在中文字符与引用标记间夹一个空格，视觉上不自然）
  html = html.replace(/([\u4e00-\u9fff0-9a-zA-Z%)）%])\s+(\[\d+\])/g, '$1$2')
  html = html.replace(/\[(\d+)\]\(?(?!\w)/g, (_, n) =>
    `<span class="citation" data-marker="[${n}]">[${n}]</span>`
  )
  return html
}

// 精简摘要：长文本截断前 N 字，返回是否被截断，供点击展开
const TRUNC_N = 40
function truncate(text, n = TRUNC_N) {
  if (!text) return { text: '', clipped: false }
  return text.length > n
    ? { text: text.slice(0, n) + '…', clipped: true }
    : { text, clipped: false }
}

// 工作过程卡片：生成中动态展示各阶段，生成后随回答保留在回复上方
function WorkCard({ live, stage, stageContext, worklog, retrievalLabel, personaLabel, model, useVector, useRerank, autoExpandSources }) {
  const [open, setOpen] = useState(true)
  const [expandedStep, setExpandedStep] = useState(null)
  const [historyOpen, setHistoryOpen] = useState(false)
  // 引用来源自动展开：true 时"召回片段"默认展开，false 时默认折叠
  const [sourcesOpen, setSourcesOpen] = useState(autoExpandSources)
  const [expHistory, setExpHistory] = useState({})  // {idx: bool} 会话历史条目展开态
  const [expSources, setExpSources] = useState({})  // {idx: bool} 召回片段条目展开态
  // 检索阶段候选来源列表（含 source 类型），到达时缓存，供整个 live 周期与结束后展示来源分布
  const [retrievalCtx, setRetrievalCtx] = useState(null)
  useEffect(() => {
    if (live && stage && stage.key === '检索' && stageContext && stageContext.sources) {
      setRetrievalCtx(stageContext.sources)
    }
  }, [live, stage, stageContext])
  const doneAll = !live || (stage && stage.label === '缓存')
  const idx = live ? (stage ? stage.idx : 0) : STEPS.length
  return (
    <div className="think-card">
      <button className="think-card-head" type="button" onClick={() => setOpen(o => !o)}>
        <span className="think-card-title">
          <svg className="think-card-icon" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M9.5 2A7.5 7.5 0 0 0 5 15.5V18a2 2 0 0 0 2 2h.5a2.5 2.5 0 0 0 2.5-2.5V15a2 2 0 0 0-2-2H9V9a4 4 0 0 1 4-4h2a4 4 0 0 1 4 4v2h-.5a2 2 0 0 0-2 2h.5a2.5 2.5 0 0 1 2.5 2.5V18a2 2 0 0 1-2 2H17a2 2 0 0 1-2-2v-.5A2.5 2.5 0 0 0 12.5 15H11a2 2 0 0 0-2 2v1a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2v-2.5A7.5 7.5 0 0 1 9.5 2z"/></svg>
          Work Process
        </span>
        <span className="think-card-stage">
          {live
            ? (stage && stage.label === '缓存'
              ? <span className="think-cache-hit">Cache Hit</span>
              : <><span className="think-card-spinner" />{STEPS.find(x => x.key === stage.key)?.label || 'Working'}…</>)
            : <span className="think-cache-hit">Done</span>}
        </span>
        <svg className={`think-card-arrow ${open ? 'open' : ''}`} width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round"><polyline points="6 9 12 15 18 9"></polyline></svg>
      </button>
      {open && (
        <div className="think-card-body">
          <div className="think-flow">
            {STEPS.map((s, i) => {
              // 运行时逐步骤追加出现：只渲染"已完成 + 正在进行"的步骤，
              // 未来的步骤随进度一个个冒出（带淡入动画），而非一开始全部列出
              if (!doneAll && i > idx) return null
              const last = i === STEPS.length - 1
              const done = doneAll || i < idx
              const active = live && !doneAll && i === idx
              const expanded = expandedStep === s.key
              const srcCount = live ? (stageContext && stageContext.sources ? stageContext.sources.length : 0) : (worklog && worklog.sources ? worklog.sources.length : 0)
              return (
                <div key={s.key} className={`think-step ${done ? 'done' : ''} ${active ? 'active' : ''} ${last ? 'last' : ''}`}>
                  <button type="button" className="think-step-head" onClick={() => setExpandedStep(expanded ? null : s.key)}>
                    <svg className="think-step-icon" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d={s.icon} /></svg>
                    <span className="think-step-name">{s.label}</span>
                  </button>
                  {expanded && (
                    <div className="think-step-detail">
                      {s.key === '检索' && (
                        <>
                          <span className="think-detail-note">
                            {srcCount ? `共召回 ${srcCount} 条候选片段，进入下一步精选` : '未检索到候选，可能为闲聊或空知识库'}
                          </span>
                          {(() => {
                            // 来源分布：live 用检索阶段缓存，结束后用 worklog 持久化的检索清单
                            const list = live
                              ? (retrievalCtx || (stageContext && stageContext.sources ? stageContext.sources : null))
                              : (worklog && worklog.retrievalMeta && worklog.retrievalMeta.sources ? worklog.retrievalMeta.sources : null)
                            if (!list || !list.length) return null
                            const v = list.filter(x => x.source === 'vector').length
                            const b = list.filter(x => x.source === 'bm25').length
                            const m = list.filter(x => x.source === 'both').length
                            return (
                              <span className="think-detail-src">
                                <b>来源</b>
                                <span className={`src-chip v ${v ? '' : 'zero'}`}>向量 {v}</span>
                                <span className={`src-chip b ${b ? '' : 'zero'}`}>关键词 {b}</span>
                                <span className={`src-chip m ${m ? '' : 'zero'}`}>混合 {m}</span>
                              </span>
                            )
                          })()}
                        </>
                      )}
                      {s.key === '重排' && (
                        <span className="think-detail-note">
                          {srcCount
                            ? `已精选 ${srcCount} 条高相关片段用于回答`
                            : (useRerank ? '已按相关度精选片段' : '未启用 LLM 重排序，直接取前几条')}
                        </span>
                      )}
                      {s.key === '注入' && (
                        <>
                          <div className="think-detail-grid">
                            <span className="think-detail-cell"><b>检索模式</b>{retrievalLabel}</span>
                            <span className="think-detail-cell"><b>回复模式</b>{personaLabel}</span>
                            <span className="think-detail-cell"><b>模型</b>{model || '—'}</span>
                            <span className="think-detail-cell"><b>向量</b>{useVector ? '开' : '关'}</span>
                            <span className="think-detail-cell"><b>重排序</b>{useRerank ? '开' : '关'}</span>
                          </div>
                          <div className="think-inject">
                            <span className="think-inject-title">本次注入内容</span>
                            <button type="button" className="think-inject-row" onClick={() => setHistoryOpen(o => !o)}>
                              <span className="think-inject-label">会话历史</span>
                              <span className="think-inject-meta">{worklog?.inject?.history_count ?? worklog?.history?.length ?? 0} 条</span>
                              <svg className={`think-inject-chev ${historyOpen ? 'open' : ''}`} width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round"><polyline points="6 9 12 15 18 9"></polyline></svg>
                            </button>
                            {historyOpen && (
                              <div className="think-inject-body">
                                {(worklog?.history || []).map((h, j) => {
                                  const full = expHistory[j]
                                  const t = truncate(h.content)
                                  return (
                                    <button
                                      key={j}
                                      type="button"
                                      className={`think-inject-item ${t.clipped && !full ? 'clipped' : ''}`}
                                      onClick={() => setExpHistory(s => ({ ...s, [j]: !s[j] }))}
                                    >
                                      <span className={`think-inject-role ${h.role}`}>{h.role === 'user' ? '用户' : 'AI'}</span>
                                      <span className="think-inject-text">{full ? h.content : t.text}</span>
                                      {t.clipped && (
                                        <span className="think-inject-expand">{full ? '收起' : '展开'}</span>
                                      )}
                                    </button>
                                  )
                                })}
                              </div>
                            )}
                            <button type="button" className="think-inject-row" onClick={() => setSourcesOpen(o => !o)}>
                              <span className="think-inject-label">召回片段</span>
                              <span className="think-inject-meta">{worklog?.inject?.sources_count ?? worklog?.sources?.length ?? 0} 条</span>
                              <svg className={`think-inject-chev ${sourcesOpen ? 'open' : ''}`} width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round"><polyline points="6 9 12 15 18 9"></polyline></svg>
                            </button>
                            {sourcesOpen && (
                              <div className="think-inject-body">
                                {(worklog?.sources || []).map((s, j) => {
                                  const full = expSources[j]
                                  const t = truncate(s.title)
                                  return (
                                    <button
                                      key={j}
                                      type="button"
                                      className={`think-inject-item ${t.clipped && !full ? 'clipped' : ''}`}
                                      onClick={() => setExpSources(x => ({ ...x, [j]: !x[j] }))}
                                    >
                                      <span className="think-inject-marker">[{s.marker}]</span>
                                      <span className="think-inject-text">{full ? s.title : t.text}</span>
                                      {t.clipped && (
                                        <span className="think-inject-expand">{full ? '收起' : '展开'}</span>
                                      )}
                                      {s.score > 0 && <span className="think-inject-score">{Math.round(s.score * 100)}%</span>}
                                    </button>
                                  )
                                })}
                              </div>
                            )}
                            <div className="think-inject-row">
                              <span className="think-inject-label">跨会话记忆</span>
                              <span className="think-inject-meta">{worklog?.inject?.has_memory ? '已注入' : '无'}</span>
                            </div>
                            <div className="think-inject-row">
                              <span className="think-inject-label">早期摘要</span>
                              <span className="think-inject-meta">{worklog?.inject?.has_summary ? '已注入' : '无'}</span>
                            </div>
                          </div>
                        </>
                      )}
                      {s.key === '生成' && (
                        <span className="think-detail-note">{live ? 'LLM 正在流式生成回答…' : '回答已生成'}</span>
                      )}
                    </div>
                  )}
                </div>
              )
            })}
          </div>
        </div>
      )}
    </div>
  )
}

export default function QaPage({ settings, setCurrentPage }) {
  const {
    messages, streaming, stage, stageContext, avatarHtml, persona, setPersona,
    retrieval, setRetrieval, send, stop, beginNewSession, sources,
    sessions, currentSessionId, restoreSession,
    models, currentModel, loadModels, switchModel, lastUsage,
  } = useQA()
  const [input, setInput] = useState('')
  const [personaOpen, setPersonaOpen] = useState(false)
  const [retrievalOpen, setRetrievalOpen] = useState(false)
  const [modelOpen, setModelOpen] = useState(false)
  const [logOpen, setLogOpen] = useState(false)
  const [elapsed, setElapsed] = useState(0)
  const [cacheHit, setCacheHit] = useState(false)
  const [refOpen, setRefOpen] = useState(false)      // 引用弹层
  const [refDetail, setRefDetail] = useState(null)   // {title, content} 选中文档详情
  const [refLoading, setRefLoading] = useState(false)
  const [viewTab, setViewTab] = useState('chat')     // 'chat' | 'trajectory'
  const textareaRef = useRef(null)
  const bottomRef = useRef(null)
  const startRef = useRef(0)
  // 记住最后一个有效阶段与 LLM 耗时：回复完成后 stage 被清空，状态栏仍保留最后值
  const lastStageRef = useRef(null)
  const lastElapsedRef = useRef(0)

  // 当前会话标题（用于顶部栏）
  const currentSession = sessions.find(s => s.id === currentSessionId)
  const sessionTitle = currentSession?.title || (messages.length ? '新会话' : '')

  // 阶段变化时记录最后值；完成后用 lastStage 兜底，避免"步数"回退到 0/4
  useEffect(() => { if (stage) lastStageRef.current = stage }, [stage])
  const shownStage = stage || lastStageRef.current

  // 轮数 = user 消息条数；步数 = 当前阶段
  const rounds = messages.filter(m => m.role === 'user').length
  const stepInfo = `${Math.min(shownStage ? shownStage.idx + 1 : 0, STEPS.length)}/${STEPS.length}`

  // 流式生成计时（LLM 耗时）
  useEffect(() => {
    if (streaming) {
      startRef.current = Date.now()
      setElapsed(0)
      const id = setInterval(() => {
        const e = (Date.now() - startRef.current) / 1000
        setElapsed(e)
        lastElapsedRef.current = e
      }, 100)
      return () => clearInterval(id)
    }
  }, [streaming, currentSessionId])

  // 缓存命中标记：后端在命中答案缓存时发送 stage="缓存"
  useEffect(() => {
    if (stage && stage.label === '缓存') setCacheHit(true)
    if (!streaming) setCacheHit(false)
  }, [stage, streaming])

  // 获取可用模型列表
  useEffect(() => { loadModels() }, [loadModels])

  // 消息区自动滚动
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' })
  }, [messages, stage])

  const autoGrow = (e) => {
    const el = e.target
    el.style.height = 'auto'
    el.style.height = Math.min(el.scrollHeight, 200) + 'px'
  }

  const submit = (text) => {
    const t = (text ?? input).trim()
    if (!t) return
    setInput('')
    send(t, { streaming: settings.streaming !== false })
    if (textareaRef.current) textareaRef.current.style.height = 'auto'
  }

  const onKeyDown = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      submit()
    }
  }

  const empty = messages.length === 0 && !streaming

  // 新会话（无消息）时自动回到"对话"视图，避免切到"轨迹"后点新会话残留空轨迹页
  useEffect(() => {
    if (empty) setViewTab('chat')
  }, [empty])

  // 点击正文引用标记 [n]：在当前引用来源中找到对应文档，打开引用弹层展示其内容
  // sources[].marker 可能是 3 或 "[3]"，统一去掉方括号后比较
  const stripBr = (m) => String(m).replace(/^\[|\]$/g, '')
  const onCiteClick = (e) => {
    const cite = e.target.closest('.citation')
    if (!cite) return
    const marker = stripBr(cite.dataset.marker || cite.textContent.trim())
    const s = sources.find(x => stripBr(x.marker) === marker)
    if (s) loadReference(s)
    else openReferences()
  }

  const openReferences = () => { setRefDetail(null); setRefOpen(true) }

  const loadReference = async (s) => {
    if (!s.doc_id) return
    setRefOpen(true)
    setRefLoading(true)
    setRefDetail({ title: s.title, content: '' })
    try {
      const d = await api.getDocumentContent(s.doc_id)
      setRefDetail({ title: d.title, content: d.content })
    } catch (err) {
      setRefDetail({ title: s.title, content: `加载失败：${err.message || err}` })
    }
    setRefLoading(false)
  }

  const currentPersona = PERSONAS.find(p => p.key === persona) || PERSONAS[0]
  const currentRetrieval = RETRIEVAL_MODES.find(m => m.key === retrieval.key) || RETRIEVAL_MODES[0]

  // 关闭下拉：点击外部区域
  useEffect(() => {
    const close = () => { setPersonaOpen(false); setRetrievalOpen(false); setModelOpen(false); setLogOpen(false) }
    document.addEventListener('click', close)
    return () => document.removeEventListener('click', close)
  }, [])

  return (
    <div className="qa-page">
      {/* 顶部会话栏 */}
      <div className="qa-topbar">
        <div className="qa-topbar-title">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg>
          <span className="qa-topbar-name">{sessionTitle || '新会话'}</span>
        </div>
        <div className="qa-topbar-actions">
          <button
            className="qa-topbar-log"
            type="button"
            onClick={(e) => { e.stopPropagation(); setLogOpen(o => !o) }}
            title="会话列表"
          >
            <span>Session log</span>
            <svg className="persona-select-arrow" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round"><polyline points="6 9 12 15 18 9"></polyline></svg>
          </button>
          {logOpen && (
            <div className="qa-log-dropdown" onClick={(e) => e.stopPropagation()}>
              {sessions.length === 0 && <div className="qa-log-empty">暂无会话</div>}
              {sessions.map(s => (
                <button
                  key={s.id}
                  className={`qa-log-item ${currentSessionId === s.id ? 'active' : ''}`}
                  onMouseDown={(e) => { e.preventDefault(); restoreSession(s.id); setLogOpen(false) }}
                >
                  <span className="qa-log-item-title">{s.title || '新会话'}</span>
                  <span className="qa-log-item-time">{(s.created_at || '').slice(0, 10)}</span>
                </button>
              ))}
            </div>
          )}
        </div>
      </div>

      {/* 视图切换 Tab：对话 / 轨迹 */}
      {!empty && (
        <div className="qa-view-tabs" role="tablist">
          {[
            { id: 'chat', label: '对话' },
            { id: 'trajectory', label: '轨迹' },
          ].map(tab => (
            <button
              key={tab.id}
              type="button"
              role="tab"
              aria-selected={viewTab === tab.id}
              className={`qa-view-tab ${viewTab === tab.id ? 'active' : ''}`}
              onClick={() => setViewTab(tab.id)}
            >
              {tab.label}
            </button>
          ))}
        </div>
      )}

      {viewTab === 'trajectory' ? (
        <TrajectoryView messages={messages} onOpenSource={loadReference} />
      ) : (
      <div className="qa-messages" ref={bottomRef} onClick={onCiteClick}>
        {empty ? (
          <div className="qa-hero">
            <h1 className="qa-hero-title">
              <span className="hero-icon hero-avatar" dangerouslySetInnerHTML={{ __html: avatarHtml }} />
              库藏万象，知音楼宇
              <span className="qa-hero-badge">预览版</span>
            </h1>

            <div className="qa-meta-bar">
              <div className="qa-meta-item">
                <svg className="meta-icon" width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/></svg>
                <span>{KB_NAME}</span>
              </div>
              <button
                className="qa-meta-item"
                type="button"
                onClick={(e) => { e.stopPropagation(); setRetrievalOpen(o => !o) }}
                title="检索方式"
              >
                <svg className="meta-icon" width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><circle cx="11" cy="11" r="7"/><path d="m21 21-4.3-4.3"/></svg>
                <span>{currentRetrieval.label}</span>
                <svg className="meta-arrow" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round"><polyline points="6 9 12 15 18 9"></polyline></svg>
                {retrievalOpen && (
                  <div className="toolbar-dropdown toolbar-dropdown--down meta-dropdown" onClick={(e) => e.stopPropagation()}>
                    {RETRIEVAL_MODES.map(m => (
                      <button
                        key={m.key}
                        className={`toolbar-dropdown-item ${retrieval.key === m.key ? 'active' : ''}`}
                        onMouseDown={(e) => { e.preventDefault(); setRetrieval({ key: m.key, useVector: m.useVector, useRerank: m.useRerank }); setRetrievalOpen(false) }}
                      >
                        <span>{m.label}</span>
                        <span style={{ fontSize: 11, color: 'var(--label-caption)' }}>{m.desc}</span>
                      </button>
                    ))}
                  </div>
                )}
              </button>
              <button
                className="qa-meta-item"
                type="button"
                onClick={(e) => { e.stopPropagation(); setPersonaOpen(o => !o) }}
                title="回复模式"
              >
                <svg className="meta-icon" width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="m12 3-1.9 5.8a2 2 0 0 1-1.3 1.3L3 12l5.8 1.9a2 2 0 0 1 1.3 1.3L12 21l1.9-5.8a2 2 0 0 1 1.3-1.3L21 12l-5.8-1.9a2 2 0 0 1-1.3-1.3z"/></svg>
                <span>{currentPersona.label}</span>
                <svg className="meta-arrow" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round"><polyline points="6 9 12 15 18 9"></polyline></svg>
                {personaOpen && (
                  <div className="toolbar-dropdown toolbar-dropdown--down meta-dropdown" onClick={(e) => e.stopPropagation()}>
                    {PERSONAS.map(p => (
                      <button
                        key={p.key}
                        className={`toolbar-dropdown-item ${persona === p.key ? 'active' : ''}`}
                        onMouseDown={(e) => { e.preventDefault(); setPersona(p.key); setPersonaOpen(false) }}
                      >
                        <span>{p.label}</span>
                      </button>
                    ))}
                  </div>
                )}
              </button>
            </div>

            <div className="qa-big-input">
              <textarea
                ref={textareaRef}
                value={input}
                placeholder="描述你想要构建的内容"
                onChange={(e) => { setInput(e.target.value); autoGrow(e) }}
                onKeyDown={onKeyDown}
              />
              <div className="qa-toolbar">
                <div className="qa-toolbar-left">
                  <CmdMenu setCurrentPage={setCurrentPage} beginNewSession={beginNewSession} />
                </div>
                <div className="qa-toolbar-right">
                  {streaming && (
                    <button className="stop-btn" onClick={stop} title="停止生成">
                      <span className="stop-icon">■</span>
                    </button>
                  )}
                  <div className="toolbar-select-wrap">
                    <button
                      className="toolbar-select"
                      onClick={(e) => { e.stopPropagation(); setModelOpen(o => !o) }}
                    >
                      <span>{models.find(m => m.id === currentModel)?.name || currentModel || '选择模型'}</span>
                      <svg className="select-arrow" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round"><polyline points="6 9 12 15 18 9"></polyline></svg>
                    </button>
                    {modelOpen && (
                      <div className="toolbar-dropdown toolbar-dropdown--up" onClick={(e) => e.stopPropagation()}>
                        {models.map(m => (
                          <button
                            key={m.id}
                            className={`toolbar-dropdown-item ${currentModel === m.id ? 'active' : ''}`}
                            onMouseDown={async (e) => {
                              e.preventDefault()
                              try {
                                await switchModel(m.id)
                              } catch (err) {
                                console.error('切换模型失败:', err)
                              }
                              setModelOpen(false)
                            }}
                          >
                            <span>{m.name}</span>
                            {m.desc && <span style={{ fontSize: 11, color: 'var(--label-caption)' }}>{m.desc}</span>}
                          </button>
                        ))}
                      </div>
                    )}
                  </div>
                  <button className="send-btn-round" onClick={() => submit()} title="发送">
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
                      <line x1="12" y1="19" x2="12" y2="5"></line>
                      <polyline points="5 12 12 5 19 12"></polyline>
                    </svg>
                  </button>
                </div>
              </div>
            </div>
          </div>
        ) : (
          messages.map((m, i) => {
            const isLast = i === messages.length - 1
            const isLive = isLast && streaming && m.role === 'assistant'
            const wl = m.worklog
            const retrievalLabel = wl
              ? (RETRIEVAL_MODES.find(x => x.key === wl.retrievalKey)?.label || currentRetrieval.label)
              : currentRetrieval.label
            const personaLabel = wl
              ? (PERSONAS.find(x => x.key === wl.personaKey)?.label || currentPersona.label)
              : currentPersona.label
            return (
              <div key={i} className={`msg msg-${m.role}`}>
                {m.role === 'assistant' && (
                  <div className="msg-avatar" dangerouslySetInnerHTML={{ __html: avatarHtml }} />
                )}
                <div className="msg-body">
                  {m.role === 'assistant' && (isLive || wl) && (
                    <WorkCard
                      live={isLive}
                      stage={stage}
                      stageContext={stageContext}
                      worklog={wl}
                      retrievalLabel={retrievalLabel}
                      personaLabel={personaLabel}
                      model={currentModel}
                      useVector={retrieval.useVector}
                      useRerank={retrieval.useRerank}
                      autoExpandSources={settings.auto_expand_sources !== false}
                    />
                  )}
                  <div
                    className="msg-content markdown"
                    dangerouslySetInnerHTML={{ __html: renderAnswer(m.content) }}
                  />
                  {m.role === 'assistant' && isLast && sources.length > 0 && (
                    <div className="msg-sources">
                      {sources.map((s, j) => (
                        <button
                          key={j}
                          className="msg-source-chip"
                          onClick={() => loadReference(s)}
                        >
                          [{s.marker}] {s.title}
                        </button>
                      ))}
                    </div>
                  )}
                </div>
              </div>
            )
          })
        )}
      </div>
      )}

      {/* 非空状态下的输入框（底部固定） */}
      {!empty && (
        <div className="qa-composer">
          <div className="chat-input">
            <textarea
              ref={textareaRef}
              value={input}
              rows={1}
              placeholder="输入问题，Enter 发送，Shift+Enter 换行..."
              onChange={(e) => { setInput(e.target.value); autoGrow(e) }}
              onKeyDown={onKeyDown}
            />
            <div className="chat-input-bar">
              <div className="chat-input-actions">
              <CmdMenu setCurrentPage={setCurrentPage} beginNewSession={beginNewSession} />
              <button className="input-action-btn" onClick={openReferences} title="查看引用">引用</button>
                <div className="persona-select-wrap">
                  <button
                    className={`persona-select ${streaming ? 'disabled' : ''}`}
                    disabled={streaming}
                    onClick={(e) => { e.stopPropagation(); if (!streaming) setPersonaOpen(o => !o) }}
                  >
                    <span className="persona-select-label">{currentPersona.label}</span>
                    <svg className="persona-select-arrow" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round"><polyline points="6 9 12 15 18 9"></polyline></svg>
                  </button>
                  {personaOpen && (
                    <div className="persona-dropdown" onClick={(e) => e.stopPropagation()}>
                      {PERSONAS.map(p => (
                        <button
                          key={p.key}
                          className={`persona-dropdown-item ${persona === p.key ? 'active' : ''}`}
                          onMouseDown={(e) => { e.preventDefault(); setPersona(p.key); setPersonaOpen(false) }}
                        >
                          {p.label}
                        </button>
                      ))}
                    </div>
                  )}
                </div>
              </div>
              <div className="chat-input-actions">
                <div className="toolbar-select-wrap">
                  <button
                    className="toolbar-select"
                    onClick={(e) => { e.stopPropagation(); setModelOpen(o => !o) }}
                  >
                    <span>{models.find(m => m.id === currentModel)?.name || currentModel || '选择模型'}</span>
                    <svg className="select-arrow" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round"><polyline points="6 9 12 15 18 9"></polyline></svg>
                  </button>
                  {modelOpen && (
                    <div className="toolbar-dropdown toolbar-dropdown--up" onClick={(e) => e.stopPropagation()}>
                      {models.map(m => (
                        <button
                          key={m.id}
                          className={`toolbar-dropdown-item ${currentModel === m.id ? 'active' : ''}`}
                          onMouseDown={async (e) => {
                            e.preventDefault()
                            try {
                              await switchModel(m.id)
                            } catch (err) {
                              console.error('切换模型失败:', err)
                            }
                            setModelOpen(false)
                          }}
                        >
                          <span>{m.name}</span>
                          {m.desc && <span style={{ fontSize: 11, color: 'var(--label-caption)' }}>{m.desc}</span>}
                        </button>
                      ))}
                    </div>
                  )}
                </div>
                <button
                  className={streaming ? 'stop-btn' : 'send-btn'}
                  onClick={streaming ? stop : () => submit()}
                  title={streaming ? '停止生成' : '发送'}
                >
                  {streaming
                    ? <span className="stop-icon">■</span>
                    : <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round"><line x1="22" y1="2" x2="11" y2="13"></line><polygon points="22 2 15 22 11 13 2 9"></polygon></svg>}
                </button>
              </div>
            </div>
          </div>
          <div className="qa-statusbar">
            <span className="status-item">
              <span className="status-key">轮数</span>
              <span className="status-val">{rounds}</span>
              <span className="status-sep">·</span>
              <span className="status-key">步数</span>
              <span className="status-val">{stepInfo}</span>
            </span>
            <span className="status-item">
              <span className="status-key">LLM</span>
              <span className="status-val">{streaming ? `${elapsed.toFixed(1)}s` : (lastElapsedRef.current ? `${lastElapsedRef.current.toFixed(1)}s` : '—')}</span>
              {lastUsage && lastUsage.total > 0 && (
                <span className="status-val status-tokens">{lastUsage.total.toLocaleString()} tokens</span>
              )}
            </span>
            {cacheHit && (
              <span className="status-item status-cache">
                <span className="status-key">缓存</span>
                <span className="status-val">命中</span>
              </span>
            )}
            <span className="status-item status-model">
              <span className="status-key">模型</span>
              <span className="status-val">{models.find(m => m.id === currentModel)?.name || currentModel || '—'}</span>
            </span>
          </div>
          <div className="input-hint">AI 生成内容仅供参考，请结合实际情况判断</div>
        </div>
      )}

      {/* 引用弹层：列出本次回答引用的文件，点击查看内容 */}
      {refOpen && (
        <div className="ref-overlay" onClick={() => { setRefOpen(false); setRefDetail(null) }}>
          <div className="ref-modal" onClick={(e) => e.stopPropagation()}>
            <div className="ref-head">
              <span className="ref-title">{refDetail ? '文档内容' : '引用文件'}</span>
              <button className="ref-close" onClick={() => { setRefOpen(false); setRefDetail(null) }} title="关闭">×</button>
            </div>
            {refDetail ? (
              <div className="ref-body">
                <button className="ref-back" onClick={() => setRefDetail(null)}>← 返回列表</button>
                <div className="ref-doc-title">{refDetail.title}</div>
                <div className="ref-content">{refLoading ? '加载中…' : refDetail.content}</div>
              </div>
            ) : sources.length === 0 ? (
              <div className="ref-empty">暂无引用文件<br />提问后在这里查看回答引用了哪些资料</div>
            ) : (
              <div className="ref-list">
                {sources.map((s, j) => (
                  <button key={j} className="ref-item" onClick={() => loadReference(s)}>
                    <span className="ref-marker">[{s.marker}]</span>
                    <span className="ref-item-title">{s.title}</span>
                    {s.score > 0 && <span className="ref-score">{Math.round(s.score * 100)}%</span>}
                  </button>
                ))}
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  )
}

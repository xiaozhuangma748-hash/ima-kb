// QA 会话共享状态：当前消息、引用来源、avatar、会话管理
// 支持多会话后台续跑：切换/新建会话不中断进行中的生成，
// 每个会话维护独立的消息缓冲与流状态，切回时展示最新结果。
import React, { createContext, useCallback, useContext, useEffect, useRef, useState } from 'react'
import { api, streamQA } from '../api.js'
import { createSession, updateSession, loadSessions } from './sessions.js'

const QACtx = createContext(null)

export const RETRIEVAL_MODES = [
  { key: 'mixed', label: '智能混合', desc: '向量 + 关键词 · LLM 重排序', useVector: true, useRerank: true },
  { key: 'hybrid', label: '混合检索', desc: '向量 + 关键词 · 不重排序', useVector: true, useRerank: false },
  { key: 'keyword', label: '关键词检索', desc: '仅 BM25 · LLM 重排序', useVector: false, useRerank: true },
  { key: 'keyword_fast', label: '关键词快速', desc: '仅 BM25 · 不重排序', useVector: false, useRerank: false },
]

export function useQA() {
  const ctx = useContext(QACtx)
  if (!ctx) throw new Error('useQA 必须在 QAProvider 内使用')
  return ctx
}

const STAGES = [
  { key: '检索', label: '检索知识库' },
  { key: '重排', label: '精选参考资料' },
  { key: '注入', label: '上下文注入' },
  { key: '生成', label: '生成回答' },
]

export function QAProvider({ settings, children }) {
  const [messages, setMessages] = useState([])          // 当前查看会话的消息视图
  const [sources, setSources] = useState([])            // 当前查看会话的引用来源
  const [activeMarker, setActiveMarker] = useState(null)
  const [avatarHtml, setAvatarHtml] = useState(
    // 初始即为已上传头像图片，避免先显示 SVG 后又切换成 img 的闪烁
    `<img class="avatar-img" src="/static/avatar.gif" alt="AI">`
  )
  const [sessions, setSessions] = useState(() => loadSessions())
  const [currentSessionId, setCurrentSessionId] = useState(null)
  const [persona, setPersona] = useState('neutral')
  // 检索方式：{key, useVector, useRerank} — 默认智能混合（向量+BM25+重排序）
  const [retrieval, setRetrieval] = useState({ key: 'mixed', useVector: true, useRerank: true })
  const [streamStates, setStreamStates] = useState({})  // {sid: {streaming, stage, context}}
  // 模型选择：全局共享，QA 顶部下拉与设置-模型管理保持同步
  const [models, setModels] = useState([])
  const [currentModel, setCurrentModel] = useState('')
  // 最近一次 LLM 的 token 用量（状态栏展示），随 usage 事件更新
  const [lastUsage, setLastUsage] = useState(null)

  const currentSessionIdRef = useRef(currentSessionId)
  currentSessionIdRef.current = currentSessionId

  // 各会话的实时消息缓冲、进行中的流、引用来源（后台会话不随视图丢失）
  const liveRef = useRef({})        // {sid: messages[]}
  const streamsRef = useRef({})     // {sid: {controller}}
  const liveSourcesRef = useRef({}) // {sid: sources[]}
  const liveInjectRef = useRef({})  // {sid: 注入清单{history_count, has_memory, has_summary, sources_count}}
  const liveRetrievalRef = useRef({})  // {sid: 检索清单{sources:[{source,score,...}]}}
  const liveLogsRef = useRef({})    // {sid: 英文运行日志行[]}，后端 log 事件为全量快照，直接覆盖
  const liveUsageRef = useRef({})   // {sid: {input, output, total}}，LLM token 用量

  // 派生当前查看会话的流状态
  const currentStream = currentSessionId ? streamStates[currentSessionId] : null
  const streaming = !!(currentStream && currentStream.streaming)
  const stage = currentStream ? currentStream.stage : null
  const stageContext = currentStream ? currentStream.context : null
  const streamingSessionIds = Object.keys(streamStates).filter(sid => streamStates[sid].streaming)

  // 加载头像（设置里上传/删除后调用 reloadAvatar 立即刷新各处头像）
  const reloadAvatar = useCallback(() => {
    api.avatar().then(d => {
      // 有自定义头像用之，否则回退默认 avatar.gif
      const src = d.avatar_url || '/static/avatar.gif'
      setAvatarHtml(`<img class="avatar-img" src="${src}?t=${Date.now()}" alt="AI">`)
    }).catch(() => {})
  }, [])
  useEffect(() => { reloadAvatar() }, [reloadAvatar])

  const beginNewSession = useCallback(() => {
    // 不中断任何后台流
    setCurrentSessionId(null)
    setMessages([])
    setSources([])
    setActiveMarker(null)
  }, [])

  const restoreSession = useCallback((sid) => {
    const s = loadSessions().find(x => x.id === sid)
    if (!s) return
    setCurrentSessionId(sid)
    const buf = liveRef.current[sid]
    const msgs = buf ? buf : (s.messages || [])
    setMessages(msgs)
    // sources 优先取内存（流式中的会话），否则从最后一条带 worklog 的回答恢复（刷新后引用仍可点开）
    let srcs = liveSourcesRef.current[sid] || null
    if (!srcs) {
      for (let i = msgs.length - 1; i >= 0; i--) {
        if (msgs[i].worklog?.sources?.length) { srcs = msgs[i].worklog.sources; break }
      }
    }
    setSources(srcs || [])
    setActiveMarker(null)
    // 从最后一条带 worklog.usage 的回答恢复 token 用量（刷新后状态栏仍显示）
    for (let i = msgs.length - 1; i >= 0; i--) {
      if (msgs[i].worklog?.usage) { setLastUsage(msgs[i].worklog.usage); return }
    }
    setLastUsage(null)
  }, [])

  const deleteSession = useCallback((sid) => {
    const remaining = loadSessions().filter(x => x.id !== sid)
    try { localStorage.setItem('ima_kb.sessions.v1', JSON.stringify(remaining)) } catch {}
    setSessions(remaining)
    delete liveRef.current[sid]
    delete streamsRef.current[sid]
    delete liveSourcesRef.current[sid]
    delete liveRetrievalRef.current[sid]
    setStreamStates(prev => { const c = { ...prev }; delete c[sid]; return c })
    if (currentSessionId === sid) {
      setCurrentSessionId(null)
      setMessages([])
      setSources([])
    }
  }, [currentSessionId])

  const send = useCallback((text, opts = {}) => {
    const trimmed = (text || '').trim()
    if (!trimmed) return
    // 流式输出开关：关闭时后端仍走流式，但前端不逐字渲染，等生成结束一次性写入完整答案
    const streamMode = opts.streaming !== false

    // 归属会话：复用当前会话，否则新建
    let sid = currentSessionId
    const base = sid
      ? (liveRef.current[sid] || loadSessions().find(x => x.id === sid)?.messages || [])
      : []
    // 发送即插入空的 assistant 占位消息，让"工作过程"在检索/重排/注入阶段（首个 token 到达前）就出现
    // createdAt 供轨迹视图显示每轮问答时间
    const newMessages = [
      ...base,
      { role: 'user', content: trimmed, createdAt: new Date().toISOString() },
      { role: 'assistant', content: '', worklog: null, createdAt: new Date().toISOString() },
    ]
    if (!sid) {
      const created = createSession(newMessages)
      sid = created.id
      setCurrentSessionId(sid)
      setSessions(loadSessions())
      // 新会话必然成为当前视图，立即展示用户消息 + 工作过程占位
      setMessages(newMessages)
    } else if (sid === currentSessionIdRef.current) {
      setMessages(newMessages)
    }

    liveRef.current[sid] = newMessages
    updateSession(sid, { messages: newMessages })
    setSessions(loadSessions())

    // 同一会话若已有进行中的流，先中止它（不牵连其他会话）
    const existing = streamsRef.current[sid]
    if (existing) existing.controller.abort()

    const controller = new AbortController()
    streamsRef.current[sid] = { controller }

    setStreamStates(prev => ({ ...prev, [sid]: { streaming: true, stage: { idx: 0, label: '检索', count: 0 }, context: null } }))
    setSources([])
    setActiveMarker(null)

    const history = newMessages.slice(-20)

    streamQA({
      question: trimmed,
      history,
      persona,
      useVector: retrieval.useVector,
      useRerank: retrieval.useRerank,
      signal: controller.signal,
      onStage: (key, count, context) => {
        if (!streamsRef.current[sid]) return
        const i = STAGES.findIndex(s => s.key === key)
        // 注入阶段携带注入清单（历史条数/记忆/摘要/片段数），供生成结束后写进 worklog
        if (key === '注入' && context) liveInjectRef.current[sid] = context
        // 检索阶段携带候选来源列表（含 source 类型），供生成结束后写进 worklog，展示来源分布
        if (key === '检索' && context) liveRetrievalRef.current[sid] = context
        setStreamStates(prev => ({
          ...prev,
          [sid]: {
            streaming: true,
            // 未知 stage（如"缓存"）保留原始 key 作为 label，用于命中提示
            stage: { idx: i === -1 ? 0 : i, label: i === -1 ? key : STAGES[i].label, count },
            context: context || prev[sid]?.context || null,
          },
        }))
      },
      onLog: (logs) => {
        // 后端每次发全量日志快照，直接覆盖；轨迹视图与排查都以此为准
        if (!streamsRef.current[sid]) return
        liveLogsRef.current[sid] = logs
      },
      onUsage: (usage) => {
        // LLM token 用量，供状态栏展示真实 token 数
        if (!streamsRef.current[sid]) return
        liveUsageRef.current[sid] = usage
        setLastUsage(usage)
      },
      onToken: (t) => {
        if (!streamsRef.current[sid]) return
        // 非流式：不逐字追加，保留空占位，等 onDone 一次性写入完整答案
        if (!streamMode) return
        const buf = liveRef.current[sid] || []
        const next = buf.slice()
        const last = next[next.length - 1]
        // 首个 token：占位 assistant 消息尚为空，需要切到"生成"阶段
        const isFirstToken = !(last && last.role === 'assistant' && last.content)
        if (last && last.role === 'assistant') {
          next[next.length - 1] = { role: 'assistant', content: last.content + t, worklog: last.worklog || null }
        } else {
          next.push({ role: 'assistant', content: t })
        }
        if (isFirstToken) {
          // 后端在生成阶段不再发 stage 事件，这里手动把阶段切到"生成"，
          // 让思考卡片从"正在检索/重排/注入"更新为"正在生成回答"
          const g = STAGES.findIndex(s => s.key === '生成')
          setStreamStates(prev => ({
            ...prev,
            [sid]: { streaming: true, stage: { idx: g === -1 ? 0 : g, label: '生成', count: 0 } },
          }))
        }
        liveRef.current[sid] = next
        if (sid === currentSessionIdRef.current) setMessages(next)
      },
      onDone: (parsed) => {
        if (!streamsRef.current[sid]) return
        delete streamsRef.current[sid]
        const answer = parsed.answer || ''
    const srcs = Array.isArray(parsed.citations)
      ? parsed.citations.map(c => ({
          marker: c.marker,
          title: c.title,
          doc_id: c.doc_id,
          snippet: c.preview || c.snippet || '',
          paragraph_num: c.paragraph_num,
          score: (parsed.sources || []).find(s => s.doc_id === c.doc_id)?.score || 0,
        }))
      : (parsed.sources || []).map(s => ({
          marker: s.marker || 'r1',
          title: s.doc_title || s.title || '未命名',
          doc_id: s.doc_id,
          snippet: s.preview || s.snippet || '',
          paragraph_num: s.paragraph_num,
          score: s.score || 0,
        }))
    // 工作过程快照：随回答一起保留，供生成结束后仍显示在回复上方
    const inject = liveInjectRef.current[sid] || null
    delete liveInjectRef.current[sid]
    const retrievalMeta = liveRetrievalRef.current[sid] || null
    delete liveRetrievalRef.current[sid]
    const runLogs = liveLogsRef.current[sid] || []
    delete liveLogsRef.current[sid]
    const usage = liveUsageRef.current[sid] || null
    delete liveUsageRef.current[sid]
    const worklog = {
      sources: srcs,
      personaKey: persona,
      retrievalKey: retrieval.key,
      retrievalMeta,
      history: (history || []).slice(-10),
      inject,
      logs: runLogs,
      usage,
    }
    const buf = liveRef.current[sid] || []
    const next = buf.slice()
    const last = next[next.length - 1]
    if (last && last.role === 'assistant') {
      next[next.length - 1] = { role: 'assistant', content: answer, worklog }
    } else {
      next.push({ role: 'assistant', content: answer, worklog })
    }
    liveRef.current[sid] = next
    updateSession(sid, { messages: next })
    setSessions(loadSessions())
    liveSourcesRef.current[sid] = srcs
        if (sid === currentSessionIdRef.current) {
          setMessages(next)
          setSources(srcs)
        }
        setStreamStates(prev => { const c = { ...prev }; delete c[sid]; return c })
      },
      onError: (msg) => {
        if (!streamsRef.current[sid]) return
        delete streamsRef.current[sid]
        const buf = liveRef.current[sid] || []
        const next = buf.slice()
        const last = next[next.length - 1]
        // 若最后是占位 assistant（空内容），就地替换为错误消息，避免残留空白占位
        if (last && last.role === 'assistant' && !last.content) {
          next[next.length - 1] = { role: 'assistant', content: `错误: ${msg}` }
        } else {
          next.push({ role: 'assistant', content: `错误: ${msg}` })
        }
        liveRef.current[sid] = next
        updateSession(sid, { messages: next })
        setSessions(loadSessions())
        if (sid === currentSessionIdRef.current) setMessages(next)
        setStreamStates(prev => { const c = { ...prev }; delete c[sid]; return c })
      },
    })
  }, [persona, currentSessionId, retrieval])

  const stop = useCallback(() => {
    const sid = currentSessionId
    const stream = sid && streamsRef.current[sid]
    if (!stream) return
    stream.controller.abort()
    delete streamsRef.current[sid]
    const buf = liveRef.current[sid]
    if (buf && buf.length) {
      const next = buf.slice()
      const last = next[next.length - 1]
      // 若最后是空的占位 assistant（还没等到任何 token），移除它，避免留空白气泡
      if (last && last.role === 'assistant' && !last.content) next.pop()
      liveRef.current[sid] = next
      updateSession(sid, { messages: next })
      setSessions(loadSessions())
      if (sid === currentSessionIdRef.current) setMessages(next)
    }
    setStreamStates(prev => { const c = { ...prev }; delete c[sid]; return c })
  }, [currentSessionId])

  const loadModels = useCallback(() => {
    api.getModels().then(data => {
      setModels(data.models || [])
      setCurrentModel(data.current || '')
    }).catch(() => {})
  }, [])

  const switchModel = useCallback(async (id) => {
    const data = await api.setModel(id)
    setCurrentModel(data.model)
    return data.model
  }, [])

  const value = {
    messages, streaming, stage, stageContext, sources, activeMarker, avatarHtml, reloadAvatar,
    persona, setPersona, retrieval, setRetrieval, sessions, currentSessionId, streamingSessionIds,
    beginNewSession, restoreSession, deleteSession, send, stop,
    models, currentModel, loadModels, switchModel, lastUsage,
    highlightMarker: setActiveMarker,
  }

  return <QACtx.Provider value={value}>{children}</QACtx.Provider>
}
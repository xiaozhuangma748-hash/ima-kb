// QA 会话共享状态：当前消息、引用来源、avatar、会话管理
// 支持多会话后台续跑：切换/新建会话不中断进行中的生成，
// 每个会话维护独立的消息缓冲与流状态，切回时展示最新结果。
import React, { createContext, useCallback, useContext, useEffect, useRef, useState } from 'react'
import { api, streamQA } from '../api.js'
import { createSession, updateSession, loadSessions } from './sessions.js'

const QACtx = createContext(null)

export function useQA() {
  const ctx = useContext(QACtx)
  if (!ctx) throw new Error('useQA 必须在 QAProvider 内使用')
  return ctx
}

const ROBOT_AVATAR_SVG = `<svg viewBox="0 0 32 32" fill="none" xmlns="http://www.w3.org/2000/svg">
  <defs><linearGradient id="avaGrad" x1="0" y1="0" x2="32" y2="32" gradientUnits="userSpaceOnUse">
    <stop stop-color="#4A8AC4"/><stop offset="1" stop-color="#6799FE"/>
  </linearGradient></defs>
  <rect width="32" height="32" rx="8" fill="url(#avaGrad)"/>
  <path d="M9 11C9 9.895 9.895 9 11 9H21C22.105 9 23 9.895 23 11V18C23 19.105 22.105 20 21 20H15.5L12 23.5V20H11C9.895 20 9 19.105 9 18V11Z" fill="#fff"/>
  <circle cx="14" cy="14.5" r="1.4" fill="#4A8AC4"/>
  <circle cx="18" cy="14.5" r="1.4" fill="#4A8AC4"/>
</svg>`

const STAGES = [
  { key: '检索', label: '检索知识库' },
  { key: '重排', label: '精选参考资料' },
  { key: '生成', label: '生成回答' },
]

export function QAProvider({ settings, children }) {
  const [messages, setMessages] = useState([])          // 当前查看会话的消息视图
  const [sources, setSources] = useState([])            // 当前查看会话的引用来源
  const [activeMarker, setActiveMarker] = useState(null)
  const [avatarHtml, setAvatarHtml] = useState(ROBOT_AVATAR_SVG)
  const [sessions, setSessions] = useState(() => loadSessions())
  const [currentSessionId, setCurrentSessionId] = useState(null)
  const [persona, setPersona] = useState('neutral')
  const [streamStates, setStreamStates] = useState({})  // {sid: {streaming, stage}}

  const currentSessionIdRef = useRef(currentSessionId)
  currentSessionIdRef.current = currentSessionId

  // 各会话的实时消息缓冲、进行中的流、引用来源（后台会话不随视图丢失）
  const liveRef = useRef({})        // {sid: messages[]}
  const streamsRef = useRef({})     // {sid: {controller}}
  const liveSourcesRef = useRef({}) // {sid: sources[]}

  // 派生当前查看会话的流状态
  const currentStream = currentSessionId ? streamStates[currentSessionId] : null
  const streaming = !!(currentStream && currentStream.streaming)
  const stage = currentStream ? currentStream.stage : null
  const streamingSessionIds = Object.keys(streamStates).filter(sid => streamStates[sid].streaming)

  // 加载头像
  useEffect(() => {
    api.avatar().then(d => {
      if (d.avatar_url) {
        setAvatarHtml(`<img class="avatar-img" src="${d.avatar_url}?t=${Date.now()}" alt="AI">`)
      }
    }).catch(() => {})
  }, [])

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
    setMessages(buf ? buf : (s.messages || []))
    setSources(liveSourcesRef.current[sid] || [])
    setActiveMarker(null)
  }, [])

  const deleteSession = useCallback((sid) => {
    const remaining = loadSessions().filter(x => x.id !== sid)
    try { localStorage.setItem('ima_kb.sessions.v1', JSON.stringify(remaining)) } catch {}
    setSessions(remaining)
    delete liveRef.current[sid]
    delete streamsRef.current[sid]
    delete liveSourcesRef.current[sid]
    setStreamStates(prev => { const c = { ...prev }; delete c[sid]; return c })
    if (currentSessionId === sid) {
      setCurrentSessionId(null)
      setMessages([])
      setSources([])
    }
  }, [currentSessionId])

  const send = useCallback((text) => {
    const trimmed = (text || '').trim()
    if (!trimmed) return

    // 归属会话：复用当前会话，否则新建
    let sid = currentSessionId
    const base = sid
      ? (liveRef.current[sid] || loadSessions().find(x => x.id === sid)?.messages || [])
      : []
    const newMessages = [...base, { role: 'user', content: trimmed }]
    if (!sid) {
      const created = createSession([{ role: 'user', content: trimmed }])
      sid = created.id
      setCurrentSessionId(sid)
      setSessions(loadSessions())
      // 新会话必然成为当前视图，立即展示用户消息
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

    setStreamStates(prev => ({ ...prev, [sid]: { streaming: true, stage: { idx: 0, label: '检索', count: 0 } } }))
    setSources([])
    setActiveMarker(null)

    const history = newMessages.slice(-20)

    streamQA({
      question: trimmed,
      history,
      persona,
      signal: controller.signal,
      onStage: (key, count) => {
        if (!streamsRef.current[sid]) return
        const i = STAGES.findIndex(s => s.key === key)
        setStreamStates(prev => ({
          ...prev,
          [sid]: { streaming: true, stage: { idx: i === -1 ? 0 : i, label: STAGES[i === -1 ? 0 : i].label, count } },
        }))
      },
      onToken: (t) => {
        if (!streamsRef.current[sid]) return
        const buf = liveRef.current[sid] || []
        const next = buf.slice()
        const last = next[next.length - 1]
        if (last && last.role === 'assistant') {
          next[next.length - 1] = { role: 'assistant', content: last.content + t }
        } else {
          next.push({ role: 'assistant', content: t })
        }
        liveRef.current[sid] = next
        if (sid === currentSessionIdRef.current) setMessages(next)
      },
      onDone: (parsed) => {
        if (!streamsRef.current[sid]) return
        delete streamsRef.current[sid]
        const answer = parsed.answer || ''
        const buf = liveRef.current[sid] || []
        const next = buf.slice()
        const last = next[next.length - 1]
        if (last && last.role === 'assistant') {
          next[next.length - 1] = { role: 'assistant', content: answer }
        } else {
          next.push({ role: 'assistant', content: answer })
        }
        liveRef.current[sid] = next
        updateSession(sid, { messages: next })
        setSessions(loadSessions())
        const srcs = Array.isArray(parsed.citations)
          ? parsed.citations.map(c => ({
              marker: c.marker,
              title: c.title,
              snippet: '',
              score: (parsed.sources || []).find(s => s.doc_id === c.doc_id)?.score || 0,
            }))
          : (parsed.sources || [])
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
        const next = [...buf, { role: 'assistant', content: `错误: ${msg}` }]
        liveRef.current[sid] = next
        updateSession(sid, { messages: next })
        setSessions(loadSessions())
        if (sid === currentSessionIdRef.current) setMessages(next)
        setStreamStates(prev => { const c = { ...prev }; delete c[sid]; return c })
      },
    })
  }, [persona, currentSessionId])

  const stop = useCallback(() => {
    const sid = currentSessionId
    const stream = sid && streamsRef.current[sid]
    if (!stream) return
    stream.controller.abort()
    delete streamsRef.current[sid]
    const buf = liveRef.current[sid]
    if (buf && buf.length) {
      updateSession(sid, { messages: buf })
      setSessions(loadSessions())
    }
    setStreamStates(prev => { const c = { ...prev }; delete c[sid]; return c })
  }, [currentSessionId])

  const value = {
    messages, streaming, stage, sources, activeMarker, avatarHtml,
    persona, setPersona, sessions, currentSessionId, streamingSessionIds,
    beginNewSession, restoreSession, deleteSession, send, stop,
    highlightMarker: setActiveMarker,
  }

  return <QACtx.Provider value={value}>{children}</QACtx.Provider>
}
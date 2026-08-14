import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useQA } from '../store/qa.jsx'
import { api } from '../api.js'

const PERSONAS = [
  { key: 'neutral', label: '综合模式', icon: '🤖' },
  { key: 'scholar', label: '深度分析模式', icon: '🎓' },
  { key: 'warrior', label: '直接行动模式', icon: '⚔️' },
  { key: 'artisan', label: '结构化模式', icon: '🔧' },
]

const SUGGESTIONS = [
  { icon: '🌿', text: '骨灰安置有哪些生态安葬方式？' },
  { icon: '💰', text: '殡葬服务收费标准是什么？' },
  { icon: '📰', text: '杭州市殡葬改革最新政策？' },
]

const STEPS = [
  { key: '检索', label: '检索知识库' },
  { key: '重排', label: '精选参考资料' },
  { key: '生成', label: '生成回答' },
]

function renderAnswer(content) {
  if (typeof marked === 'undefined') return content
  let html = marked.parse(content || '')
  html = html.replace(/\[(\d+)\]\(?(?!\w)/g, (_, n) =>
    `<span class="citation" data-marker="[${n}]">[${n}]</span>`
  )
  return html
}

export default function QaPage({ settings }) {
  const {
    messages, streaming, stage, avatarHtml, persona, setPersona,
    send, stop, beginNewSession, sources, highlightMarker,
  } = useQA()
  const [input, setInput] = useState('')
  const [rows, setRows] = useState(1)
  const [personaOpen, setPersonaOpen] = useState(false)
  const textareaRef = useRef(null)
  const bottomRef = useRef(null)
  const messagesRef = useRef(messages)
  messagesRef.current = messages

  const showSuggestions = settings.show_suggestions !== false

  // 消息区自动滚动
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' })
  }, [messages, stage])

  const autoGrow = (e) => {
    const el = e.target
    el.style.height = 'auto'
    el.style.height = Math.min(el.scrollHeight, 200) + 'px'
    setRows(undefined)
  }

  const submit = (text) => {
    const t = (text ?? input).trim()
    if (!t) return
    setInput('')
    send(t) // 生成中会先中断当前任务，再发新消息
    if (textareaRef.current) textareaRef.current.style.height = 'auto'
  }

  const onKeyDown = (e) => {
    // 回车直接发送；Shift+Enter 换行
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      submit()
    }
  }

  const empty = messages.length === 0 && !streaming

  const onCiteClick = (e) => {
    const cite = e.target.closest('.citation')
    if (cite) {
      highlightMarker(cite.dataset.marker || cite.textContent.trim())
    }
  }

  return (
    <div className="qa-page">
      <div className="qa-messages" ref={bottomRef} onClick={onCiteClick}>
        {empty ? (
          <div className="qa-hero">
            <div className="qa-hero-mark">IMA</div>
            <h1 className="qa-hero-title">今天有什么想了解的？</h1>
            <p className="qa-hero-sub">基于知识库的 RAG 问答 · 带引用溯源</p>
            {showSuggestions && (
              <div className="qa-suggestions">
                {SUGGESTIONS.map((s, i) => (
                  <button key={i} className="qa-suggestion-chip" onClick={() => submit(s.text)}>
                    <span className="chip-icon">{s.icon}</span>
                    <span>{s.text}</span>
                  </button>
                ))}
              </div>
            )}
          </div>
        ) : (
          messages.map((m, i) => (
            <div key={i} className={`msg msg-${m.role}`}>
              {m.role === 'assistant' && (
                <div className="msg-avatar" dangerouslySetInnerHTML={{ __html: avatarHtml }} />
              )}
              <div className="msg-body">
                <div
                  className="msg-content markdown"
                  dangerouslySetInnerHTML={{ __html: renderAnswer(m.content) }}
                />
                {m.role === 'assistant' && i === messages.length - 1 && sources.length > 0 && (
                  <div className="msg-sources">
                    {sources.map((s, j) => (
                      <button
                        key={j}
                        className="msg-source-chip"
                        onClick={() => highlightMarker(s.marker)}
                      >
                        [{s.marker}] {s.title}
                      </button>
                    ))}
                  </div>
                )}
              </div>
            </div>
          ))
        )}

        {streaming && stage && (
          <div className="msg msg-assistant">
            <div className="msg-avatar" dangerouslySetInnerHTML={{ __html: avatarHtml }} />
            <div className="msg-body">
              <div className="ai-thinking">
                <span className="thinking-dots" aria-hidden="true">
                  <i className="thinking-dot" />
                  <i className="thinking-dot" />
                  <i className="thinking-dot" />
                </span>
                <span className="thinking-text">正在{stage.label}{stage.count ? ` (${stage.count})` : ''}</span>
                <span className="thinking-step">{stage.idx + 1}/{STEPS.length}</span>
              </div>
            </div>
          </div>
        )}
      </div>

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
            <div className="persona-inline">
              <span>模式</span>
              <div className="persona-select-wrap">
                <button
                  className="persona-select"
                  onClick={() => setPersonaOpen(o => !o)}
                  onBlur={() => setPersonaOpen(false)}
                >
                  <span className="persona-select-label">
                    {PERSONAS.find(p => p.key === persona)?.label || '通用模式'}
                  </span>
                  <svg className="persona-select-arrow" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round"><polyline points="6 9 12 15 18 9"></polyline></svg>
                </button>
                {personaOpen && (
                  <div className="persona-dropdown">
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
              <button className="input-action-btn" onClick={beginNewSession}>清空</button>
              {streaming && (
                <button className="stop-btn" onClick={stop} title="停止生成">
                  <span className="stop-icon">■</span>
                </button>
              )}
              <button className="send-btn" onClick={() => submit()} title="发送">
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round"><line x1="22" y1="2" x2="11" y2="13"></line><polygon points="22 2 15 22 11 13 2 9"></polygon></svg>
              </button>
            </div>
          </div>
        </div>
        <div className="input-hint">AI 生成内容仅供参考，请结合实际情况判断</div>
      </div>
    </div>
  )
}
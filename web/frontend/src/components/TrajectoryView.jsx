import React, { useState } from 'react'
import { RETRIEVAL_MODES } from '../store/qa.jsx'

const PERSONA_LABELS = {
  neutral: '综合模式',
  scholar: '深度分析模式',
  warrior: '直接行动模式',
  artisan: '结构化模式',
}

// 每个阶段一个主色，用于时间线节点与运行日志头部
const STEP_META = [
  { key: '检索', label: 'Retrieve', desc: '从知识库召回候选片段', color: '#4f8cff' },
  { key: '重排', label: 'Rerank', desc: '按相关度精选参考片段', color: '#8b7bff' },
  { key: '注入', label: 'Inject', desc: '组装历史、片段与记忆上下文', color: '#e0a23d' },
  { key: '生成', label: 'Generate', desc: 'LLM 流式生成回答', color: '#2fc48a' },
]

// 英文运行日志按前缀归类到对应阶段（query.route / cache 归入检索）
const LOG_GROUPERS = {
  '检索': m => /^(query\.route|retrieval\.|cache\.)/.test(m),
  '重排': m => /^rerank\./.test(m),
  '注入': m => /^(memory\.|prompt\.|inject\.)/.test(m),
  '生成': m => /^(llm\.|citation\.|done)/.test(m),
}

// 旧格式 [ 15.930s] msg → 统一为新格式结构 [HH:MM:SS.mmm | 相对秒s] msg
// 旧日志的绝对时钟时间不可回溯，用占位符 ??:??:??.??? 表示
function normalizeLogLine(line) {
  if (!line) return line
  if (/^\[\d{2}:\d{2}:\d{2}\.\d{3}\s*\|/.test(line)) return line // 已是新格式
  const old = line.match(/^\[\s*([\d.]+s)\]\s*(.*)$/)
  if (old) return `[??:??:??.??? | ${old[1].padStart(8, ' ')}] ${old[2]}`
  return line
}

// 把扁平日志行按阶段分组，返回 { '检索': [], '重排': [], '注入': [], '生成': [] }
function groupLogs(logs) {
  const groups = { '检索': [], '重排': [], '注入': [], '生成': [] }
  for (const rawLine of (logs || [])) {
    const line = normalizeLogLine(rawLine)
    const msg = line.replace(/^\[[^\]]*\]\s*/, '')
    for (const key of Object.keys(LOG_GROUPERS)) {
      if (LOG_GROUPERS[key](msg)) { groups[key].push(line); break }
    }
  }
  return groups
}

function formatTime(date) {
  if (!date) return ''
  const d = new Date(date)
  if (Number.isNaN(d.getTime())) return ''
  return d.toLocaleString('zh-CN', { month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit' })
}

function SourceItem({ s, onOpenSource }) {
  const [open, setOpen] = useState(false)
  return (
    <div className={`tr-source ${open ? 'open' : ''}`}>
      <div className="tr-source-head">
        <button type="button" className="tr-source-toggle" onClick={() => setOpen(o => !o)}>
          <svg className="tr-source-chevron" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round"><polyline points="6 9 12 15 18 9" /></svg>
        </button>
        <span className="tr-source-marker">[{s.marker || 'r'}]</span>
        <span className="tr-source-title" title={s.title}>{s.title}</span>
        {s.score > 0 && <span className="tr-source-score">{Math.round(s.score * 100)}%</span>}
        <button type="button" className="tr-source-open" onClick={() => onOpenSource && onOpenSource(s)} title="打开完整文档">打开</button>
      </div>
      {open && (
        <div className="tr-source-proof">
          {s.paragraph_num ? <span className="tr-source-para">§ 第 {s.paragraph_num} 段</span> : null}
          <p className="tr-source-snippet">{s.snippet || '（无命中片段）'}</p>
        </div>
      )}
    </div>
  )
}

function TurnCard({ index, userMsg, assistantMsg, onOpenSource }) {
  const [open, setOpen] = useState(true)
  const wl = assistantMsg?.worklog
  const retrievalLabel = RETRIEVAL_MODES.find(m => m.key === wl?.retrievalKey)?.label || '智能混合'
  const personaLabel = PERSONA_LABELS[wl?.personaKey] || '综合模式'
  const inject = wl?.inject || {}
  const sources = wl?.sources || []
  const logGroups = groupLogs(wl?.logs)

  return (
    <div className="tr-turn">
      <div className="tr-turn-card">
        <button type="button" className={`tr-turn-head ${open ? 'open' : ''}`} onClick={() => setOpen(o => !o)}>
          <span className="tr-turn-index">#{index + 1}</span>
          <span className="tr-turn-question" title={userMsg.content}>{userMsg.content}</span>
          <span className="tr-turn-meta">{formatTime(assistantMsg?.createdAt)}</span>
          <svg className="tr-turn-chevron" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><polyline points="6 9 12 15 18 9" /></svg>
        </button>
        {open && (
          <div className="tr-turn-body">
            <div className="tr-summary">
              <span className="tr-summary-item"><b>{retrievalLabel}</b><em>检索模式</em></span>
              <span className="tr-summary-item"><b>{personaLabel}</b><em>回复模式</em></span>
              <span className="tr-summary-item"><b>{sources.length}</b><em>引用</em></span>
              <span className="tr-summary-item"><b>{inject.sources_count ?? sources.length ?? 0}</b><em>片段</em></span>
              <span className="tr-summary-item"><b>{inject.history_count ?? wl?.history?.length ?? 0}</b><em>历史</em></span>
              {(inject.has_memory || inject.has_summary) && (
                <span className="tr-summary-item">
                  <b>{inject.has_memory ? '记忆 ' : ''}{inject.has_summary ? '摘要' : ''}</b><em>增强</em>
                </span>
              )}
            </div>

            <div className="tr-steps">
              {STEP_META.map(step => {
                const stepLogs = logGroups[step.key] || []
                return (
                  <div key={step.key} className="tr-step">
                    <span className="tr-step-dot" style={{ background: step.color }} />
                    <div className="tr-step-main-wrap">
                      <div className="tr-step-main">
                        <span className="tr-step-name">{step.label}</span>
                        <span className="tr-step-desc">{step.desc}</span>
                        {stepLogs.length > 0 && <span className="tr-step-count">{stepLogs.length} 条日志</span>}
                      </div>
                      {stepLogs.length > 0 && (
                        <div className="tr-step-log">
                          <div className="tr-log-head">
                            <span className="tr-log-dot" style={{ background: step.color }} />
                            <span className="tr-log-name">{step.label} · 运行日志</span>
                            <span className="tr-log-tag">terminal</span>
                          </div>
                          <pre className="tr-log-body">{stepLogs.join('\n')}</pre>
                        </div>
                      )}
                    </div>
                  </div>
                )
              })}
            </div>

            {sources.length > 0 && (
              <div className="tr-sources">
                <span className="tr-sources-title">引用文件 · 点击 ▶ 展开命中片段</span>
                <div className="tr-source-list">
                  {sources.map((s, j) => (
                    <SourceItem key={j} s={s} onOpenSource={onOpenSource} />
                  ))}
                </div>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  )
}

export default function TrajectoryView({ messages, onOpenSource }) {
  const turns = []
  for (let i = 0; i < messages.length - 1; i++) {
    const user = messages[i]
    const assistant = messages[i + 1]
    if (user.role === 'user' && assistant && assistant.role === 'assistant') {
      turns.push({ user, assistant, index: turns.length })
      i++
    }
  }

  if (turns.length === 0) {
    return (
      <div className="tr-empty">
        暂无轨迹<br />
        发送消息后，这里会记录每轮问答的完整工作过程
      </div>
    )
  }

  return (
    <div className="tr-root">
      <div className="tr-timeline">
        {turns.map(t => (
          <TurnCard
            key={t.index}
            index={t.index}
            userMsg={t.user}
            assistantMsg={t.assistant}
            onOpenSource={onOpenSource}
          />
        ))}
      </div>
    </div>
  )
}
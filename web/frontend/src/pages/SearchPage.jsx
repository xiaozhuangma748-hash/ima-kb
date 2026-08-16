import { useEffect, useRef, useState } from 'react'
import { api } from '../api.js'
import { Toggle } from '../ui/Base.jsx'
import { useToast } from '../ui/Toast.jsx'

function escapeReg(s) { return s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&') }

export default function SearchPage({ settings }) {
  // settings.use_vector / use_rerank 仅作开关初始值
  const { showToast } = useToast()
  const [q, setQ] = useState('')
  const [useVector, setUseVector] = useState(settings.use_vector !== false)
  const [useRerank, setUseRerank] = useState(settings.use_rerank !== false)
  const [state, setState] = useState('idle') // idle | loading | done | error
  const [results, setResults] = useState(null)
  const [countText, setCountText] = useState('输入关键词开始搜索')
  const abortRef = useRef(null)
  const inputRef = useRef(null)

  // 全局 "/" 快捷键跳转搜索
  useEffect(() => {
    const onKey = (e) => {
      if (e.key !== '/') return
      const tag = (e.target?.tagName || '').toLowerCase()
      if (tag === 'input' || tag === 'textarea') return
      e.preventDefault()
      inputRef.current?.focus()
    }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [])

  const doSearch = () => {
    const query = q.trim()
    if (!query || state === 'loading') return
    if (abortRef.current) abortRef.current.abort()
    const controller = new AbortController()
    abortRef.current = controller

    setState('loading')
    setCountText('搜索中...')
    setResults(null)

    const params = new URLSearchParams({ q: query, limit: '10', use_vector: String(useVector), use_rerank: String(useRerank) })

    fetch(`/api/search?${params.toString()}`, { signal: controller.signal })
      .then(r => r.json())
      .then(data => {
        setResults(data)
        setCountText(`找到 ${data.total} 个结果 · 用时 ${(data.time_ms / 1000).toFixed(2)} 秒`)
        setState('done')
      })
      .catch(err => {
        if (err.name === 'AbortError') return
        setState('error')
        setCountText('搜索失败')
        showToast('请求失败: ' + err.message, 'error')
      })
      .finally(() => { abortRef.current = null })
  }

  const highlightSnippet = (text) => {
    let snippet = text || ''
    const keywords = q.split(/\s+/).filter(k => k.length >= 2)
    for (const kw of keywords) {
      snippet = snippet.replace(new RegExp(escapeReg(kw), 'gi'), m => `<mark>${m}</mark>`)
    }
    return snippet
  }

  return (
    <div className="search-page">
      <div className="page-header">
        <div>
          <div className="page-title">🔍 搜索</div>
          <div className="page-subtitle">BM25 + 向量混合检索 · RRF 融合 · LLM 重排序</div>
        </div>
      </div>

      <div className="search-bar">
        <span className="search-icon">⌕</span>
        <input
          ref={inputRef}
          className="search-input"
          value={q}
          placeholder="输入关键词或问题..."
          onChange={e => setQ(e.target.value)}
          onKeyDown={e => { if (e.key === 'Enter') doSearch() }}
        />
        <button className="btn btn-primary" onClick={doSearch} disabled={state === 'loading'}>
          {state === 'loading' ? '搜索中' : '搜索'}
        </button>
      </div>

      <div className="search-filters">
        <Toggle label="向量检索" on={useVector} onChange={setUseVector} />
        <Toggle label="LLM 重排序" on={useRerank} onChange={setUseRerank} />
      </div>

      <div className="result-count-text">{countText}</div>

      {state === 'loading' && (
        <div className="search-loading">
          <div className="loading-spinner" />
          <div className="loading-stage">混合检索中...</div>
          <div className="loading-skeletons">
            <div className="skeleton-line skeleton-title" />
            <div className="skeleton-line" />
            <div className="skeleton-line" />
            <div className="skeleton-line skeleton-short" />
          </div>
        </div>
      )}

      {state === 'done' && (
        <div className="search-results">
          {!results.results?.length ? (
            <div className="empty-state">未找到结果</div>
          ) : (
            results.results.map((r, i) => (
              <div key={i} className="result-item">
                <div className="result-title">
                  {r.doc_title}
                  {(r.tags || []).map(t => <span key={t} className="tag tag-orange">{t}</span>)}
                </div>
                <div className="result-snippet" dangerouslySetInnerHTML={{ __html: highlightSnippet(r.snippet || r.content || '') }} />
                <div className="result-meta">
                  <span>相关度 <span className="score-bar"><span className="score-fill" style={{ width: `${(r.score * 100).toFixed(0)}%` }} /></span> {(r.score * 100).toFixed(0)}%</span>
                </div>
              </div>
            ))
          )}
        </div>
      )}
    </div>
  )
}
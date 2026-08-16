import { useState } from 'react'
import { api } from '../api.js'
import { Btn, Card } from '../ui/Base.jsx'
import { useToast } from '../ui/Toast.jsx'

function formatSize(bytes) {
  if (bytes < 1024) return bytes + ' B'
  if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB'
  return (bytes / (1024 * 1024)).toFixed(1) + ' MB'
}

export default function AnalyzePage() {
  const { showToast } = useToast()
  const [file, setFile] = useState(null)
  const [busy, setBusy] = useState(false)
  const [data, setData] = useState(null)
  const [error, setError] = useState('')
  const [sheet, setSheet] = useState(null)

  const pick = () => document.getElementById('analyze-file-input')?.click()

  const onFileChange = (e) => {
    const f = e.target.files?.[0] || null
    setFile(f)
    setData(null)
    setError('')
  }

  const analyze = (targetSheet = null, withAI = true) => {
    if (!file || busy) {
      if (!file) showToast('请先选择文件', 'error', 2500)
      return
    }
    setBusy(true)
    setError('')
    if (!targetSheet) setData(null)
    api.analyze(file, withAI, targetSheet)
      .then(d => {
        setData(d)
        setSheet(d.current_sheet || null)
        if (!targetSheet) showToast(`分析完成：${d.filename || file.name}`, 'success')
      })
      .catch(err => {
        setError(err.message)
        showToast(`分析失败：${err.message}`, 'error')
      })
      .finally(() => setBusy(false))
  }

  const exportReport = () => {
    if (data?.cache_key) window.open(`/api/analyze/export?key=${encodeURIComponent(data.cache_key)}`, '_blank')
  }

  return (
    <div className="analyze-page">
      <div className="page-header">
        <div>
          <div className="page-title">📊 数据分析</div>
          <div className="page-subtitle">Excel 多 sheet 自动统计 · 字符图可视化 · AI 趋势解读</div>
        </div>
        <div className="header-actions">
          <input type="file" id="analyze-file-input" accept=".xlsx,.xls,.csv,.tsv,.json" style={{ display: 'none' }} onChange={onFileChange} />
          <Btn onClick={pick}>📁 选择文件</Btn>
          <Btn variant="primary" onClick={() => analyze()} disabled={busy}>{busy ? '分析中...' : '🤖 AI 分析'}</Btn>
        </div>
      </div>

      {file && (
        <div className="analyze-file-info">
          <div className="analyze-file-icon">📄</div>
          <div className="analyze-file-main">
            <div className="analyze-file-name">{file.name}</div>
            <div className="analyze-file-meta">大小 {formatSize(file.size)} · {busy ? '分析中，请稍候...' : '等待分析'}</div>
          </div>
        </div>
      )}

      {busy && (
        <div className="analyze-loading">
          <div className="analyze-loading-spinner" />
          <div className="analyze-loading-text">正在分析数据...</div>
        </div>
      )}

      {error && (
        <Card className="empty-card">
          <div className="empty-icon">⚠️</div>
          <div style={{ color: 'var(--red)' }}>分析失败：{error}</div>
        </Card>
      )}

      {data && (
        <div className="analyze-content">
          <Card className="analyze-summary-card">
            <div className="analyze-summary-main">
              <div className="analyze-summary-name">{data.filename || '未命名文件'}</div>
              <div className="analyze-summary-meta">
                {data.current_sheet && <span className="tag tag-cyan">Sheet: {data.current_sheet}</span>}
                <span className="tag">{data.rows || 0} 行 × {data.cols || 0} 列</span>
                <span className="tag tag-success">分析完成</span>
              </div>
            </div>
            <Btn size="sm" onClick={exportReport}>导出报告</Btn>
          </Card>

          {data.sheets?.length > 1 && (
            <div className="sheet-tabs">
              {data.sheets.map(s => (
                <button
                  key={s}
                  className={`sheet-tab ${s === sheet ? 'active' : ''}`}
                  disabled={busy}
                  onClick={() => { if (s !== sheet) analyze(s, false) }}
                >{s}</button>
              ))}
            </div>
          )}

          <div className="stats-grid">
            {(data.columns || []).map((col, i) => (
              <Card key={i}>
                <div className="stat-header">
                  <div className="stat-name">{col.name}</div>
                  <div className="stat-type">{col.dtype}</div>
                </div>
                <div className="stat-rows">
                  {Object.entries(col)
                    .filter(([k]) => !['name', 'dtype', 'top_values'].includes(k))
                    .map(([k, v]) => <div key={k}><span className="label">{k}</span>{v}</div>)}
                </div>
              </Card>
            ))}
          </div>

          {(data.preview_rows || []).length > 0 && (
            <Card className="mt-16">
              <div className="card-title mb-12">数据预览</div>
              <div className="data-table">
                <table>
                  <thead><tr>{(data.columns || []).map(c => <th key={c.name}>{c.name}</th>)}</tr></thead>
                  <tbody>
                    {data.preview_rows.map((row, i) => (
                      <tr key={i}>{(data.columns || []).map(c => <td key={c.name}>{row[c.name] ?? ''}</td>)}</tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </Card>
          )}

          {data.ai_insight && (
            <Card className="mt-16 ai-insight-card">
              <div className="card-title mb-12" style={{ color: 'var(--cyan)' }}>🤖 AI 解读</div>
              <div className="ai-insight-text">{data.ai_insight}</div>
            </Card>
          )}
        </div>
      )}
    </div>
  )
}
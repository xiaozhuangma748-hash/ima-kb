import { useEffect, useState } from 'react'
import { api } from '../api.js'
import { Card, Btn } from '../ui/Base.jsx'

export default function DashboardPage() {
  const [data, setData] = useState(null)
  const [error, setError] = useState('')

  const load = () => {
    setError('')
    api.stats().then(setData).catch(e => setError(e.message))
  }

  useEffect(() => { load() }, [])

  const metrics = [
    { label: '文档总数', value: data?.documents ?? '–', cls: '' },
    { label: '分块总数', value: data?.chunks ?? '–', cls: 'cyan' },
    { label: '标签数量', value: data?.tags_count ?? '–', cls: 'purple' },
    { label: '图谱节点', value: data?.graph_nodes ?? '–', cls: 'green' },
  ]

  return (
    <div className="dashboard-page">
      <div className="page-header">
        <div>
          <div className="page-title">📈 仪表盘</div>
          <div className="page-subtitle">知识库总览 · 质量告警 · 最近活动</div>
        </div>
        <Btn className="ml-auto" onClick={load}>🔄 刷新</Btn>
      </div>

      {error && <div className="inline-error">请求失败: {error}</div>}

      <div className="dashboard-grid">
        {metrics.map(m => (
          <div key={m.label} className={`metric-card ${m.cls}`}>
            <div className="metric-label">{m.label}</div>
            <div className="metric-value">{m.value}</div>
          </div>
        ))}
      </div>

      <div className="dashboard-row">
        <Card>
          <div className="card-title mb-12">📊 标签分布 Top 10</div>
          <div className="chart-bars">
            {(data?.top_tags || []).length === 0 && <div className="placeholder-text">暂无标签数据</div>}
            {(data?.top_tags || []).map(t => {
              const max = Math.max(...(data?.top_tags || []).map(x => x.count), 1)
              return (
                <div key={t.name} className="chart-bar-item">
                  <div className="chart-bar" style={{ height: `${(t.count / max * 100).toFixed(0)}%` }} />
                  <div className="chart-bar-label" title={t.name}>{t.name.length > 4 ? t.name.slice(0, 4) + '…' : t.name}</div>
                </div>
              )
            })}
          </div>
        </Card>
        <Card>
          <div className="card-title mb-12">⚠️ 质量告警</div>
          <div id="alerts-list">
            {(data?.alerts || []).length === 0
              ? <div className="placeholder-text">一切正常 ✓</div>
              : data.alerts.map((a, i) => (
                <div key={i} className={`alert-item ${a.severity}`}>
                  <strong>{a.severity === 'error' ? '❌' : '⚠️'} {a.severity}</strong>
                  <br /><span className="text-secondary">{a.message}</span>
                </div>
              ))}
          </div>
        </Card>
      </div>

      <Card className="mt-16">
        <div className="card-title mb-12">🕐 最近入库</div>
        {(data?.recent_docs || []).length === 0 ? (
          <div className="placeholder-text">暂无入库记录</div>
        ) : (
          <div className="data-table">
            <table>
              <thead><tr><th>文档名</th><th>格式</th><th>标签</th><th>分块</th><th>入库时间</th></tr></thead>
              <tbody>
                {data.recent_docs.map(d => (
                  <tr key={d.doc_id}>
                    <td>{d.title}</td>
                    <td>{d.file_type}</td>
                    <td>{(d.tags || []).map(t => <span key={t} className="tag tag-orange">{t}</span>)}</td>
                    <td>{d.chunk_count}</td>
                    <td>{d.created_at}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
    </div>
  )
}
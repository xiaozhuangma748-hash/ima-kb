import { useQA } from '../store/qa.jsx'
import { useState } from 'react'

// DetailsPanel：右侧引用来源面板，QA 页写入 sources / activeMarker
export default function DetailsPanel({ content, onClose }) {
  const qa = useQA()
  const sources = content ? content.sources : qa.sources
  const activeMarker = content ? content.activeMarker : qa.activeMarker
  const title = content ? content.title : '引用来源'

  const grouped = sources ? groupSources(sources) : []

  return (
    <div className="details">
      {!qa.streaming && sources && sources.length > 0 && (
        <div className="details-head">
          <span className="details-title">{title}</span>
          <button className="details-close" onClick={onClose} title="关闭">×</button>
        </div>
      )}
      {qa.streaming ? (
        <div className="details-empty">生成中…</div>
      ) : grouped.length === 0 ? (
        <div className="details-empty">暂无引用来源<br />提问后在这里查看资料</div>
      ) : (
        <div className="details-list">
          {grouped.map(({ marker, docs }) => (
            <div
              key={marker}
              className={`source-card ${activeMarker === marker ? 'active' : ''}`}
              onClick={() => qa.highlightMarker?.(marker)}
            >
              <div className="source-marker">[{marker}]</div>
              <div className="source-docs">
                {docs.map((d, i) => (
                  <div key={i} className="source-doc" title={d.title}>
                    <span className="source-title">{d.title}</span>
                    {d.score !== undefined && (
                      <span className="source-score">{Math.round(d.score * 100)}%</span>
                    )}
                  </div>
                ))}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

// 按 marker 聚合 citations + sources
function groupSources(sources) {
  const map = new Map()
  for (const s of sources) {
    const key = s.marker || 'r1'
    if (!map.has(key)) map.set(key, [])
    map.get(key).push(s)
  }
  return [...map.entries()].map(([marker, docs]) => ({ marker, docs }))
}
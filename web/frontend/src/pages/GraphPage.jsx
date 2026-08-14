import { useEffect, useRef, useState } from 'react'
import { api } from '../api.js'
import { Btn } from '../ui/Base.jsx'
import { useToast } from '../ui/Toast.jsx'

const CLUSTER_HUES = [0, 30, 60, 120, 180, 210, 240, 270, 300, 330, 15, 75, 150, 195, 225, 255, 285, 315]
const TYPE_COLORS = { document: '#FEB02E', region: '#22D3EE', agency: '#FF5F57', topic: '#A78BFA' }

function clusterBorder(idx) { return idx < 0 ? '#aaa' : `hsl(${CLUSTER_HUES[idx % CLUSTER_HUES.length]}, 70%, 55%)` }
function clusterBg(idx) { return idx < 0 ? '#1f2126' : `hsl(${CLUSTER_HUES[idx % CLUSTER_HUES.length]}, 40%, 24%)` }

export default function GraphPage() {
  const { showToast } = useToast()
  const canvasRef = useRef(null)
  const networkRef = useRef(null)
  const [stats, setStats] = useState({ nodes: '–', edges: '–' })
  const [empty, setEmpty] = useState(false)
  const [selected, setSelected] = useState(null) // {label, type, degree, doc_count, neighbors}
  const [neighbors, setNeighbors] = useState([])

  const loadGraph = () => {
    api.graphData().then(data => {
      const els = data.elements
      if (!els?.nodes?.length) {
        setEmpty(true)
        setSelected(null)
        return
      }
      setEmpty(false)

      const nodes = new vis.DataSet(els.nodes.map(n => {
        const d = n.data || n
        const cluster = d.cluster ?? -1
        return {
          id: d.id || n.id,
          label: d.label || n.label,
          color: {
            background: clusterBg(cluster),
            border: clusterBorder(cluster),
            highlight: { background: clusterBg(cluster), border: '#6799FE' },
            hover: { background: clusterBg(cluster), border: '#6799FE' },
          },
          size: d.size || 16,
          font: { color: '#e6e8ea', size: d.font_size || 12, face: 'PingFang SC, -apple-system, sans-serif' },
          shape: 'dot',
          borderWidth: 1,
          borderWidthSelected: 2,
          type: d.type,
          degree: d.degree || 0,
          doc_count: d.doc_count || 0,
          title: `${d.label || n.label}\n类型: ${d.type}\n关联文档: ${d.doc_count || 0}\n连接数: ${d.degree || 0}`,
        }
      }))

      const edges = new vis.DataSet((els.edges || []).map(e => {
        const d = e.data || e
        return {
          from: d.source || e.source,
          to: d.target || e.target,
          label: d.label || e.label || '',
          arrows: 'to',
          color: { color: 'rgba(255,255,255,0.2)', highlight: '#6799FE', hover: 'rgba(255,255,255,0.45)' },
          font: { color: 'rgba(255,255,255,0.5)', size: 9, strokeWidth: 0 },
          smooth: { type: 'cubicBezier', forceDirection: 'horizontal', roundness: 0.3 },
        }
      }))

      const container = canvasRef.current
      if (!container) return
      const network = new vis.Network(container, { nodes, edges }, {
        physics: {
          barnesHut: { gravitationalConstant: -3000, centralGravity: 0.3, springLength: 120, springConstant: 0.04, damping: 0.09 },
          stabilization: { iterations: 300 },
        },
        interaction: { hover: true, tooltipDelay: 200, zoomView: true, dragView: true },
      })
      networkRef.current = network

      network.on('click', (params) => {
        if (!params.nodes.length) { setSelected(null); return }
        const nodeId = params.nodes[0]
        const nodeData = nodes.get(nodeId)
        setSelected({
          label: nodeData.label,
          type: nodeData.type || '',
          degree: nodeData.degree || 0,
          doc_count: nodeData.doc_count || 0,
        })
        api.graphNeighbors(nodeId).then(nd => {
          setNeighbors(nd.found && nd.neighbors ? nd.neighbors : [])
        }).catch(() => setNeighbors([]))
      })
    }).catch(() => setEmpty(true))
  }

  const loadStats = () => {
    api.stats().then(d => setStats({ nodes: d.graph_nodes, edges: d.graph_edges })).catch(() => {})
  }

  useEffect(() => { loadGraph(); loadStats() }, [])

  // 页面卸载时销毁网络实例，避免内存泄漏
  useEffect(() => () => { networkRef.current?.destroy(); networkRef.current = null }, [])

  const rebuild = () => {
    if (!window.confirm('确定重建知识图谱？这将调用 LLM 重新抽取实体关系。')) return
    api.graphBuild().then(data => {
      window.alert(`构建完成: 处理 ${data.processed} 个文档`)
      loadGraph(); loadStats()
    }).catch(err => showToast('请求失败: ' + err.message, 'error'))
  }

  return (
    <div className="graph-page">
      <div className="page-header">
        <div>
          <div className="page-title">🕸️ 知识图谱</div>
          <div className="page-subtitle">{stats.nodes} 节点 · {stats.edges} 边 · LLM 抽取实体关系</div>
        </div>
        <div className="ml-auto flex-gap-8">
          <Btn onClick={rebuild}>🔄 重建</Btn>
          <a href="/api/graph/export" className="btn btn-primary" download>📥 导出 HTML</a>
        </div>
      </div>

      <div className="graph-layout">
        <div className="graph-canvas" ref={canvasRef}>
          {empty && <div className="graph-empty">图谱为空，请先构建知识图谱</div>}
          <div className="graph-legend">
            <div className="legend-title">节点类型</div>
            <div className="legend-item"><div className="legend-dot legend-dot-orange" />document 文档</div>
            <div className="legend-item"><div className="legend-dot legend-dot-teal" />region 地区</div>
            <div className="legend-item"><div className="legend-dot legend-dot-red" />agency 机构</div>
            <div className="legend-item"><div className="legend-dot legend-dot-purple" />topic 主题</div>
          </div>
        </div>
        <div className="graph-sidebar">
          {selected ? (
            <div className="graph-panel">
              <div className="panel-header">
                <div className="panel-title">{selected.label}</div>
                <div className="panel-type">{selected.type}</div>
              </div>
              <div className="panel-stats">
                <div className="panel-stat">
                  <div className="stat-value">{selected.degree}</div>
                  <div className="stat-label">连接数</div>
                </div>
                <div className="panel-stat">
                  <div className="stat-value">{selected.doc_count}</div>
                  <div className="stat-label">关联文档</div>
                </div>
              </div>
              <div className="panel-section">
                <div className="section-title">邻居节点</div>
                <div className="neighbors-list">
                  {neighbors.length === 0 ? (
                    <div className="empty-hint">无邻居节点</div>
                  ) : (
                    neighbors.map((n, i) => (
                      <div key={i} className="neighbor-item">
                        <span className="neighbor-name" style={{ color: TYPE_COLORS[n.type] || '#22D3EE' }}>{n.node}</span>
                        <span className="neighbor-rel">{n.relation_label || ''}</span>
                      </div>
                    ))
                  )}
                </div>
              </div>
            </div>
          ) : (
            <div className="graph-panel">
              <div className="panel-header"><div className="panel-title">图谱概览</div></div>
              <div className="panel-stats">
                <div className="panel-stat">
                  <div className="stat-value">{stats.nodes}</div>
                  <div className="stat-label">节点</div>
                </div>
                <div className="panel-stat">
                  <div className="stat-value">{stats.edges}</div>
                  <div className="stat-label">边</div>
                </div>
              </div>
              <div className="panel-section">
                <div className="section-title">图例</div>
                <div className="legend-grid">
                  <div className="legend-chip"><span className="legend-dot legend-dot-orange" />文档</div>
                  <div className="legend-chip"><span className="legend-dot legend-dot-teal" />地区</div>
                  <div className="legend-chip"><span className="legend-dot legend-dot-red" />机构</div>
                  <div className="legend-chip"><span className="legend-dot legend-dot-purple" />主题</div>
                </div>
              </div>
              <div className="panel-hint">
                点击节点查看详情<br />滚轮缩放 · 拖拽移动
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
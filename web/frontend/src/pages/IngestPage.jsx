import { useEffect, useRef, useState } from 'react'
import { api } from '../api.js'
import { Btn, Card, Tag } from '../ui/Base.jsx'
import { useToast } from '../ui/Toast.jsx'

function formatSize(bytes) {
  if (bytes < 1024) return bytes + ' B'
  if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB'
  return (bytes / (1024 * 1024)).toFixed(1) + ' MB'
}

function extIcon(name) {
  const ext = (name.split('.').pop() || 'file').slice(0, 4).toUpperCase()
  return ext
}

export default function IngestPage() {
  const { showToast } = useToast()
  const [tab, setTab] = useState('file')
  const [queue, setQueue] = useState([]) // {id, name, size, source, status, error, chunks, tokens, tags}
  const [dragOver, setDragOver] = useState(false)
  const [url, setUrl] = useState('')
  const [urlBusy, setUrlBusy] = useState(false)
  const [clipTitle, setClipTitle] = useState('')
  const [clipContent, setClipContent] = useState('')
  const [clipBusy, setClipBusy] = useState(false)
  const fileInputRef = useRef(null)
  const [stats, setStats] = useState(null)

  const loadStats = () => api.stats().then(setStats).catch(() => {})
  useEffect(() => { loadStats() }, [])

  const addItem = (name, size, source) => {
    const id = `q-${Date.now()}-${Math.random().toString(36).slice(2, 6)}`
    setQueue(prev => [...prev, { id, name, size, source, status: 'processing' }])
    return id
  }

  const patchItem = (id, patch) => {
    setQueue(prev => prev.map(it => it.id === id ? { ...it, ...patch } : it))
  }

  const handleFiles = (files) => {
    if (!files?.length) return
    const fd = new FormData()
    const items = []
    for (const f of files) {
      fd.append('files', f)
      items.push({ name: f.name, id: addItem(f.name, f.size, 'file') })
    }
    showToast(`正在上传 ${files.length} 个文件...`, 'info', 2000)
    api.upload(fd)
      .then(data => {
        let success = 0, skip = 0, fail = 0
        for (const r of data.results || []) {
          const m = items.find(it => it.name === r.filename)
          if (m) patchItem(m.id, r)
          else { const id = addItem(r.filename, 0, 'file'); patchItem(id, r) }
          if (r.status === 'success') success++
          else if (r.status === 'skipped') skip++
          else fail++
        }
        if (success > 0) { showToast(`成功入库 ${success} 个文档`, 'success'); loadStats() }
        if (skip > 0) showToast(`${skip} 个文件被跳过（重复或不支持）`, 'info')
        if (fail > 0) showToast(`${fail} 个文件入库失败`, 'error')
      })
      .catch(() => {
        items.forEach(it => patchItem(it.id, { status: 'failed', error: '网络错误' }))
        showToast('上传失败：网络错误', 'error')
      })
  }

  const handleUrl = () => {
    const u = url.trim()
    if (!u) { showToast('请输入 URL', 'error', 2000); return }
    setUrlBusy(true)
    const id = addItem(u, 0, 'url')
    api.ingestUrl(u)
      .then(data => {
        patchItem(id, data)
        if (data.status === 'success') { showToast(`入库成功: ${data.title}`, 'success'); loadStats() }
        else if (data.status === 'skipped') showToast(`已跳过: ${data.error || '重复内容'}`, 'info')
        else showToast(`入库失败: ${data.error || '未知错误'}`, 'error')
        setUrl('')
      })
      .catch(() => { patchItem(id, { status: 'failed', error: '网络错误' }); showToast('URL 入库失败：网络错误', 'error') })
      .finally(() => setUrlBusy(false))
  }

  const handleClip = () => {
    const content = clipContent.trim()
    if (!content) { showToast('请输入内容', 'error', 2000); return }
    setClipBusy(true)
    const title = clipTitle.trim()
    const displayName = title || `手动录入_${content.slice(0, 20)}...`
    const id = addItem(displayName, content.length, 'clip')
    api.ingestClip(title, content)
      .then(data => {
        patchItem(id, data)
        if (data.status === 'success') {
          showToast(`入库成功: ${data.title}`, 'success')
          loadStats()
          setClipContent('')
          setClipTitle('')
        } else if (data.status === 'skipped') showToast(`已跳过: ${data.error || '重复内容'}`, 'info')
        else showToast(`入库失败: ${data.error || '未知错误'}`, 'error')
      })
      .catch(() => { patchItem(id, { status: 'failed', error: '网络错误' }); showToast('手动录入入库失败：网络错误', 'error') })
      .finally(() => setClipBusy(false))
  }

  const clearQueue = () => {
    const removable = queue.filter(it => it.status !== 'processing')
    if (removable.length === 0) { showToast('没有可清空的记录', 'info', 2000); return }
    setQueue(prev => prev.filter(it => it.status === 'processing'))
    showToast(`已清空 ${removable.length} 条记录`, 'info', 2000)
  }

  return (
    <div className="ingest-page">
      <div className="page-header">
        <div>
          <div className="page-title">📥 文档入库</div>
          <div className="page-subtitle">拖拽文件 · 自动解析 · 智能标签 · 知识图谱构建</div>
        </div>
      </div>

      <div className="ingest-layout">
        <div className="ingest-main">
          <div className="ingest-tabs">
            {['file', 'url', 'clip'].map(t => (
              <button key={t} className={`ingest-tab ${tab === t ? 'active' : ''}`} onClick={() => setTab(t)}>
                {{ file: '文件上传', url: 'URL 入库', clip: '手动录入' }[t]}
              </button>
            ))}
          </div>

          {tab === 'file' && (
            <div
              className={`dropzone ${dragOver ? 'dragging' : ''}`}
              onClick={() => fileInputRef.current?.click()}
              onDragOver={e => { e.preventDefault(); setDragOver(true) }}
              onDragLeave={() => setDragOver(false)}
              onDrop={e => { e.preventDefault(); setDragOver(false); handleFiles(e.dataTransfer.files) }}
            >
              <div className="dropzone-icon">📂</div>
              <div className="dropzone-text"><strong>拖拽文件到此处</strong> 或点击选择</div>
              <div className="dropzone-hint">支持批量上传 · 单文件最大 100MB</div>
              <div className="format-pills">
                <Tag color="orange">PDF</Tag><Tag color="cyan">Word</Tag>
                <Tag color="purple">Excel</Tag><Tag color="red">PPT</Tag>
                <Tag>MD</Tag><Tag>TXT</Tag><Tag>HTML</Tag>
                <Tag>图片</Tag><Tag>扫描 PDF</Tag><Tag>.doc</Tag>
              </div>
            </div>
          )}
          <input
            ref={fileInputRef}
            type="file"
            multiple
            hidden
            accept=".pdf,.docx,.doc,.xlsx,.xls,.pptx,.md,.txt,.html,.htm,.png,.jpg,.jpeg,.tif,.tiff,.bmp,.webp,.py,.js,.json,.csv,.tsv"
            onChange={e => { handleFiles(e.target.files); e.target.value = '' }}
          />

          {tab === 'url' && (
            <div className="url-form">
              <div className="url-input-row">
                <input className="input flex-1" value={url} placeholder="输入网页 URL，例如 https://..."
                  onChange={e => setUrl(e.target.value)}
                  onKeyDown={e => { if (e.key === 'Enter') handleUrl() }} />
                <Btn variant="primary" onClick={handleUrl} disabled={urlBusy}>{urlBusy ? '抓取中...' : '入库'}</Btn>
              </div>
              <div style={{ fontSize: 12, color: 'var(--text-muted)' }}>将抓取网页正文并自动入库，支持新闻、政策、博客等页面。</div>
            </div>
          )}

          {tab === 'clip' && (
            <div className="clip-form">
              <input className="input flex-1" value={clipTitle} placeholder="文档标题（可选，留空自动生成）"
                onChange={e => setClipTitle(e.target.value)} />
              <textarea className="clip-textarea" value={clipContent} placeholder="在此输入或粘贴文本内容..."
                onChange={e => setClipContent(e.target.value)} />
              <div className="clip-toolbar">
                <span className="clip-counter">{clipContent.length} 字</span>
                <div className="clip-actions">
                  <Btn onClick={() => { setClipTitle(''); setClipContent('') }}>重置</Btn>
                  <Btn variant="primary" onClick={handleClip} disabled={clipBusy}>{clipBusy ? '入库中...' : '入库'}</Btn>
                </div>
              </div>
            </div>
          )}

          <div className="queue-section">
            <div className="queue-header">
              <div className="queue-title">入库队列</div>
              <div className="queue-actions">
                <button className="queue-btn" onClick={clearQueue}>清空</button>
              </div>
            </div>
            <div className="upload-list">
              {queue.length === 0 ? (
                <div className="queue-empty">暂无入库任务，上传文件或粘贴内容后将在此显示</div>
              ) : (
                queue.map(it => (
                  <QueueItem key={it.id} item={it} />
                ))
              )}
            </div>
          </div>
        </div>

        <div className="ingest-side">
          <Card>
            <div className="card-title mb-12">入库统计</div>
            <div className="stat-block"><span className="stat-label">总文档数</span><span className="metric-inline">{stats?.documents ?? '–'}</span></div>
            <div className="stat-block"><span className="stat-label">总分块数</span><span className="metric-inline-cyan">{stats?.chunks ?? '–'}</span></div>
            <div className="stat-block"><span className="stat-label">自动标签</span><span className="metric-inline-purple">{stats?.tags_count ?? '–'}</span></div>
            <div className="stat-block"><span className="stat-label">图谱节点</span><span className="metric-inline-red">{stats?.graph_nodes ?? '–'}</span></div>
            <div className="stat-block"><span className="stat-label">总 Token</span><span className="metric-inline-primary">{stats?.total_tokens ?? '–'}</span></div>
          </Card>
          <div className="ingest-tips">
            <div className="ingest-tips-title">入库说明</div>
            <div className="ingest-tips-list">
              · 支持拖拽或点击选择多个文件<br />
              · 扫描版 PDF 自动走 OCR<br />
              · 重复内容自动跳过<br />
              · LLM 自动生成主题标签<br />
              · 入库后可前往「知识图谱」查看
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}

function QueueItem({ item }) {
  const s = item.status
  const sizeText = item.size > 0 ? formatSize(item.size) : item.source === 'url' ? '网页' : item.source === 'clip' ? '文本' : ''
  const statusText = { processing: '处理中', success: '已入库', skipped: '跳过', failed: '失败' }[s]
  const cls = { processing: 'item-processing', success: 'item-success', skipped: 'item-skipped', failed: 'item-failed' }[s]
  const icon = s === 'success' ? 'OK' : s === 'skipped' ? '--' : s === 'failed' ? '!' : extIcon(item.name)

  return (
    <div className={`upload-item ${cls}`}>
      <div className={`file-icon ${s === 'success' ? 'icon-success' : s === 'skipped' ? 'icon-skipped' : s === 'failed' ? 'icon-failed' : ''}`}>{icon}</div>
      <div className="file-info">
        <div className="file-name">{item.name}</div>
        <div className="file-meta">
          {s === 'processing' && <span>{sizeText}</span>}
          {s === 'success' && (<>
            <span>{item.chunks || 0} 块</span>
            <span>{item.tokens || 0} tokens</span>
            {(item.tags || []).slice(0, 3).map(t => <Tag key={t}>{t}</Tag>)}
          </>)}
          {s === 'skipped' && <span>{item.error || '已存在'}</span>}
          {s === 'failed' && <span>{item.error || '未知错误'}</span>}
        </div>
        <div className="progress-bar">
          <div className={`progress-fill ${s === 'processing' ? '' : `fill-${s}`}`}
            style={{ width: s === 'processing' ? '30%' : '100%' }} />
        </div>
      </div>
      <div className={`file-status status-${s}`}>{statusText}</div>
    </div>
  )
}
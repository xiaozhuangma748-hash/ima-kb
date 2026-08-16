import { useEffect, useMemo, useRef, useState } from 'react'
import { api } from '../api.js'
import { Btn, Tag } from '../ui/Base.jsx'
import { useToast } from '../ui/Toast.jsx'

function formatSize(bytes) {
  if (!bytes) return ''
  if (bytes < 1024) return bytes + ' B'
  if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB'
  return (bytes / (1024 * 1024)).toFixed(1) + ' MB'
}

function formatDate(iso) {
  if (!iso) return ''
  const d = new Date(iso)
  if (isNaN(d)) return iso
  const p = n => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`
}

// 文件类型 → 大类 + 显示名 + 色块样式
const TYPE_MAP = [
  { key: 'pdf', label: 'PDF', cls: 'tp-pdf', exts: ['pdf'] },
  { key: 'word', label: 'Word', cls: 'tp-word', exts: ['docx', 'doc'] },
  { key: 'excel', label: 'Excel', cls: 'tp-excel', exts: ['xlsx', 'xls', 'csv'] },
  { key: 'ppt', label: 'PPT', cls: 'tp-ppt', exts: ['pptx', 'ppt'] },
  { key: 'image', label: '图片', cls: 'tp-image', exts: ['png', 'jpg', 'jpeg', 'tif', 'tiff', 'bmp', 'webp'] },
  { key: 'text', label: '文本', cls: 'tp-text', exts: ['txt', 'md', 'html', 'htm', 'json', 'py', 'js'] },
  { key: 'other', label: '其他', cls: 'tp-other', exts: [] },
]

function typeOf(fileType = '', fileName = '') {
  const src = (fileType || '').toLowerCase().replace(/^\./, '') || (fileName || '').split('.').pop().toLowerCase()
  if (!src) return TYPE_MAP[TYPE_MAP.length - 1]
  return TYPE_MAP.find(t => t.exts.includes(src)) || TYPE_MAP[TYPE_MAP.length - 1]
}

export default function IngestPage() {
  const { showToast } = useToast()
  const [activeMethod, setActiveMethod] = useState('file') // file | url | clip
  const [url, setUrl] = useState('')
  const [urlBusy, setUrlBusy] = useState(false)
  const [clipTitle, setClipTitle] = useState('')
  const [clipContent, setClipContent] = useState('')
  const [clipBusy, setClipBusy] = useState(false)
  const fileInputRef = useRef(null)

  // 已入库文档
  const [docs, setDocs] = useState([])
  const [loading, setLoading] = useState(true)
  const [typeFilter, setTypeFilter] = useState('all')
  const [query, setQuery] = useState('')
  const [stats, setStats] = useState(null)
  const [dragOver, setDragOver] = useState(false)

  const loadDocs = () => {
    setLoading(true)
    api.listDocuments()
      .then(data => setDocs(data.documents || []))
      .catch(() => showToast('加载文档列表失败', 'error'))
      .finally(() => setLoading(false))
  }
  const loadStats = () => api.stats().then(setStats).catch(() => {})
  useEffect(() => { loadDocs(); loadStats() }, [])

  // 类型筛选 chips（按实际文档类型统计）
  const typeCounts = useMemo(() => {
    const m = {}
    for (const d of docs) {
      const key = typeOf(d.file_type, d.file_name).key
      m[key] = (m[key] || 0) + 1
    }
    return m
  }, [docs])

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase()
    return docs.filter(d => {
      if (typeFilter !== 'all' && typeOf(d.file_type, d.file_name).key !== typeFilter) return false
      if (!q) return true
      return (d.title || '').toLowerCase().includes(q) || (d.file_name || '').toLowerCase().includes(q)
    })
  }, [docs, typeFilter, query])

  const reload = () => { loadDocs(); loadStats() }

  const handleFiles = (files) => {
    if (!files?.length) return
    const fd = new FormData()
    for (const f of files) fd.append('files', f)
    showToast(`正在上传 ${files.length} 个文件...`, 'info', 2000)
    api.upload(fd)
      .then(data => {
        let success = 0, skip = 0, fail = 0
        for (const r of data.results || []) {
          if (r.status === 'success') success++
          else if (r.status === 'skipped') skip++
          else fail++
        }
        if (success > 0) { showToast(`成功入库 ${success} 个文档`, 'success'); reload() }
        if (skip > 0) showToast(`${skip} 个文件被跳过（重复或不支持）`, 'info')
        if (fail > 0) showToast(`${fail} 个文件入库失败`, 'error')
      })
      .catch(() => showToast('上传失败：网络错误', 'error'))
  }

  const handleUrl = () => {
    const u = url.trim()
    if (!u) { showToast('请输入 URL', 'error', 2000); return }
    setUrlBusy(true)
    api.ingestUrl(u)
      .then(data => {
        if (data.status === 'success') { showToast(`入库成功: ${data.title}`, 'success'); reload(); setUrl('') }
        else if (data.status === 'skipped') showToast(`已跳过: ${data.error || '重复内容'}`, 'info')
        else showToast(`入库失败: ${data.error || '未知错误'}`, 'error')
      })
      .catch(() => showToast('URL 入库失败：网络错误', 'error'))
      .finally(() => setUrlBusy(false))
  }

  const handleClip = () => {
    const content = clipContent.trim()
    if (!content) { showToast('请输入内容', 'error', 2000); return }
    setClipBusy(true)
    api.ingestClip(clipTitle.trim(), content)
      .then(data => {
        if (data.status === 'success') {
          showToast(`入库成功: ${data.title}`, 'success')
          reload(); setClipContent(''); setClipTitle('')
        } else if (data.status === 'skipped') showToast(`已跳过: ${data.error || '重复内容'}`, 'info')
        else showToast(`入库失败: ${data.error || '未知错误'}`, 'error')
      })
      .catch(() => showToast('手动录入入库失败：网络错误', 'error'))
      .finally(() => setClipBusy(false))
  }

  const handleDelete = (d) => {
    if (!window.confirm(`确定删除「${d.title}」？将同时清除其分块与向量，不可恢复。`)) return
    api.deleteDocument(d.id)
      .then(() => { showToast('已删除', 'success'); reload() })
      .catch(e => showToast(`删除失败: ${e.message}`, 'error'))
  }

  const fileTypes = () => {
    const set = new Set()
    for (const d of docs) set.add(typeOf(d.file_type, d.file_name))
    return Array.from(set)
  }

  return (
    <div className="ingest-page">
      <div className="page-header">
        <div>
          <div className="page-title">📥 文档入库</div>
          <div className="page-subtitle">拖拽文件 · 自动解析 · 智能标签 · 知识图谱构建</div>
        </div>
      </div>

      {/* 顶部统计概览 */}
      <div className="ingest-stats">
        <div className="stat-chip"><span className="stat-chip-label">总文档</span><span className="stat-chip-val">{stats?.documents ?? '–'}</span></div>
        <div className="stat-chip"><span className="stat-chip-label">总分块</span><span className="stat-chip-val">{stats?.chunks ?? '–'}</span></div>
        <div className="stat-chip"><span className="stat-chip-label">自动标签</span><span className="stat-chip-val">{stats?.tags_count ?? '–'}</span></div>
        <div className="stat-chip"><span className="stat-chip-label">图谱节点</span><span className="stat-chip-val">{stats?.graph_nodes ?? '–'}</span></div>
        <div className="stat-chip"><span className="stat-chip-label">总 Token</span><span className="stat-chip-val">{stats?.total_tokens ?? '–'}</span></div>
      </div>

      {/* 入库操作：并排卡片 */}
      <div className="ingest-methods">
        <MethodCard
          active={activeMethod === 'file'} icon="📂" title="文件上传" desc="拖拽或点击选择本地文件，支持批量"
          onClick={() => setActiveMethod('file')}
        />
        <MethodCard
          active={activeMethod === 'url'} icon="🔗" title="URL 入库" desc="抓取网页正文并自动入库"
          onClick={() => setActiveMethod('url')}
        />
        <MethodCard
          active={activeMethod === 'clip'} icon="📝" title="手动录入" desc="粘贴文本内容，生成新文档"
          onClick={() => setActiveMethod('clip')}
        />
      </div>

      <div className="ingest-panel">
        {activeMethod === 'file' && (
          <div
            className={`dropzone ${dragOver ? 'dragging' : ''}`}
            onClick={() => fileInputRef.current?.click()}
            onDragOver={e => { e.preventDefault(); setDragOver(true) }}
            onDragLeave={e => { e.preventDefault(); setDragOver(false) }}
            onDrop={e => { e.preventDefault(); setDragOver(false); handleFiles(e.dataTransfer.files) }}
          >
            <div className="dropzone-icon">📂</div>
            <div className="dropzone-text"><strong>拖拽文件到此处</strong> 或点击选择</div>
            <div className="dropzone-hint">支持批量上传 · 单文件最大 100MB</div>
            <div className="format-pills">
              <Tag color="orange">PDF</Tag><Tag color="cyan">Word</Tag>
              <Tag color="purple">Excel</Tag><Tag color="red">PPT</Tag>
              <Tag>MD</Tag><Tag>TXT</Tag><Tag>HTML</Tag><Tag>图片</Tag>
            </div>
          </div>
        )}
        <input
          ref={fileInputRef} type="file" multiple hidden
          accept=".pdf,.docx,.doc,.xlsx,.xls,.pptx,.md,.txt,.html,.htm,.png,.jpg,.jpeg,.tif,.tiff,.bmp,.webp,.py,.js,.json,.csv,.tsv"
          onChange={e => { handleFiles(e.target.files); e.target.value = '' }}
        />

        {activeMethod === 'url' && (
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

        {activeMethod === 'clip' && (
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
      </div>

      {/* 已入库内容 */}
      <div className="docs-section">
        <div className="docs-head">
          <div className="docs-title">已入库内容</div>
          <div className="docs-count">{docs.length} 个文档</div>
        </div>

        <div className="docs-toolbar">
          <div className="docs-filters">
            <button
              className={`filter-chip ${typeFilter === 'all' ? 'active' : ''}`}
              onClick={() => setTypeFilter('all')}
            >全部 {docs.length}</button>
            {fileTypes().map(t => (
              <button
                key={t.key}
                className={`filter-chip ${typeFilter === t.key ? 'active' : ''}`}
                onClick={() => setTypeFilter(t.key)}
              >
                <span className={`dot ${t.cls}`} />{t.label} {typeCounts[t.key] || 0}
              </button>
            ))}
          </div>
          <div className="docs-search">
            <input className="input" value={query} placeholder="搜索文档标题或文件名..."
              onChange={e => setQuery(e.target.value)} />
          </div>
        </div>

        {loading ? (
          <div className="docs-empty">加载中...</div>
        ) : filtered.length === 0 ? (
          <div className="docs-empty">{docs.length === 0 ? '暂无入库文档，请从上方添加入库' : '没有匹配的文档'}</div>
        ) : (
          <div className="docs-grid">
            {filtered.map(d => {
              const t = typeOf(d.file_type, d.file_name)
              return (
                <div className="doc-card" key={d.id}>
                  <div className={`doc-type-icon ${t.cls}`}>{t.label}</div>
                  <button
                    className="doc-del" title="删除"
                    onClick={(e) => { e.stopPropagation(); handleDelete(d) }}
                  >×</button>
                  <div className="doc-title">{d.title || d.file_name}</div>
                  <div className="doc-file">{d.file_name}</div>
                  {(d.tags || []).length > 0 && (
                    <div className="doc-tags">
                      {d.tags.slice(0, 3).map(tg => <Tag key={tg}>{tg}</Tag>)}
                    </div>
                  )}
                  <div className="doc-meta">
                    <span>{d.chunk_count || 0} 块</span>
                    <span>{d.total_tokens || 0} tokens</span>
                    <span>{formatSize(d.file_size) || t.label}</span>
                    <span>{formatDate(d.created_at)}</span>
                  </div>
                </div>
              )
            })}
          </div>
        )}
      </div>
    </div>
  )
}

function MethodCard({ active, icon, title, desc, onClick }) {
  return (
    <div className={`method-card ${active ? 'active' : ''}`} onClick={onClick}>
      <div className="method-icon">{icon}</div>
      <div className="method-title">{title}</div>
      <div className="method-desc">{desc}</div>
    </div>
  )
}
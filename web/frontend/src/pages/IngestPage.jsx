import { useEffect, useMemo, useRef, useState } from 'react'
import { api } from '../api.js'
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

// 文件类型 → 大类 + 显示名 + 图标色（柔和彩色小方块）
const TYPE_MAP = [
  { key: 'pdf', label: 'PDF', icon: '▣', color: '#f0564f', ext: ['pdf'] },
  { key: 'word', label: 'Word', icon: 'W', color: '#3a7afe', ext: ['docx', 'doc'] },
  { key: 'excel', label: 'Excel', icon: '▦', color: '#22a06b', ext: ['xlsx', 'xls', 'csv'] },
  { key: 'ppt', label: 'PPT', icon: '◈', color: '#e68c1f', ext: ['pptx', 'ppt'] },
  { key: 'image', label: '图片', icon: '▨', color: '#a86ee9', ext: ['png', 'jpg', 'jpeg', 'tif', 'tiff', 'bmp', 'webp'] },
  { key: 'text', label: '文本', icon: '¶', color: '#7d8794', ext: ['txt', 'md', 'html', 'htm', 'json', 'py', 'js'] },
  { key: 'other', label: '其他', icon: '◇', color: '#7d8794', ext: [] },
]

function typeOf(fileType = '', fileName = '') {
  const src = (fileType || '').toLowerCase().replace(/^\./, '') || (fileName || '').split('.').pop().toLowerCase()
  if (!src) return TYPE_MAP[TYPE_MAP.length - 1]
  return TYPE_MAP.find(t => t.ext.includes(src)) || TYPE_MAP[TYPE_MAP.length - 1]
}

// 标签主题色池（按标签名哈希取稳定色，简洁而克制）
const TAG_COLORS = ['#3681ff', '#a05eef', '#e0673c', '#26a69a', '#7b6fe0', '#d65f83', '#5c8dd6', '#3aa76d']
function tagColor(tag) {
  let h = 0
  for (let i = 0; i < tag.length; i++) h = (h * 31 + tag.charCodeAt(i)) >>> 0
  return TAG_COLORS[h % TAG_COLORS.length]
}

export default function IngestPage() {
  const { showToast } = useToast()

  // —— 入库操作（收进左侧栏）——
  const [upMode, setUpMode] = useState('file')       // file | url | clip
  const [url, setUrl] = useState('')
  const [urlBusy, setUrlBusy] = useState(false)
  const [clipTitle, setClipTitle] = useState('')
  const [clipContent, setClipContent] = useState('')
  const [clipBusy, setClipBusy] = useState(false)
  const [dragOver, setDragOver] = useState(false)
  const fileInputRef = useRef(null)

  // —— 文档与筛选 ——
  const [docs, setDocs] = useState([])
  const [loading, setLoading] = useState(true)
  const [allTags, setAllTags] = useState([])
  const [activeType, setActiveType] = useState('all')   // 'all' | type.key
  const [activeTag, setActiveTag] = useState(null)      // null=该类型全部 | tag 名
  const [activeDoc, setActiveDoc] = useState(null)      // 无标签类型下选中的文档 id（单选）
  const [expanded, setExpanded] = useState({})          // 类型展开状态
  const [query, setQuery] = useState('')
  const [stats, setStats] = useState(null)

  const loadDocs = () => {
    setLoading(true)
    api.listDocuments()
      .then(data => setDocs(data.documents || []))
      .catch(() => showToast('加载文档列表失败', 'error'))
      .finally(() => setLoading(false))
  }
  const loadStats = () => api.stats().then(setStats).catch(() => {})
  const reload = () => { loadDocs(); loadStats() }
  useEffect(() => { loadDocs(); loadStats() }, [])

  // 从文档聚合"类型 → 标签（含计数）"
  const typeTree = useMemo(() => {
    const map = {}
    for (const d of docs) {
      const t = typeOf(d.file_type, d.file_name)
      if (!map[t.key]) map[t.key] = { type: t, tags: { _all: 0 }, docs: [] }
      const node = map[t.key]
      node.docs.push(d)
      node.tags._all++
      for (const tag of (d.tags || [])) {
        if (!node.tags[tag]) node.tags[tag] = 0
        node.tags[tag]++
      }
    }
    return Object.values(map)
  }, [docs])

  const allTypeCount = docs.length

  // 当前筛选下的文档
  const activeNode = typeTree.find(n => n.type.key === activeType) || null
  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase()
    return docs.filter(d => {
      if (activeType !== 'all') {
        const t = typeOf(d.file_type, d.file_name)
        if (t.key !== activeType) return false
      }
      if (activeTag) {
        if (!(d.tags || []).includes(activeTag)) return false
      }
      if (!q) return true
      return (d.title || '').toLowerCase().includes(q) || (d.file_name || '').toLowerCase().includes(q)
    })
  }, [docs, activeType, activeTag, query])

  const switchType = (key) => {
    setActiveType(key)
    setActiveTag(null)
    setActiveDoc(null)
  }
  const switchTag = (key, tag) => {
    setActiveType(key)
    setActiveTag(tag)
    setActiveDoc(null)
  }
  const switchDoc = (key, id) => {
    setActiveType(key)
    setActiveTag(null)
    setActiveDoc(prev => prev === id ? null : id)   // 点击同一项则取消选中
  }

  // —— 上传逻辑（沿用原实现）——
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

  // 当前视图标题
  const viewTitle = useMemo(() => {
    if (activeType === 'all') return '全部文档'
    if (activeTag) return `${activeNode?.type.label || ''} · ${activeTag}`
    return activeNode?.type.label || ''
  }, [activeType, activeTag, activeNode])

  const upLabel = upMode === 'file' ? '文件' : upMode === 'url' ? '链接' : '文本'

  return (
    <div className="ingest-page">
      {/* ===== 左侧栏：入库 + 层级树 ===== */}
      <aside className="ingest-sb">
        <div className="ingest-sb-title">文档库</div>

        {/* 入库操作 */}
        <div className="ingest-up card-elev">
          <div className="ingest-up-tabs">
            {[['file', '文件'], ['url', '链接'], ['clip', '文本']].map(([k, l]) => (
              <button
                key={k}
                className={`ingest-up-tab ${upMode === k ? 'active' : ''}`}
                onClick={() => setUpMode(k)}
              >{l}</button>
            ))}
          </div>

          {upMode === 'file' && (
            <div
              className={`ingest-dropzone ${dragOver ? 'dragging' : ''}`}
              onClick={() => fileInputRef.current?.click()}
              onDragOver={e => { e.preventDefault(); setDragOver(true) }}
              onDragLeave={e => { e.preventDefault(); setDragOver(false) }}
              onDrop={e => { e.preventDefault(); setDragOver(false); handleFiles(e.dataTransfer.files) }}
            >
              <div className="ingest-drop-ico">＋</div>
              <div className="ingest-drop-txt">拖入文件，或点击选择</div>
              <div className="ingest-drop-hint">PDF · Word · Excel · PPT · MD · 图片</div>
            </div>
          )}
          {upMode === 'url' && (
            <div className="ingest-up-form">
              <input className="input ingest-input" value={url} placeholder="输入网页 URL…"
                onChange={e => setUrl(e.target.value)}
                onKeyDown={e => { if (e.key === 'Enter') handleUrl() }} />
              <button className="btn btn-primary btn-block" onClick={handleUrl} disabled={urlBusy}>{urlBusy ? '抓取中…' : '入库链接'}</button>
            </div>
          )}
          {upMode === 'clip' && (
            <div className="ingest-up-form">
              <input className="input ingest-input" value={clipTitle} placeholder="标题（可选）"
                onChange={e => setClipTitle(e.target.value)} />
              <textarea className="ingest-clip" value={clipContent} placeholder="粘贴文本内容…"
                onChange={e => setClipContent(e.target.value)} rows={3} />
              <button className="btn btn-primary btn-block" onClick={handleClip} disabled={clipBusy}>{clipBusy ? '入库中…' : '入库文本'}</button>
            </div>
          )}
          <input
            ref={fileInputRef} type="file" multiple hidden
            accept=".pdf,.docx,.doc,.xlsx,.xls,.pptx,.md,.txt,.html,.htm,.png,.jpg,.jpeg,.tif,.tiff,.bmp,.webp,.py,.js,.json,.csv,.tsv"
            onChange={e => { handleFiles(e.target.files); e.target.value = '' }}
          />
        </div>

        {/* 层级树：类型 → 标签 */}
        <div className="ingest-tree">
          <div
            className={`ingest-tn ${activeType === 'all' && !activeTag ? 'active' : ''}`}
            onClick={() => switchType('all')}
          >
            <span className="ingest-tn-ico">🗂</span>
            <span className="ingest-tn-txt">全部</span>
            <span className="ingest-tn-n">{allTypeCount}</span>
          </div>

          {typeTree.map(node => {
            const open = expanded[node.type.key]
            const isParent = activeType === node.type.key && !activeTag
            const tagList = Object.entries(node.tags).filter(([k]) => k !== '_all').sort((a, b) => b[1] - a[1])
            return (
              <div key={node.type.key} className="ingest-te">
                <div
                  className={`ingest-tn ${isParent ? 'active' : ''}`}
                  onClick={() => { switchType(node.type.key); setExpanded(x => ({ ...x, [node.type.key]: !open })) }}
                >
                  <span className={`ingest-tn-caret ${open ? 'open' : ''}`}>›</span>
                  <span className="ingest-tn-ico" style={{ color: node.type.color, background: node.type.color + '1c' }}>{node.type.icon}</span>
                  <span className="ingest-tn-txt">{node.type.label}</span>
                  <span className="ingest-tn-n">{node.tags._all}</span>
                </div>
                {open && tagList.length > 0 && (
                  <div className="ingest-tc">
                    {tagList.map(([tag, cnt]) => (
                      <div
                        key={tag}
                        className={`ingest-tag ${activeType === node.type.key && activeTag === tag ? 'active' : ''}`}
                        onClick={() => switchTag(node.type.key, tag)}
                      >
                        <span className="ingest-tag-dot" style={{ background: tagColor(tag) }} />
                        <span className="ingest-tag-txt">{tag}</span>
                        <span className="ingest-tag-n">{cnt}</span>
                      </div>
                    ))}
                  </div>
                )}
                {open && tagList.length === 0 && node.docs.length > 0 && (
                  <div className="ingest-tc">
                    {node.docs.map(d => (
                      <div
                        key={d.id}
                        className={`ingest-docleaf ${activeType === node.type.key && activeDoc === d.id ? 'on' : ''}`}
                        onClick={() => switchDoc(node.type.key, d.id)}
                      >
                        <span className="ingest-docleaf-ico" style={{ color: node.type.color }}>{node.type.icon}</span>
                        <span className="ingest-docleaf-txt">{d.title || d.file_name}</span>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            )
          })}
        </div>
      </aside>

      {/* ===== 右侧：文档列表 ===== */}
      <main className="ingest-main">
        <div className="ingest-head">
          <div className="ingest-crumb">
            <span className="ingest-crumb-root">文档库 /</span>
            <span className="ingest-crumb-cur">{viewTitle}</span>
          </div>
          <span className="ingest-count">{filtered.length} 个文档</span>
        </div>

        <div className="ingest-toolbar">
          <input className="ingest-search" placeholder="搜索标题或文件名…"
            value={query} onChange={e => setQuery(e.target.value)} />
          <div className="ingest-head-stats">
            <span className="ingest-hs"><b>{stats?.chunks ?? '–'}</b>&nbsp;分块</span>
            <span className="ingest-hs"><b>{stats?.graph_nodes ?? '–'}</b>&nbsp;节点</span>
            <span className="ingest-hs"><b>{stats?.total_tokens ? (stats.total_tokens / 1000).toFixed(1) + 'k' : '–'}</b>&nbsp;tokens</span>
          </div>
        </div>

        {loading ? (
          <div className="ingest-empty">加载中…</div>
        ) : filtered.length === 0 ? (
          <div className="ingest-empty">{docs.length === 0 ? '暂无文档，从左侧添加入库' : '没有匹配的文档'}</div>
        ) : (
          <div className="ingest-list">
            {filtered.map(d => {
              const t = typeOf(d.file_type, d.file_name)
              const rowActive = activeDoc === d.id
              return (
                <div className={`ingest-row ${rowActive ? 'active' : ''}`} key={d.id}>
                  <div className="ingest-row-ico" style={{ color: t.color, background: t.color + '1c' }}>{t.icon}</div>
                  <div className="ingest-row-main">
                    <div className="ingest-row-title">{d.title || d.file_name}</div>
                    <div className="ingest-row-sub">{d.file_name} · {formatSize(d.file_size) || t.label}</div>
                  </div>
                  {(d.tags || []).length > 0 && (
                    <div className="ingest-row-tags">
                      {d.tags.slice(0, 3).map(tg => (
                        <span key={tg} className="ingest-row-tag">{tg}</span>
                      ))}
                    </div>
                  )}
                  <div className="ingest-row-meta">
                    <span>{d.chunk_count || 0} 块</span>
                    <span>{formatDate(d.created_at)}</span>
                  </div>
                  <button className="ingest-row-del" title="删除"
                    onClick={(e) => { e.stopPropagation(); handleDelete(d) }}>×</button>
                </div>
              )
            })}
          </div>
        )}
      </main>
    </div>
  )
}
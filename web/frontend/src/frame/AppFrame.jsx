import { useCallback, useEffect, useRef, useState } from 'react'
import { computeColumns, SIDEBAR_AUTO_COLLAPSE, SIDEBAR_DEFAULT, DETAILS_DEFAULT } from './columns.js'
import Sidebar from './Sidebar.jsx'
import TopTabs from './TopTabs.jsx'
import SettingsDrawer from './SettingsDrawer.jsx'
import DetailsPanel from './DetailsPanel.jsx'
import Pages from './Pages.jsx'
import { QAProvider, useQA } from '../store/qa.jsx'

function DragHandle({ left, side, onStart, onDrag, onEnd }) {
  const [dragging, setDragging] = useState(false)
  const origin = useRef(0)
  const latest = useRef(0)
  const frame = useRef(null)
  const cbs = useRef({ onStart, onDrag, onEnd })
  cbs.current = { onStart, onDrag, onEnd }

  const onPointerDown = (e) => {
    e.preventDefault()
    e.currentTarget.setPointerCapture(e.pointerId)
    origin.current = e.clientX
    latest.current = e.clientX
    cbs.current.onStart()
    setDragging(true)
  }
  const onPointerMove = (e) => {
    if (!e.currentTarget.hasPointerCapture(e.pointerId)) return
    latest.current = e.clientX
    if (frame.current !== null) return
    frame.current = requestAnimationFrame(() => {
      frame.current = null
      cbs.current.onDrag(latest.current - origin.current)
    })
  }
  const onPointerUp = (e) => {
    if (!e.currentTarget.hasPointerCapture(e.pointerId)) return
    e.currentTarget.releasePointerCapture(e.pointerId)
    if (frame.current !== null) { cancelAnimationFrame(frame.current); frame.current = null }
    cbs.current.onDrag(latest.current - origin.current)
    setDragging(false)
    cbs.current.onEnd()
  }

  return (
    <div
      className="frame-handle"
      style={{ left }}
      data-side={side}
      data-dragging={dragging || undefined}
      onPointerDown={onPointerDown}
      onPointerMove={onPointerMove}
      onPointerUp={onPointerUp}
    />
  )
}

export default function AppFrame({ settings, updateSettings, currentPage, setCurrentPage }) {
  return (
    <QAProvider settings={settings}>
      <AppFrameInner
        settings={settings}
        updateSettings={updateSettings}
        currentPage={currentPage}
        setCurrentPage={setCurrentPage}
      />
    </QAProvider>
  )
}

function AppFrameInner({ settings, updateSettings, currentPage, setCurrentPage }) {
  const { streaming: qaStreaming } = useQA()
  const frameRef = useRef(null)
  const [viewport, setViewport] = useState(() => window.innerWidth)

  // 侧栏：0=折叠；details：0=关闭
  const [sidebarPref, setSidebarPref] = useState(SIDEBAR_DEFAULT)
  const [detailsPref, setDetailsPref] = useState(0)
  const [detailsContent, setDetailsContent] = useState(null) // {title, node}
  const [settingsOpen, setSettingsOpen] = useState(false)
  const [narrowExpanded, setNarrowExpanded] = useState(false)
  const [dragging, setDragging] = useState(false)

  // 窄屏自动收起
  const narrow = viewport < SIDEBAR_AUTO_COLLAPSE
  const sidebarCollapsed = narrow ? !narrowExpanded : sidebarPref === 0
  const sidebarPreference = sidebarCollapsed ? 0 : sidebarPref === 0 ? SIDEBAR_DEFAULT : sidebarPref

  const cols = computeColumns(viewport, sidebarPreference, detailsPref === 0 ? 0 : detailsPref)
  const colsRef = useRef(cols)
  colsRef.current = cols

  // 跟踪视口
  useEffect(() => {
    const el = frameRef.current
    if (!el) return
    let raf = null
    const observer = new ResizeObserver(() => {
      if (raf !== null) return
      raf = requestAnimationFrame(() => {
        raf = null
        const width = el.getBoundingClientRect().width
        if (width > 0) setViewport(width)
      })
    })
    observer.observe(el)
    return () => { observer.disconnect(); if (raf !== null) cancelAnimationFrame(raf) }
  }, [])

  const sidebarBase = useRef(0)
  const detailsBase = useRef(0)
  const onSidebarStart = useCallback(() => { sidebarBase.current = colsRef.current.sidebar; setDragging(true) }, [])
  const onDetailsStart = useCallback(() => { detailsBase.current = colsRef.current.details; setDragging(true) }, [])
  const onSidebarDrag = useCallback((dx) => setSidebarPref(sidebarBase.current + dx), [])
  const onDetailsDrag = useCallback((dx) => setDetailsPref(detailsBase.current - dx), [])
  const onDragEnd = useCallback(() => setDragging(false), [])

  const toggleSidebar = () => {
    if (narrow) { setNarrowExpanded(v => !v); return }
    setSidebarPref(v => (v === 0 ? SIDEBAR_DEFAULT : 0))
  }

  const openDetails = useCallback((content) => {
    setDetailsContent(content)
    setDetailsPref(v => (v === 0 ? DETAILS_DEFAULT : v))
  }, [])

  const closeDetails = useCallback(() => setDetailsPref(0), [])

  return (
    <div
        ref={frameRef}
        className="app-frame"
        style={{ gridTemplateColumns: `${cols.sidebar}px minmax(0, 1fr) ${cols.details}px` }}
        data-dragging={dragging || undefined}
      >
        <div className="frame-col frame-sidebar">
          <Sidebar
            collapsed={sidebarCollapsed}
            width={cols.sidebar}
            onToggle={toggleSidebar}
            onOpenSettings={() => setSettingsOpen(true)}
            currentPage={currentPage}
            setCurrentPage={setCurrentPage}
          />
        </div>

        <div className="frame-col frame-center">
          <TopTabs
            currentPage={currentPage}
            setCurrentPage={setCurrentPage}
            hidden={currentPage === 'qa' && qaStreaming}
          />
          <div className="frame-page">
            <Pages
              currentPage={currentPage}
              settings={settings}
              openDetails={openDetails}
              closeDetails={closeDetails}
            />
          </div>
        </div>

        <div className="frame-col frame-details">
          <DetailsPanel content={detailsContent} onClose={closeDetails} />
        </div>

        {!sidebarCollapsed && (
          <DragHandle side="sidebar" left={cols.sidebar} onStart={onSidebarStart} onDrag={onSidebarDrag} onEnd={onDragEnd} />
        )}
        {cols.details > 0 && (
          <DragHandle side="details" left={viewport - cols.details} onStart={onDetailsStart} onDrag={onDetailsDrag} onEnd={onDragEnd} />
        )}

        {settingsOpen && (
          <SettingsDrawer settings={settings} updateSettings={updateSettings} onClose={() => setSettingsOpen(false)} />
        )}
      </div>
  )
}
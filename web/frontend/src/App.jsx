import { useEffect, useState } from 'react'
import AppFrame from './frame/AppFrame.jsx'
import { loadSettings, saveSettings, applyTheme } from './store/settings.js'
import { ToastProvider, useToast } from './ui/Toast.jsx'

export default function App() {
  const [settings, setSettings] = useState(null)
  const [currentPage, setCurrentPage] = useState('qa')

  // 启动时加载后端设置并应用主题
  useEffect(() => {
    let alive = true
    loadSettings().then(s => {
      if (!alive) return
      setSettings(s)
      applyTheme(s)
    })
    return () => { alive = false }
  }, [])

  const updateSettings = async (patch) => {
    const next = await saveSettings(patch)
    setSettings(next)
    applyTheme(next)
  }

  if (!settings) {
    return <div className="app-boot"><div className="boot-spinner" /><span>加载设置…</span></div>
  }

  return (
    <ToastProvider>
      <AppFrame
        settings={settings}
        updateSettings={updateSettings}
        currentPage={currentPage}
        setCurrentPage={setCurrentPage}
      />
    </ToastProvider>
  )
}
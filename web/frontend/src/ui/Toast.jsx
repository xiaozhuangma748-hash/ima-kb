// Toast 通知：成功/错误/信息

import React, { createContext, useCallback, useContext, useRef, useState } from 'react'

const ToastCtx = createContext(null)

export function useToast() {
  const ctx = useContext(ToastCtx)
  if (!ctx) {
    // 允许在 Provider 外使用（退化：console）
    return { showToast: (msg, type) => console.log(`[toast:${type}]`, msg) }
  }
  return ctx
}

export function ToastProvider({ children }) {
  const [toasts, setToasts] = useState([])
  const seq = useRef(0)

  const showToast = useCallback((message, type = 'info', duration = 3500) => {
    const id = ++seq.current
    setToasts(prev => [...prev, { id, message, type }])
    setTimeout(() => {
      setToasts(prev => prev.filter(t => t.id !== id))
    }, duration)
  }, [])

  const icons = { success: '✓', error: '✗', info: 'ℹ' }

  return (
    <ToastCtx.Provider value={{ showToast }}>
      {children}
      <div className="toast-container">
        {toasts.map(t => (
          <div key={t.id} className={`toast toast-${t.type}`}>
            <span className={`toast-icon toast-${t.type}-icon`}>{icons[t.type] || icons.info}</span>
            <span>{t.message}</span>
          </div>
        ))}
      </div>
    </ToastCtx.Provider>
  )
}
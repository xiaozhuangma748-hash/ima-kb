// 通用 UI：按钮 / 卡片 / 开关 / 标签

import React from 'react'

export function Btn({ variant = 'ghost', size = 'md', className = '', children, ...rest }) {
  const cls = ['btn'];
  if (variant === 'primary') cls.push('btn-primary');
  if (size === 'sm') cls.push('btn-sm');
  if (className) cls.push(className);
  return <button className={cls.join(' ')} {...rest}>{children}</button>
}

export function Card({ className = '', children, style }) {
  return <div className={`card ${className}`} style={style}>{children}</div>
}

export function Toggle({ on, onChange, label }) {
  return (
    <div className="toggle-row" onClick={() => onChange?.(!on)} role="switch" aria-checked={on}>
      {label && <span className="toggle-label">{label}</span>}
      <div className={`toggle ${on ? 'on' : ''}`} />
    </div>
  )
}

export function Tag({ color = '', children }) {
  const cls = ['tag'];
  if (color) cls.push(`tag-${color}`);
  return <span className={cls.join(' ')}>{children}</span>
}
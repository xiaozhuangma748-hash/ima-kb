import { useEffect, useState } from 'react'
import { api } from '../api.js'
import { Btn, Card } from '../ui/Base.jsx'
import { useToast } from '../ui/Toast.jsx'

const PERSONA_STYLES = [
  { style: 'scholar', icon: '🎓', name: 'scholar 深度分析模式', desc: '深度分析·引用密集·表格对比', cls: 'text-orange' },
  { style: 'warrior', icon: '⚔️', name: 'warrior 直接行动模式', desc: '直接结论·行动建议·简洁', cls: '' },
  { style: 'artisan', icon: '🔧', name: 'artisan 结构化模式', desc: '结构化·小标题·可视化', cls: '' },
  { style: 'auto', icon: '🤖', name: 'auto 自动模式', desc: '根据问题自动选择', cls: '' },
]

export default function PetPage() {
  const { showToast } = useToast()
  const [pet, setPet] = useState(null)

  const load = () => api.petStatus().then(setPet).catch(() => {})
  useEffect(() => { load() }, [])

  const adopt = () => {
    const name = window.prompt('给宠物起个名字:') || '小白'
    api.petAdopt(name).then(load)
  }

  const interact = (action) => api.petInteract(action).then(load)
  const setStyle = (style) => api.petStyle(style).then(() => { load(); showToast(`已切换 ${style} 模式`, 'success') })

  if (!pet || !pet.found) {
    return (
      <div className="pet-page">
        <div className="page-header">
          <div>
            <div className="page-title">🐾 宠物管理</div>
            <div className="page-subtitle">宠物管理员 · 4 种回复模式 · 升级养成</div>
          </div>
        </div>
        <div className="pet-empty-state">
          <p>尚未领养宠物</p>
          <Btn variant="primary" onClick={adopt}>领养宠物</Btn>
        </div>
      </div>
    )
  }

  return (
    <div className="pet-page">
      <div className="page-header">
        <div>
          <div className="page-title">🐾 宠物管理</div>
          <div className="page-subtitle">宠物管理员 · 4 种回复模式 · 升级养成</div>
        </div>
      </div>

      <div className="pet-layout">
        <div className="pet-display">
          <pre className="pet-ascii">{pet.ascii_art || '…'}</pre>
          <div className="pet-name">{pet.name}</div>
          <div className="pet-level">Lv.{pet.level} · {pet.style} 模式</div>
          <div className="pet-stats">
            <div className="pet-stat">
              <div className="pet-stat-label">😊 心情</div>
              <div className="pet-stat-bar"><div className="pet-stat-fill fill-orange" style={{ width: `${pet.mood}%` }} /></div>
            </div>
            <div className="pet-stat">
              <div className="pet-stat-label">🍖 饱食</div>
              <div className="pet-stat-bar"><div className="pet-stat-fill fill-teal" style={{ width: `${pet.hunger}%` }} /></div>
            </div>
            <div className="pet-stat">
              <div className="pet-stat-label">⚡ 能量</div>
              <div className="pet-stat-bar"><div className="pet-stat-fill fill-purple" style={{ width: `${pet.energy}%` }} /></div>
            </div>
          </div>
          <div className="pet-actions">
            <Btn className="pet-interact-btn" onClick={() => interact('feed')}>🍖 喂食</Btn>
            <Btn className="pet-interact-btn" onClick={() => interact('play')}>🎾 玩耍</Btn>
            <Btn className="pet-interact-btn" onClick={() => interact('train')}>📚 训练</Btn>
          </div>
        </div>

        <Card>
          <div className="card-title mb-16">🎨 回复模式</div>
          <div className="persona-grid">
            {PERSONA_STYLES.map(p => (
              <div
                key={p.style}
                className={`persona-card-style ${pet.style === p.style ? 'active' : ''}`}
                onClick={() => setStyle(p.style)}
              >
                <div className="persona-card-icon">{p.icon}</div>
                <div className={`persona-card-name ${p.cls}`}>{p.name}</div>
                <div className="persona-card-desc">{p.desc}</div>
              </div>
            ))}
          </div>
        </Card>
      </div>
    </div>
  )
}
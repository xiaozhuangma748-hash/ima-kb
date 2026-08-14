// 设置弹窗：左侧菜单（基础设置 / 回复模式）+ 右侧内容区
// 基础设置：外观（主题/主题色）+ 内容开关
// 回复模式：四种模式切换
// 持久化到后端 config 文件
import { useState } from 'react'
import { useQA } from '../store/qa.jsx'
import { Toggle } from '../ui/Base.jsx'

const THEME_OPTIONS = [
  { key: 'dark', label: '深色' },
  { key: 'light', label: '浅色' },
  { key: 'system', label: '跟随系统' },
]

const ACCENT_OPTIONS = [
  { key: 'blue', label: '蓝' },
  { key: 'green', label: '绿' },
  { key: 'purple', label: '紫' },
  { key: 'orange', label: '橙' },
]

const TOGGLES = [
  { key: 'streaming', label: '流式输出' },
  { key: 'use_rerank', label: 'LLM 重排序' },
  { key: 'use_vector', label: '向量检索' },
  { key: 'auto_expand_sources', label: '引用来源自动展开' },
  { key: 'show_suggestions', label: '输入建议' },
  { key: 'animations', label: '动画过渡' },
]

const MENUS = [
  { key: 'basic', label: '基础设置', icon: '🎛️' },
  { key: 'reply', label: '回复模式', icon: '💬' },
]

const PERSONAS = [
  {
    key: 'scholar', label: '深度分析模式', icon: '🎓',
    desc: '深度分析型',
    explanation: '严谨、博学、引用密集。适合需要查证政策原文、条文对比、严谨结论的场景。',
    traits: ['先结论后论证', '每个观点附带原文引用 [n]', '偏好表格对比、条文列举', '主动指出例外与边界条件', '语气正式客观'],
  },
  {
    key: 'warrior', label: '直接行动模式', icon: '⚔️',
    desc: '直接行动型',
    explanation: '果断、高效、行动导向。适合快速要答案、需要明确行动建议的场景。',
    traits: ['开门见山给答案', '引用最少但最相关', '主动给行动建议', '偏好列表、步骤', '语气简洁有力'],
  },
  {
    key: 'artisan', label: '结构化模式', icon: '🔧',
    desc: '结构化型',
    explanation: '细致、有条理、注重呈现。适合需要条理清晰、章节分明、便于阅读的长回答。',
    traits: ['结构化分块，带小标题', '偏好表格、流程图描述', '主动总结要点', '每节附引用', '语气温和清晰'],
  },
  {
    key: 'neutral', label: '综合模式', icon: '🤖',
    desc: '综合模式',
    explanation: '综合三种模式特点，根据问题自动平衡。适合不确定选哪种模式时使用。',
    traits: ['先结论 + 适度引用', '简单结构化', '语气平和', '灵活适配问题类型'],
  },
]

export default function SettingsDrawer({ settings, updateSettings, onClose }) {
  const { persona, setPersona } = useQA()
  const [menu, setMenu] = useState('basic')
  const set = (k, v) => updateSettings({ [k]: v })

  return (
    <div className="settings-overlay" onClick={onClose}>
      <div className="settings-modal" onClick={(e) => e.stopPropagation()}>
        <div className="settings-head">
          <h2>设置</h2>
          <button className="drawer-close" onClick={onClose}>×</button>
        </div>

        <div className="settings-body">
          <nav className="settings-menu">
            {MENUS.map(m => (
              <button
                key={m.key}
                className={`settings-menu-item ${menu === m.key ? 'active' : ''}`}
                onClick={() => setMenu(m.key)}
              >
                <span>{m.label}</span>
              </button>
            ))}
          </nav>

          <div className="settings-content">
            {menu === 'basic' && (
              <>
                <section className="drawer-sec">
                  <h3>外观</h3>
                  <div className="setting-row">
                    <span className="setting-label">主题</span>
                    <div className="seg">
                      {THEME_OPTIONS.map(o => (
                        <button
                          key={o.key}
                          className={`seg-btn ${settings.theme === o.key ? 'active' : ''}`}
                          onClick={() => set('theme', o.key)}
                        >{o.label}</button>
                      ))}
                    </div>
                  </div>
                  <div className="setting-row">
                    <span className="setting-label">主题色</span>
                    <div className="swatches">
                      {ACCENT_OPTIONS.map(o => (
                        <button
                          key={o.key}
                          className={`swatch swatch-${o.key} ${settings.accent === o.key ? 'active' : ''}`}
                          title={o.label}
                          onClick={() => set('accent', o.key)}
                        />
                      ))}
                    </div>
                  </div>
                </section>

                <section className="drawer-sec">
                  <h3>内容</h3>
                  {TOGGLES.map(t => (
                    <Toggle
                      key={t.key}
                      label={t.label}
                      on={!!settings[t.key]}
                      onChange={(v) => set(t.key, v)}
                    />
                  ))}
                </section>
              </>
            )}

            {menu === 'reply' && (
              <section className="drawer-sec">
                <h3>回复模式</h3>
                <div className="persona-list">
                  {PERSONAS.map(p => (
                    <button
                      key={p.key}
                      className={`persona-card ${persona === p.key ? 'active' : ''}`}
                      onClick={() => setPersona(p.key)}
                    >
                      <span className="persona-card-head">
                        <span className="persona-name">{p.label}</span>
                        <span className={`persona-tag ${persona === p.key ? 'cur' : ''}`}>{persona === p.key ? '当前使用' : p.desc}</span>
                      </span>
                      <span className="persona-expl">{p.explanation}</span>
                    </button>
                  ))}
                </div>
              </section>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}
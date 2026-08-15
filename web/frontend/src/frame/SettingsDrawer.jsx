// 设置弹窗：左侧菜单（基础设置 / 回复模式 / 模型管理）+ 右侧内容区
// 基础设置：外观（主题/主题色）+ 内容开关
// 回复模式：四种模式切换
// 模型管理：查看/添加/删除 LLM 模型
// 持久化到后端 config 文件
import { useEffect, useState } from 'react'
import { useQA, RETRIEVAL_MODES } from '../store/qa.jsx'
import { Toggle } from '../ui/Base.jsx'
import { api } from '../api.js'

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
  { key: 'models', label: '模型管理', icon: '🤖' },
  { key: 'retrieval', label: '检索预设', icon: '🔍' },
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

const EMPTY_FORM = { id: '', name: '', desc: '', base_url: '', api_key: '' }

export default function SettingsDrawer({ settings, updateSettings, onClose }) {
  const { persona, setPersona, retrieval, setRetrieval } = useQA()
  const [menu, setMenu] = useState('basic')
  const set = (k, v) => updateSettings({ [k]: v })

  // ---- 模型管理状态 ----
  const [models, setModels] = useState([])
  const [currentModel, setCurrentModel] = useState('')
  const [form, setForm] = useState(EMPTY_FORM)
  const [formError, setFormError] = useState('')
  const [formMsg, setFormMsg] = useState('')

  const loadModels = () => {
    api.getModels().then(data => {
      setModels(data.models || [])
      setCurrentModel(data.current || '')
    }).catch(() => {})
  }

  useEffect(() => {
    if (menu === 'models') loadModels()
  }, [menu])

  const addModel = async () => {
    setFormError('')
    setFormMsg('')
    if (!form.id.trim()) {
      setFormError('请填写模型 ID（如 deepseek-chat）')
      return
    }
    try {
      const data = await api.addModel(form)
      setModels(data.models || [])
      setForm(EMPTY_FORM)
      setFormMsg('模型已添加')
    } catch (e) {
      setFormError(e.message || '添加失败')
    }
  }

  const deleteModel = async (id) => {
    if (!confirm(`确定删除模型 ${id}？`)) return
    try {
      const data = await api.deleteModel(id)
      setModels(data.models || [])
      // 若删除的是当前使用中的模型，回退到列表里第一个模型
      if (currentModel === id) {
        const first = (data.models || [])[0]
        if (first) {
          const r = await api.setModel(first.id)
          setCurrentModel(r.model)
        }
      }
    } catch (e) {
      setFormError(e.message || '删除失败')
    }
  }

  const switchModel = async (id) => {
    try {
      const data = await api.setModel(id)
      setCurrentModel(data.model)
    } catch (e) {
      setFormError(e.message || '切换失败')
    }
  }

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

            {menu === 'models' && (
              <section className="drawer-sec">
                <h3>模型管理</h3>
                <p className="model-hint">内置模型不可删除。自定义模型可设置独立接口地址（base_url）与 API Key，留空则使用全局配置。</p>

                <div className="model-list">
                  {models.map(m => (
                    <div
                      key={m.id}
                      className={`model-row ${currentModel === m.id ? 'active' : ''}`}
                      onClick={() => switchModel(m.id)}
                    >
                      <div className="model-row-main">
                        <div className="model-row-name">
                          <span className="model-name">{m.name || m.id}</span>
                          {m.builtin && <span className="model-badge">内置</span>}
                          {currentModel === m.id && <span className="model-badge cur">使用中</span>}
                        </div>
                        <div className="model-row-sub">
                          <span className="model-id">{m.id}</span>
                          {m.desc && <span className="model-desc">{m.desc}</span>}
                        </div>
                      </div>
                      {!m.builtin && (
                        <div className="model-row-actions">
                          <button
                            className="model-btn model-btn--del"
                            onClick={(e) => { e.stopPropagation(); deleteModel(m.id) }}
                          >删除</button>
                        </div>
                      )}
                    </div>
                  ))}
                </div>

                <h3 className="model-add-title">添加模型</h3>
                <div className="model-form">
                  <div className="model-form-grid">
                    <div className="model-field">
                      <label>模型 ID *</label>
                      <input
                        value={form.id}
                        placeholder="如 deepseek-chat"
                        onChange={e => setForm({ ...form, id: e.target.value })}
                      />
                    </div>
                    <div className="model-field">
                      <label>显示名称</label>
                      <input
                        value={form.name}
                        placeholder="如 DeepSeek-V3"
                        onChange={e => setForm({ ...form, name: e.target.value })}
                      />
                    </div>
                    <div className="model-field">
                      <label>描述</label>
                      <input
                        value={form.desc}
                        placeholder="可选"
                        onChange={e => setForm({ ...form, desc: e.target.value })}
                      />
                    </div>
                    <div className="model-field">
                      <label>接口地址 base_url</label>
                      <input
                        value={form.base_url}
                        placeholder="如 https://api.example.com/v1（可选）"
                        onChange={e => setForm({ ...form, base_url: e.target.value })}
                      />
                    </div>
                    <div className="model-field model-field--full">
                      <label>API Key</label>
                      <input
                        value={form.api_key}
                        type="password"
                        placeholder="留空则使用全局配置的 Key"
                        onChange={e => setForm({ ...form, api_key: e.target.value })}
                      />
                    </div>
                  </div>
                  {formError && <div className="model-form-msg model-form-msg--err">{formError}</div>}
                  {formMsg && <div className="model-form-msg">{formMsg}</div>}
                  <button className="model-btn model-btn--add" onClick={addModel}>+ 添加模型</button>
                </div>
              </section>
            )}

            {menu === 'retrieval' && (
              <section className="drawer-sec">
                <h3>检索预设</h3>
                <p className="model-hint">选择问答时的检索方式。默认智能混合（向量 + 关键词 · LLM 重排序）。</p>
                <div className="persona-list">
                  {RETRIEVAL_MODES.map(m => (
                    <button
                      key={m.key}
                      className={`persona-card ${retrieval.key === m.key ? 'active' : ''}`}
                      onClick={() => setRetrieval({ key: m.key, useVector: m.useVector, useRerank: m.useRerank })}
                    >
                      <span className="persona-card-head">
                        <span className="persona-name">{m.label}</span>
                        <span className={`persona-tag ${retrieval.key === m.key ? 'cur' : ''}`}>{retrieval.key === m.key ? '当前使用' : m.desc}</span>
                      </span>
                      <span className="persona-expl">{m.desc}</span>
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
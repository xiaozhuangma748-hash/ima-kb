// 全局设置：主题 / 主题色 / 内容开关
// 持久化到后端 config 文件（storage/web_settings.json）

const DEFAULTS = {
  theme: 'dark',            // dark | light | system
  accent: 'blue',           // blue | green | purple | orange
  streaming: true,
  use_rerank: true,
  use_vector: true,
  auto_expand_sources: true,
  show_suggestions: true,
  animations: true,
};

const THEMES = ['dark', 'light', 'system'];
const ACCENTS = ['blue', 'green', 'purple', 'orange'];

let cached = null;
let loadPromise = null;

export function getDefaultSettings() {
  return { ...DEFAULTS };
}

// 合并后端返回，丢弃未知键
function normalize(raw) {
  const out = { ...DEFAULTS };
  if (raw && typeof raw === 'object') {
    for (const k of Object.keys(DEFAULTS)) {
      if (raw[k] !== undefined) out[k] = raw[k];
    }
  }
  if (!THEMES.includes(out.theme)) out.theme = 'dark';
  if (!ACCENTS.includes(out.accent)) out.accent = 'blue';
  return out;
}

export async function loadSettings() {
  if (cached) return cached;
  if (!loadPromise) {
    loadPromise = fetch('/api/settings')
      .then(r => (r.ok ? r.json() : {}))
      .then(normalize)
      .then(s => { cached = s; return s; })
      .catch(() => { cached = getDefaultSettings(); return cached; });
  }
  return loadPromise;
}

export async function saveSettings(next) {
  const merged = normalize({ ...getDefaultSettings(), ...next });
  cached = merged;
  try {
    await fetch('/api/settings', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(merged),
    });
  } catch { /* 后端不可达时静默，仅保留内存态 */ }
  return merged;
}

// 应用主题/主题色到 <html> 属性
export function applyTheme(s) {
  const root = document.documentElement;
  let effective = s.theme;
  if (effective === 'system') {
    effective = window.matchMedia('(prefers-color-scheme: light)').matches ? 'light' : 'dark';
  }
  root.setAttribute('data-theme', effective);
  root.setAttribute('data-accent', s.accent);
  root.classList.toggle('no-anim', !s.animations);
}
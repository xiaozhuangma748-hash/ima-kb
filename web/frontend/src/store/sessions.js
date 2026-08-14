// 会话历史：localStorage 持久化
// 结构 { id, title, created_at, messages: [{role, content}] }，上限 20 条

const STORAGE_KEY = 'ima_kb.sessions.v1';
const MAX_SESSIONS = 20;

function loadRaw() {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    return raw ? JSON.parse(raw) : [];
  } catch {
    return [];
  }
}

export function loadSessions() {
  return loadRaw();
}

function persist(list) {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(list.slice(0, MAX_SESSIONS)));
  } catch { /* 存储满/隐私模式时静默 */ }
}

export function createSession(messages = []) {
  const list = loadRaw();
  const title = firstTitle(messages);
  const session = {
    id: `s-${Date.now()}-${Math.random().toString(36).slice(2, 6)}`,
    title,
    created_at: new Date().toISOString(),
    messages,
  };
  list.unshift(session);
  persist(list);
  return session;
}

export function updateSession(id, patch) {
  const list = loadRaw();
  const idx = list.findIndex(s => s.id === id);
  if (idx === -1) return null;
  list[idx] = { ...list[idx], ...patch };
  if (patch.messages) list[idx].title = firstTitle(patch.messages);
  persist(list);
  return list[idx];
}

export function deleteSession(id) {
  const list = loadRaw().filter(s => s.id !== id);
  persist(list);
  return list;
}

function firstTitle(messages) {
  if (!messages) return '新会话';
  const first = messages.find(m => m.role === 'user');
  const text = (first && first.content || '').trim();
  return text ? text.slice(0, 20) + (text.length > 20 ? '…' : '') : '新会话';
}
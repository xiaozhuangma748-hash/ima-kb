// API 封装：统一 fetch + 错误处理

async function request(url, options = {}) {
  const res = await fetch(url, options);
  if (!res.ok) {
    let detail = `HTTP ${res.status}`;
    try {
      const body = await res.json();
      detail = body.detail || detail;
    } catch { /* ignore */ }
    throw new Error(detail);
  }
  return res.json();
}

export const api = {
  // ---- 统计 / 设置 ----
  stats: () => request('/api/stats'),
  getSettings: () => request('/api/settings'),
  saveSettings: (settings) => request('/api/settings', {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(settings),
  }),

  // ---- 搜索 ----
  search: (q, opts = {}) => {
    const params = new URLSearchParams({ q, limit: String(opts.limit || 10) });
    if (opts.use_vector !== undefined) params.set('use_vector', String(opts.use_vector));
    if (opts.use_rerank !== undefined) params.set('use_rerank', String(opts.use_rerank));
    return request(`/api/search?${params.toString()}`);
  },

  // ---- 入库 ----
  upload: (formData) => request('/api/ingest/upload', { method: 'POST', body: formData }),
  ingestUrl: (url) => request('/api/ingest/url', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ url }),
  }),
  ingestClip: (title, content) => request('/api/ingest/clip', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ title, content }),
  }),

  // ---- 数据分析 ----
  analyze: (file, aiInsight = true) => {
    const fd = new FormData();
    fd.append('file', file);
    return request(`/api/analyze?ai_insight=${aiInsight}`, { method: 'POST', body: fd });
  },

  // ---- 图谱 ----
  graphData: () => request('/api/graph/data'),
  graphNeighbors: (name) => request(`/api/graph/neighbors/${encodeURIComponent(name)}`),
  graphBuild: () => request('/api/graph/build', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ force: true }),
  }),

  // ---- 宠物 ----
  petStatus: () => request('/api/pet/status'),
  petAdopt: (name) => request('/api/pet/adopt', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ name }),
  }),
  petInteract: (action) => request('/api/pet/interact', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ action }),
  }),
  petStyle: (style) => request('/api/pet/style', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ style }),
  }),

  // ---- 头像 ----
  avatar: async () => {
    const res = await fetch('/api/avatar');
    return res.json();
  },
  uploadAvatar: (file) => {
    const fd = new FormData();
    fd.append('file', file);
    return request('/api/avatar', { method: 'POST', body: fd });
  },
};

// SSE 流式问答：读取 /api/qa/stream 的 NDJSON（以 \n\n 分隔的 SSE 块）
export function streamQA({ question, history, persona, signal, onStage, onToken, onDone, onError }) {
  return fetch('/api/qa/stream', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ question, history, persona }),
    signal,
  })
    .then(resp => {
      const reader = resp.body.getReader();
      const decoder = new TextDecoder();
      let buffer = '';

      function process() {
        return reader.read().then(({ done, value }) => {
          if (done) return;
          buffer += decoder.decode(value, { stream: true });

          while (buffer.includes('\n\n')) {
            const idx = buffer.indexOf('\n\n');
            const block = buffer.slice(0, idx);
            buffer = buffer.slice(idx + 2);

            const lines = block.split('\n');
            let data = '';
            for (const line of lines) {
              if (line.startsWith('data: ')) data = line.slice(6);
              else if (line.startsWith('data:')) data = line.slice(5);
            }
            if (!data) continue;

            let parsed;
            try { parsed = JSON.parse(data); } catch { continue; }

            if (parsed.type === 'stage' && onStage) onStage(parsed.stage, parsed.count);
            else if (parsed.type === 'token' && onToken) onToken(parsed.text);
            else if (parsed.type === 'done' && onDone) onDone(parsed);
            else if (parsed.type === 'error' && onError) onError(parsed.message || '未知错误');
          }
          return process();
        });
      }
      return process();
    })
    .catch(err => {
      if (err.name === 'AbortError') return;
      if (onError) onError(err.message || '网络错误');
    });
}
// AI 问答 · SSE 流式
import { state } from './state.js';
import { escapeHtml } from './utils.js';

// 像素机器人 SVG 头像
const ROBOT_AVATAR_SVG = `<svg viewBox="0 0 32 32" fill="none" xmlns="http://www.w3.org/2000/svg">
  <rect width="32" height="32" rx="8" fill="#111827"/>
  <rect x="7" y="5" width="18" height="11" rx="2" fill="#e5e7eb"/>
  <rect x="10" y="8" width="4" height="5" rx="1" fill="#111827"/>
  <rect x="18" y="8" width="4" height="5" rx="1" fill="#111827"/>
  <rect x="13" y="17" width="6" height="3" rx="1" fill="#9ca3af"/>
  <rect x="9" y="21" width="14" height="3" rx="1" fill="#6b7280"/>
  <rect x="6" y="25" width="7" height="3" rx="1" fill="#4b5563"/>
  <rect x="19" y="25" width="7" height="3" rx="1" fill="#4b5563"/>
</svg>`;

const QA_SUGGESTIONS = [
  { icon: '🌿', text: '骨灰安置有哪些生态安葬方式？' },
  { icon: '💰', text: '殡葬服务收费标准是什么？' },
  { icon: '📰', text: '杭州市殡葬改革最新政策？' },
];

export function setQuestion(text) {
  const textarea = document.getElementById('chat-textarea');
  if (textarea) {
    textarea.value = text;
    textarea.focus();
  }
  sendMessage();
}

export function toggleSourcesPanel(show) {
  const drawer = document.getElementById('qa-drawer');
  const overlay = document.getElementById('qa-drawer-overlay');
  if (!drawer || !overlay) return;
  const isOpen = drawer.classList.contains('open');
  const shouldOpen = show === undefined ? !isOpen : !!show;
  drawer.classList.toggle('open', shouldOpen);
  overlay.classList.toggle('open', shouldOpen);
}

function buildSuggestionsHtml() {
  return QA_SUGGESTIONS.map(s =>
    `<div class="qa-suggestion-chip" onclick="setQuestion('${escapeHtml(s.text)}')">
       <span class="chip-icon">${s.icon}</span><span>${escapeHtml(s.text)}</span>
     </div>`
  ).join('');
}

export function appendMessage(role, content, streaming = false) {
  const chatMessages = document.getElementById('chat-messages');
  if (chatMessages.classList.contains('empty')) {
    chatMessages.classList.remove('empty');
    chatMessages.innerHTML = '';
  }
  const div = document.createElement('div');
  div.className = 'msg msg-' + role + (streaming ? ' msg-streaming' : '');
  if (role === 'ai') {
    div.innerHTML = `
      <div class="msg-avatar">${ROBOT_AVATAR_SVG}</div>
      <div class="msg-body">
        <div class="msg-content">${content}</div>
      </div>
    `;
  } else {
    div.innerHTML = `
      <div class="msg-body">
        <div class="msg-content">${content}</div>
      </div>
    `;
  }
  chatMessages.appendChild(div);
  chatMessages.scrollTop = chatMessages.scrollHeight;
  return div;
}

export function addSource(citation) {
  const sourcesPanel = document.getElementById('sources-panel');
  if (!sourcesPanel) return;
  const empty = sourcesPanel.querySelector('.source-empty');
  if (empty) empty.remove();
  const div = document.createElement('div');
  div.className = 'source-card';
  div.dataset.marker = citation.marker || '';
  div.innerHTML = `
    <div class="source-card-header">
      <span class="source-card-marker">${escapeHtml(citation.marker || '')}</span>
      <span class="source-card-title">${escapeHtml(citation.title || '未知文档')}</span>
    </div>
    ${citation.snippet ? `<div class="source-card-snippet">${escapeHtml(citation.snippet)}</div>` : ''}
    <div class="source-card-meta">
      <span>相关度 ${(citation.score * 100).toFixed(0)}%</span>
    </div>
  `;
  sourcesPanel.appendChild(div);
}

export function highlightSourceCard(marker) {
  document.querySelectorAll('.source-card').forEach(card => {
    card.classList.remove('source-card-active');
  });
  state.activeSourceCard = null;
  if (!marker) return;
  const target = Array.from(document.querySelectorAll('.source-card')).find(card =>
    card.dataset.marker === marker
  );
  if (target) {
    target.classList.add('source-card-active');
    target.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    state.activeSourceCard = target;
  }
}

export function clearChat() {
  if (state.abortController) {
    state.abortController.abort();
    state.abortController = null;
  }
  state.chatHistory = [];
  const chatArea = document.getElementById('chat-messages');
  chatArea.innerHTML = `
    <div class="chat-empty">
      <div class="qa-hero-title">今天有什么想了解的？</div>
      <div class="qa-suggestions qa-suggestions-chips">
        ${buildSuggestionsHtml()}
      </div>
    </div>
  `;
  chatArea.classList.add('empty');
  const sourcesPanel = document.getElementById('sources-panel');
  if (sourcesPanel) {
    sourcesPanel.innerHTML = `
      <div class="source-empty">
        <div class="source-empty-icon">🔍</div>
        <div class="source-empty-title">等待 AI 回答</div>
        <div class="source-empty-desc">提问后，这里会显示答案引用的文档来源</div>
      </div>
    `;
  }
  toggleSourcesPanel(false);
}

export function sendMessage() {
  const chatInput = document.getElementById('chat-textarea');
  const chatSend = document.getElementById('chat-send');
  const sourcesPanel = document.getElementById('sources-panel');
  const text = chatInput.value.trim();
  if (!text) return;

  if (state.abortController) {
    state.abortController.abort();
    state.abortController = null;
  }

  appendMessage('user', text);
  chatInput.value = '';

  if (sourcesPanel) sourcesPanel.innerHTML = '<div class="sources-loading">正在检索引用来源...</div>';

  const aiMsg = appendMessage('ai', '', true);
  const aiContentEl = aiMsg.querySelector('.msg-content');

  const personaChip = document.querySelector('.persona-input-bar .persona-chip.active');
  const persona = personaChip ? (personaChip.dataset.persona || 'auto') : 'auto';

  if (chatSend) chatSend.disabled = true;

  state.abortController = new AbortController();

  let fullAnswer = '';
  let completed = false;
  let tokenStarted = false;

  function setAIThinking(stage, count) {
    if (!aiContentEl || tokenStarted) return;
    const steps = [
      { key: '检索', label: '检索知识库' },
      { key: '重排', label: '精选参考资料' },
      { key: '生成', label: '生成回答' },
    ];
    let activeIndex = steps.findIndex(s => s.key === stage);
    if (activeIndex === -1) activeIndex = 0;
    const current = steps[activeIndex];

    aiContentEl.innerHTML = `
      <div class="ai-thinking">
        <span class="ai-step-badge">${activeIndex + 1}/${steps.length}</span>
        <span class="thinking-dot"></span>
        <span class="thinking-text">正在${current.label}${count ? ` (${count})` : ''}</span>
      </div>
    `;

    if (sourcesPanel) {
      sourcesPanel.innerHTML = `<div class="sources-loading">正在${current.label} (${count})</div>`;
    }
  }

  if (aiContentEl) {
    setAIThinking('检索', 0);
  }

  fetch('/api/qa/stream', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ question: text, history: state.chatHistory, persona: persona }),
    signal: state.abortController.signal,
  }).then(resp => {
    const reader = resp.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';

    function process() {
      reader.read().then(({ done, value }) => {
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

          try {
            const parsed = JSON.parse(data);
            if (parsed.type === 'stage') {
              setAIThinking(parsed.stage, parsed.count);
              if (sourcesPanel) {
                sourcesPanel.innerHTML = `<div class="sources-loading">${parsed.stage}中... (${parsed.count})</div>`;
              }
            } else if (parsed.type === 'token') {
              if (!tokenStarted && aiContentEl) {
                tokenStarted = true;
                aiContentEl.textContent = '';
              }
              const contentEl = aiMsg.querySelector('.msg-content');
              contentEl.textContent += parsed.text;
              fullAnswer += parsed.text;
              const chatMessages = document.getElementById('chat-messages');
              if (chatMessages) chatMessages.scrollTop = chatMessages.scrollHeight;
            } else if (parsed.type === 'done') {
              aiMsg.classList.remove('msg-streaming');
              completed = true;
              if (parsed.answer) fullAnswer = parsed.answer;
              const contentEl = aiMsg.querySelector('.msg-content');
              let html = marked.parse(fullAnswer);
              html = html.replace(/\[(\d+)\]\(?(?!\w)/g, (_, n) =>
                `<span class="citation" data-marker="[${n}]" style="cursor:pointer">[${n}]</span>`
              );
              contentEl.innerHTML = html;
              if (sourcesPanel && parsed.citations) {
                sourcesPanel.innerHTML = '';
                const sources = parsed.sources || [];
                for (const c of parsed.citations) {
                  const matched = sources.find(s => s.doc_id === c.doc_id);
                  addSource({
                    marker: c.marker,
                    title: c.title,
                    snippet: '',
                    score: matched ? matched.score : 0,
                  });
                }
              }
            } else if (parsed.type === 'error') {
              const contentEl = aiMsg.querySelector('.msg-content');
              contentEl.textContent = '错误: ' + parsed.message;
              aiMsg.classList.remove('msg-streaming');
            }
          } catch (e) {}
        }
        process();
      });
    }
    process();
  }).catch(err => {
    if (err.name === 'AbortError') {
      aiMsg.classList.remove('msg-streaming');
      const messages = document.getElementById('chat-messages');
      if (messages) {
        const cancelDiv = document.createElement('div');
        cancelDiv.className = 'msg msg-ai';
        cancelDiv.innerHTML = `<div class="msg-avatar">${ROBOT_AVATAR_SVG}</div><div class="msg-body"><div class="msg-content" style="color:var(--text-muted)">(已取消)</div></div>`;
        messages.appendChild(cancelDiv);
        messages.scrollTop = messages.scrollHeight;
      }
    } else {
      console.error('QA error:', err);
      const contentEl = aiMsg.querySelector('.msg-content');
      if (contentEl) {
        contentEl.textContent = '请求失败: ' + err.message;
      }
      aiMsg.classList.remove('msg-streaming');
    }
  }).finally(() => {
    state.abortController = null;
    if (chatSend) chatSend.disabled = false;
    if (completed && fullAnswer) {
      state.chatHistory.push({ role: 'user', content: text });
      state.chatHistory.push({ role: 'assistant', content: fullAnswer });
      if (state.chatHistory.length > 20) {
        state.chatHistory = state.chatHistory.slice(-20);
      }
    }
  });
}

export function initQA() {
  const chatSend = document.getElementById('chat-send');
  const chatInput = document.getElementById('chat-textarea');
  const sourcesToggle = document.getElementById('btn-sources-toggle');
  const drawerClose = document.getElementById('qa-drawer-close');
  const drawerOverlay = document.getElementById('qa-drawer-overlay');

  if (sourcesToggle) {
    sourcesToggle.addEventListener('click', () => toggleSourcesPanel());
  }
  if (drawerClose) {
    drawerClose.addEventListener('click', () => toggleSourcesPanel(false));
  }
  if (drawerOverlay) {
    drawerOverlay.addEventListener('click', () => toggleSourcesPanel(false));
  }

  if (chatSend) {
    chatSend.addEventListener('click', sendMessage);
  }
  function updateChatPadding() {
    const wrapper = document.querySelector('.chat-input-wrapper');
    const chatArea = document.getElementById('chat-messages');
    if (wrapper && chatArea) {
      const height = wrapper.offsetHeight;
      // 保证底部留白至少能覆盖固定输入框 + 额外间距，且不小于 CSS 默认 220px
      chatArea.style.paddingBottom = `${Math.max(220, height + 48)}px`;
    }
  }

  if (chatInput) {
    chatInput.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) {
        e.preventDefault();
        sendMessage();
      }
    });
    chatInput.addEventListener('input', () => {
      chatInput.style.height = 'auto';
      chatInput.style.height = Math.min(chatInput.scrollHeight, 200) + 'px';
      updateChatPadding();
    });
  }
  window.addEventListener('resize', updateChatPadding);
  updateChatPadding();

  document.getElementById('btn-clear-chat')?.addEventListener('click', clearChat);

  document.getElementById('chat-messages')?.addEventListener('click', (e) => {
    const cite = e.target.closest('.citation');
    if (cite) {
      const marker = cite.dataset.marker || cite.textContent.trim();
      toggleSourcesPanel(true);
      highlightSourceCard(marker);
    }
  });

  document.getElementById('sources-panel')?.addEventListener('click', (e) => {
    const card = e.target.closest('.source-card');
    if (card) {
      const marker = card.dataset.marker;
      highlightSourceCard(marker);
    }
  });

  window.setQuestion = setQuestion;
}

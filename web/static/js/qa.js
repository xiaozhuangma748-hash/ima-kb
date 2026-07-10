// AI 问答 · SSE 流式
import { state } from './state.js';
import { escapeHtml } from './utils.js';

export function setSidebarCollapsed(collapsed) {
  const qaLayout = document.getElementById('qa-layout');
  const qaSidebar = document.getElementById('qa-sidebar');
  const sidebarToggle = document.getElementById('sidebar-toggle');
  if (!qaLayout || !qaSidebar || !sidebarToggle) return;
  qaSidebar.classList.toggle('collapsed', collapsed);
  qaLayout.classList.toggle('collapsed-sidebar', collapsed);
  sidebarToggle.textContent = collapsed ? '▶' : '◀';
  sidebarToggle.title = collapsed ? '展开引用来源' : '折叠引用来源';
}

export function setQuestion(text) {
  const textarea = document.getElementById('chat-textarea');
  if (textarea) {
    textarea.value = text;
    textarea.focus();
  }
  sendMessage();
}

export function appendMessage(role, content, streaming = false) {
  const chatMessages = document.getElementById('chat-messages');
  // 首次发消息时清空空状态
  if (chatMessages.classList.contains('empty')) {
    chatMessages.classList.remove('empty');
    chatMessages.innerHTML = '';
  }
  const div = document.createElement('div');
  div.className = 'msg msg-' + role + (streaming ? ' msg-streaming' : '');
  div.innerHTML = `<div class="msg-content">${content}</div>`;
  chatMessages.appendChild(div);
  chatMessages.scrollTop = chatMessages.scrollHeight;
  return div;
}

export function addSource(citation) {
  const sourcesPanel = document.getElementById('sources-panel');
  // 首次添加引用时清空提示
  if (sourcesPanel.querySelector('div:only-child')?.textContent.includes('等待 AI 回答')) {
    sourcesPanel.innerHTML = '';
  }
  const div = document.createElement('div');
  div.className = 'source-card';
  div.dataset.marker = citation.marker || '';
  div.innerHTML = `
    <div class="source-card-title">${escapeHtml(citation.marker || '')} ${escapeHtml(citation.title || '未知文档')}</div>
    <div class="source-card-snippet">${escapeHtml(citation.snippet || '')}</div>
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
  // 取消正在进行的 SSE 流
  if (state.abortController) {
    state.abortController.abort();
    state.abortController = null;
  }
  // 重置多轮对话历史
  state.chatHistory = [];
  const chatArea = document.getElementById('chat-messages');
  chatArea.innerHTML = `
    <div class="chat-empty">
      <div class="qa-hero-title">今天有什么想了解的？</div>
      <div class="qa-suggestions">
        <div class="qa-suggestion" onclick="setQuestion('骨灰安置有哪些生态安葬方式？')">骨灰安置有哪些生态安葬方式？</div>
        <div class="qa-suggestion" onclick="setQuestion('殡葬服务收费标准是什么？')">殡葬服务收费标准是什么？</div>
        <div class="qa-suggestion" onclick="setQuestion('杭州市殡葬改革最新政策？')">杭州市殡葬改革最新政策？</div>
      </div>
    </div>
  `;
  chatArea.classList.add('empty');
  const sourcesPanel = document.getElementById('sources-panel');
  if (sourcesPanel) sourcesPanel.innerHTML = '<div style="font-size:12px;color:var(--text-muted);text-align:center;padding:20px">等待 AI 回答...</div>';
}

export function sendMessage() {
  const chatInput = document.getElementById('chat-textarea');
  const chatSend = document.getElementById('chat-send');
  const sourcesPanel = document.getElementById('sources-panel');
  const text = chatInput.value.trim();
  if (!text) return;

  // 如果上一轮还在进行，先取消
  if (state.abortController) {
    state.abortController.abort();
    state.abortController = null;
  }

  // 添加用户消息
  appendMessage('user', text);
  chatInput.value = '';

  // 重置引用面板
  if (sourcesPanel) sourcesPanel.innerHTML = '<div style="font-size:12px;color:var(--text-muted);text-align:center;padding:20px">正在检索...</div>';

  // 添加 AI 占位
  const aiMsg = appendMessage('ai', '', true);

  // 获取人格
  const personaChip = document.querySelector('.persona-input-bar .persona-chip.active');
  const persona = personaChip ? (personaChip.dataset.persona || 'auto') : 'auto';

  // 禁用发送按钮，防止重复提交
  if (chatSend) chatSend.disabled = true;

  // 创建 AbortController 用于取消 SSE 流
  state.abortController = new AbortController();

  // SSE 流式请求（POST，带多轮对话历史）
  let fullAnswer = '';
  let completed = false;

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

        // 解析 SSE 事件（data-only 格式，type 字段在 JSON 内）
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
              // 阶段进度提示
              if (sourcesPanel) {
                sourcesPanel.innerHTML = `<div style="font-size:12px;color:var(--text-muted);text-align:center;padding:20px">${parsed.stage}中... (${parsed.count})</div>`;
              }
            } else if (parsed.type === 'token') {
              const contentEl = aiMsg.querySelector('.msg-content');
              contentEl.textContent += parsed.text;
              fullAnswer += parsed.text;
            } else if (parsed.type === 'done') {
              aiMsg.classList.remove('msg-streaming');
              completed = true;
              // 优先用 done 事件里的完整答案
              if (parsed.answer) fullAnswer = parsed.answer;
              // Markdown 渲染 + 引用编号可点击
              const contentEl = aiMsg.querySelector('.msg-content');
              let html = marked.parse(fullAnswer);
              html = html.replace(/\[(\d+)\]\(?(?!\w)/g, (_, n) =>
                `<span class="citation" data-marker="[${n}]" style="cursor:pointer">[${n}]</span>`
              );
              contentEl.innerHTML = html;
              // 渲染引用来源
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
      // 用户取消，保留已输出内容
      aiMsg.classList.remove('msg-streaming');
      const messages = document.getElementById('chat-messages');
      if (messages) {
        const cancelDiv = document.createElement('div');
        cancelDiv.className = 'msg msg-ai';
        cancelDiv.innerHTML = '<div class="msg-content" style="color:var(--text-muted)">(已取消)</div>';
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
    // 恢复发送按钮状态
    if (chatSend) chatSend.disabled = false;
    // 多轮对话历史：仅在正常完成时记录，保留最近 10 轮
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
  const sidebarToggle = document.getElementById('sidebar-toggle');
  const qaLayout = document.getElementById('qa-layout');
  const qaSidebar = document.getElementById('qa-sidebar');

  // 侧边栏折叠
  if (sidebarToggle && qaLayout && qaSidebar) {
    sidebarToggle.addEventListener('click', () => {
      setSidebarCollapsed(!qaSidebar.classList.contains('collapsed'));
    });
  }

  // 发送按钮
  if (chatSend) {
    chatSend.addEventListener('click', sendMessage);
  }
  if (chatInput) {
    chatInput.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) {
        e.preventDefault();
        sendMessage();
      }
    });
  }

  // 清空对话
  document.getElementById('btn-clear-chat')?.addEventListener('click', clearChat);

  // 回答中的引用编号点击高亮对应卡片
  document.getElementById('chat-messages')?.addEventListener('click', (e) => {
    const cite = e.target.closest('.citation');
    if (cite) {
      const marker = cite.dataset.marker || cite.textContent.trim();
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

  // 暴露给 HTML onclick 使用（动态生成的建议项也需要）
  window.setQuestion = setQuestion;
}

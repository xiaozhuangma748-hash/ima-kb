// renderer.js — Electron 渲染进程：猫咪交互 + 气泡问答 + 拖拽入库 + 窗口拖动
'use strict';

const img = document.getElementById('pet-img');
const petStage = document.getElementById('pet-stage');
const dropHint = document.getElementById('drop-hint');
const bubble = document.getElementById('bubble');
const bubbleInput = document.getElementById('bubble-input');
const bubbleFollowup = document.getElementById('bubble-followup');
const bubbleAnswer = document.getElementById('bubble-answer');
const bubbleCitations = document.getElementById('bubble-citations');
const btnCitations = document.getElementById('btn-citations');
const btnClose = document.getElementById('btn-close');
const pathHint = document.getElementById('path-hint');
const pathHintText = document.getElementById('path-hint-text');
const btnIngestPath = document.getElementById('btn-ingest-path');

let currentPath = null;

let isAnswerMode = false;
let currentCitations = [];
let history = []; // {role, content}

function escapeHtml(s) {
  if (s == null) return '';
  return String(s)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;');
}

// === Python 事件监听 ===
window.petAPI.onStateChanged(({ state, gif }) => {
  img.src = gif + '?t=' + Date.now();
});

window.petAPI.onPetInfo((info) => {
  console.log('[pet] info:', info);
});

window.petAPI.onAnswerToken((chunk) => {
  if (!isAnswerMode) {
    bubbleAnswer.innerHTML = '';
    isAnswerMode = true;
  }
  bubbleAnswer.innerHTML += escapeHtml(chunk);
  scrollToBottom();
});

window.petAPI.onAnswerDone((citations) => {
  currentCitations = citations || [];
  if (currentCitations.length > 0) {
    renderCitations(currentCitations);
    btnCitations.style.display = 'inline-block';
    btnCitations.textContent = '引用';
  }
  showFollowup();
  scrollToBottom();
});

window.petAPI.onAnswerError((err) => {
  bubbleAnswer.innerHTML = `<span style="color:var(--pet-error)">${escapeHtml(err)}</span>`;
  showFollowup();
  scrollToBottom();
});

window.petAPI.onShowBubble((msg) => {
  // 入库结果用 drop-hint 轻提示，不占用问答气泡
  if (typeof msg === 'string' && /^(已入库|已存在|失败：)/.test(msg)) {
    setDropHint(msg, true);
    setTimeout(clearDropState, 2000);
    return;
  }
  showBubble();
  bubbleAnswer.innerHTML = escapeHtml(msg);
  showFollowup();
});

// === 气泡控制 ===
function showBubble() {
  bubble.classList.add('visible');
  bubbleInput.style.display = 'block';
  bubbleInput.value = '';
  bubbleInput.focus();
  bubbleAnswer.innerHTML = '';
  bubbleCitations.innerHTML = '';
  bubbleCitations.classList.remove('expanded');
  btnCitations.style.display = 'none';
  bubbleFollowup.style.display = 'none';
  pathHint.classList.remove('visible');
  currentPath = null;
  isAnswerMode = false;
  currentCitations = [];
  window.petAPI.bubbleVisible(true);
}

function hideBubble() {
  bubble.classList.remove('visible');
  window.petAPI.bubbleVisible(false);
}

function scrollToBottom() {
  bubble.scrollTop = bubble.scrollHeight;
}

function showFollowup() {
  bubbleFollowup.style.display = 'block';
  bubbleFollowup.value = '';
  setTimeout(() => bubbleFollowup.focus(), 50);
}

function renderCitations(citations) {
  let html = '<b>引用溯源</b><ul>';
  for (const c of citations) {
    const docId = escapeHtml(c.doc_id || '');
    html += `<li><a href="#" data-doc-id="${docId}" ` +
      `onclick="window.petAPI.showDoc('${docId}'); return false;">` +
      `[${escapeHtml(c.marker || '')}] ${escapeHtml(c.title || '')} §${escapeHtml(String(c.paragraph_num || ''))}</a></li>`;
  }
  html += '</ul>';
  bubbleCitations.innerHTML = html;
}

function submitQuestion(question) {
  if (!question.trim()) return;
  history.push({ role: 'user', content: question });
  trimHistory();

  // UI 切换到答案模式
  bubbleInput.style.display = 'none';
  bubbleAnswer.innerHTML = '<i>思考中…</i>';
  bubbleCitations.innerHTML = '';
  bubbleCitations.classList.remove('expanded');
  btnCitations.style.display = 'none';
  bubbleFollowup.style.display = 'none';
  isAnswerMode = false;
  currentCitations = [];

  window.petAPI.askStream(question, history);
}

function trimHistory() {
  // 保留最近 3 轮（6 条）
  if (history.length > 6) {
    history = history.slice(history.length - 6);
  }
}

// === 输入框识别文件路径并提供入库 ===
function extractFilePath(text) {
  if (!text) return null;
  text = text.trim();
  // file:// 协议
  if (text.startsWith('file://')) {
    return decodeURIComponent(text.slice(7));
  }
  // Unix/macOS 绝对路径
  const absMatch = text.match(/^(\/[^\n\r]+?)(?:\s|$)/);
  if (absMatch) return absMatch[1];
  // 包含常见扩展名的绝对路径
  const extMatch = text.match(/(\/[^\n\r]*\.(pdf|md|txt|docx|doc|xlsx|xls|pptx|ppt|json|csv|html|epub|png|jpg|jpeg|gif|webp|mp4|mov|mp3|wav))(?:\s|$)/i);
  if (extMatch) return extMatch[1];
  return null;
}

function checkPathInput(inputEl) {
  const path = extractFilePath(inputEl.value);
  if (path) {
    currentPath = path;
    const fileName = path.split('/').pop() || path;
    pathHintText.textContent = `检测到文件：${fileName}`;
    pathHint.classList.add('visible');
  } else {
    currentPath = null;
    pathHint.classList.remove('visible');
  }
}

function ingestCurrentPath() {
  if (!currentPath) return;
  const path = currentPath;
  const fileName = path.split('/').pop() || path;
  bubbleInput.value = '';
  bubbleFollowup.value = '';
  pathHint.classList.remove('visible');
  hideBubble(); // 关闭问答气泡，用 drop-hint 反馈进度
  setDropHint(`正在吃掉 ${fileName}…`, true);
  currentPath = null;
  window.petAPI.ingest(path);
}

// === 事件绑定 ===
img.addEventListener('dblclick', (e) => {
  e.preventDefault();
  e.stopPropagation();
  showBubble();
});

btnClose.addEventListener('click', (e) => {
  e.stopPropagation();
  hideBubble();
});

btnCitations.addEventListener('click', (e) => {
  e.stopPropagation();
  const expanded = bubbleCitations.classList.toggle('expanded');
  btnCitations.textContent = expanded ? '收起' : '引用';
});

bubbleInput.addEventListener('keydown', (e) => {
  if (e.key === 'Enter') {
    e.preventDefault();
    submitQuestion(bubbleInput.value);
  } else if (e.key === 'Escape') {
    hideBubble();
  }
});

bubbleFollowup.addEventListener('keydown', (e) => {
  if (e.key === 'Enter') {
    e.preventDefault();
    const q = bubbleFollowup.value;
    if (!q.trim()) return;
    // 把上一轮答案加入历史，再追问
    history.push({ role: 'assistant', content: bubbleAnswer.innerText });
    trimHistory();
    submitQuestion(q);
  } else if (e.key === 'Escape') {
    hideBubble();
  }
});

// 输入框粘贴/输入文件路径时自动识别并提示入库
bubbleInput.addEventListener('input', () => checkPathInput(bubbleInput));
bubbleFollowup.addEventListener('input', () => checkPathInput(bubbleFollowup));

btnIngestPath.addEventListener('click', (e) => {
  e.preventDefault();
  e.stopPropagation();
  ingestCurrentPath();
});

document.addEventListener('keydown', (e) => {
  if (e.key === 'Escape' && bubble.classList.contains('visible')) {
    hideBubble();
  }
});

// === 拖拽移动窗口（按偏移量，避免单击跳变）===
let dragging = false;
let dragStartX = 0;
let dragStartY = 0;
let dragLastX = 0;
let dragLastY = 0;
const DRAG_THRESHOLD = 3; // 像素，超过才算拖拽

// 整个窗口透明区域都可拖拽（气泡内除外）
document.body.addEventListener('mousedown', (e) => {
  if (e.target.closest('#bubble')) return;
  // 避免在输入框、按钮等可交互元素上触发拖拽
  if (e.target.tagName === 'INPUT' || e.target.tagName === 'BUTTON' || e.target.tagName === 'A') return;
  dragging = true;
  dragStartX = e.screenX;
  dragStartY = e.screenY;
  dragLastX = e.screenX;
  dragLastY = e.screenY;
  window.petAPI.dragStart(e.screenX, e.screenY);
});

window.addEventListener('mousemove', (e) => {
  if (!dragging) return;
  const dx = e.screenX - dragLastX;
  const dy = e.screenY - dragLastY;
  // 只有真正移动了才通知主进程
  if (Math.abs(e.screenX - dragStartX) > DRAG_THRESHOLD ||
      Math.abs(e.screenY - dragStartY) > DRAG_THRESHOLD) {
    window.petAPI.dragDelta(dx, dy);
  }
  dragLastX = e.screenX;
  dragLastY = e.screenY;
});

window.addEventListener('mouseup', () => {
  if (!dragging) return;
  dragging = false;
  window.petAPI.dragEnd();
});

// === 拖拽入库（扩大到整个窗口，猫咪会“张嘴”等待）===
function setDropHint(text, show) {
  dropHint.textContent = text;
  dropHint.classList.toggle('visible', show);
}

function clearDropState() {
  img.classList.remove('drag-over', 'eating');
  setDropHint('', false);
}

document.body.addEventListener('dragover', (e) => {
  // 必须 preventDefault，否则 drop 不会触发
  e.preventDefault();
  console.log('[dnd] dragover target:', e.target.id || e.target.tagName);
  if (e.target.closest('#bubble')) {
    clearDropState();
    return;
  }
  img.classList.add('drag-over', 'eating');
  setDropHint('啊~ 丢给我！', true);
});

document.body.addEventListener('dragleave', (e) => {
  // 只有真正离开 body 时才清除（避免进入子元素时误触发）
  if (e.relatedTarget && document.body.contains(e.relatedTarget)) return;
  clearDropState();
});

document.body.addEventListener('drop', async (e) => {
  e.preventDefault();
  e.stopPropagation();
  clearDropState();
  console.log('[dnd] drop target:', e.target.id || e.target.tagName);

  if (e.target.closest('#bubble')) return;

  let filePath = null;
  let fileName = '';

  // 策略 1: text/uri-list（macOS Finder 最可靠）
  const uriList = e.dataTransfer.getData('text/uri-list');
  if (uriList) {
    const lines = uriList.split('\n').map((s) => s.trim()).filter((s) => s && !s.startsWith('#'));
    if (lines.length > 0 && lines[0].startsWith('file://')) {
      filePath = decodeURIComponent(lines[0].slice(7));
      fileName = filePath.split('/').pop() || '';
    }
  }

  // 策略 2: dataTransfer.files
  if (!filePath && e.dataTransfer.files && e.dataTransfer.files.length > 0) {
    const f = e.dataTransfer.files[0];
    filePath = f.path || f.name;
    fileName = f.name || filePath.split('/').pop() || '';
  }

  if (!filePath) {
    setDropHint('没拿到文件路径…', true);
    setTimeout(() => clearDropState(), 1500);
    return;
  }

  setDropHint(`正在吃掉 ${fileName || '文件'}…`, true);
  window.petAPI.ingest(filePath);
});

console.log('[ima-desktop-electron] renderer loaded');

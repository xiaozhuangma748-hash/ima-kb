// renderer.js — Electron 渲染进程：猫咪交互 + 气泡问答 + 拖拽入库 + 窗口拖动
'use strict';

const img = document.getElementById('pet-img');
const petStage = document.getElementById('pet-stage');
const dropHint = document.getElementById('drop-hint');
const bubble = document.getElementById('bubble');
const bubbleInput = document.getElementById('bubble-input');
const bubbleScroll = document.getElementById('bubble-scroll');

const bubbleAnswer = document.getElementById('bubble-answer');
const bubbleCitations = document.getElementById('bubble-citations');
const btnCitations = document.getElementById('btn-citations');
const btnClose = document.getElementById('btn-close');
const pathHint = document.getElementById('path-hint');
const pathHintText = document.getElementById('path-hint-text');
const btnIngestPath = document.getElementById('btn-ingest-path');
const textHint = document.getElementById('text-hint');
const btnIngestText = document.getElementById('btn-ingest-text');

let currentPath = null;
let currentText = null;

let isAnswerMode = false;
let currentCitations = [];
let history = []; // {role, content}，按 OpenAI 多轮对话格式 [user, assistant, user, assistant, ...]
let answerBuffer = ''; // 累积流式 token，done 后做 markdown 渲染
let pendingQuestion = ''; // 当前正在等待回答的问题，onAnswerDone 后才追加到 history

function escapeHtml(s) {
  if (s == null) return '';
  return String(s)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;');
}

// === 轻量 Markdown 渲染：去掉 ## ** * > 等符号，保留排版 ===
function inlineFmt(text) {
  // 先把 **xxx** 替换为占位符，escape 后再还原为 <b>
  const bolds = [];
  text = text.replace(/\*\*([^*]+)\*\*/g, (_, g1) => {
    bolds.push(g1);
    return `\u0000${bolds.length - 1}\u0000`;
  });
  // `code` → 占位
  const codes = [];
  text = text.replace(/`([^`]+)`/g, (_, g1) => {
    codes.push(g1);
    return `\u0001${codes.length - 1}\u0001`;
  });
  text = escapeHtml(text);
  text = text.replace(/\u0000(\d+)\u0000/g, (_, i) => `<b>${escapeHtml(bolds[i])}</b>`);
  text = text.replace(/\u0001(\d+)\u0001/g, (_, i) => `<code>${escapeHtml(codes[i])}</code>`);
  return text;
}

function markdownToHtml(md) {
  if (!md) return '';
  const lines = String(md).split('\n');
  let html = '';
  let inList = false;
  const closeList = () => { if (inList) { html += '</div>'; inList = false; } };

  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];
    let m;

    // 标题 # ~ ######
    if ((m = line.match(/^#{1,6}\s+(.*)$/))) {
      closeList();
      html += `<div class="md-h">${inlineFmt(m[1])}</div>`;
      continue;
    }
    // 无序列表 * - +
    if ((m = line.match(/^\s*[\*\-\+]\s+(.*)$/))) {
      if (!inList) { html += '<div class="md-list">'; inList = true; }
      html += `<div class="md-li">• ${inlineFmt(m[1])}</div>`;
      continue;
    }
    // 有序列表 1. 2.
    if ((m = line.match(/^\s*\d+\.\s+(.*)$/))) {
      if (!inList) { html += '<div class="md-list">'; inList = true; }
      html += `<div class="md-li">${inlineFmt(m[1])}</div>`;
      continue;
    }
    // 引用 >
    if ((m = line.match(/^\s*>\s?(.*)$/))) {
      closeList();
      html += `<div class="md-quote">${inlineFmt(m[1])}</div>`;
      continue;
    }
    // 分割线 --- ***
    if (/^\s*([-*]){3,}\s*$/.test(line)) {
      closeList();
      html += '<hr class="md-hr">';
      continue;
    }
    // 空行
    if (line.trim() === '') {
      closeList();
      continue;
    }
    // 普通段落
    closeList();
    html += `<div class="md-p">${inlineFmt(line)}</div>`;
  }
  closeList();
  return html;
}

// === Python 事件监听 ===
window.petAPI.onStateChanged(({ state, gif }) => {
  img.src = gif + '?t=' + Date.now();
});

window.petAPI.onPetInfo((info) => {
  console.log('[pet] info:', info);
});

// 阶段状态指示器（检索/重排/缓存），首个 token 到来时自动清除
const STAGE_TEXT = {
  '检索': '混合检索知识库',
  '重排': 'LLM 重排结果',
  '缓存': '命中缓存，快速回答',
};

function renderStageHint(stage, count) {
  const text = STAGE_TEXT[stage] || stage;
  const countStr = count > 0 ? ` (${count} 条)` : '';
  const qHtml = pendingQuestion
    ? `<div class="md-h">问：${escapeHtml(pendingQuestion)}</div>`
    : '';
  bubbleAnswer.innerHTML = qHtml +
    `<div class="stage-hint"><span class="dots"></span>${escapeHtml(text)}${countStr}</div>`;
  // 滚动到提示位置
  if (bubbleScroll) bubbleScroll.scrollTop = bubbleScroll.scrollHeight;
}

window.petAPI.onAnswerStage((data) => {
  console.log('[renderer] onAnswerStage:', data.stage, data.count, 'isAnswerMode:', isAnswerMode);
  if (!isAnswerMode) {
    renderStageHint(data.stage, data.count);
  }
});

window.petAPI.onAnswerToken((chunk) => {
  console.log('[renderer] onAnswerToken chunk="' + chunk + '" len=' + (chunk ? chunk.length : 0) + ' isAnswerMode=' + isAnswerMode);
  if (!isAnswerMode) {
    answerBuffer = '';
    isAnswerMode = true;
  }
  answerBuffer += chunk;
  // 流式阶段：问题保留在顶部，纯文本答案追加在问题下方（避免半截 markdown 抖动）
  const qHtml = pendingQuestion
    ? `<div class="md-h">问：${escapeHtml(pendingQuestion)}</div>`
    : '';
  bubbleAnswer.innerHTML = qHtml + escapeHtml(answerBuffer);
  console.log('[renderer] bubbleAnswer.innerHTML len:', bubbleAnswer.innerHTML.length);
  updateScrollHeight();
});

window.petAPI.onAnswerDone((citations) => {
  console.log('[renderer] onAnswerDone citations:', citations ? citations.length : 0, 'answerBuffer len:', answerBuffer.length);
  // 完成后再做一次 markdown 渲染，去掉 ## ** * > 等符号
  // 问题保留在顶部，答案追加在问题下方
  const qHtml = pendingQuestion
    ? `<div class="md-h">问：${escapeHtml(pendingQuestion)}</div>`
    : '';
  bubbleAnswer.innerHTML = qHtml + markdownToHtml(answerBuffer);
  console.log('[renderer] onAnswerDone final innerHTML len:', bubbleAnswer.innerHTML.length);
  // 完成后才追加完整问答到 history，避免调用前 push 导致后端 messages 重复
  if (pendingQuestion) {
    history.push({ role: 'user', content: pendingQuestion });
    history.push({ role: 'assistant', content: answerBuffer });
    trimHistory();
    pendingQuestion = '';
  }
  currentCitations = citations || [];
  if (currentCitations.length > 0) {
    renderCitations(currentCitations);
    btnCitations.style.display = 'inline-block';
    btnCitations.textContent = '引用';
  }
  // 答案完成后滚到顶部，让用户从开头阅读（长答案不会被裁掉）
  if (bubbleScroll) bubbleScroll.scrollTop = 0;
});

window.petAPI.onAnswerError((err) => {
  console.error('[renderer] onAnswerError:', err);
  // 错误时不追加 history（与 CLI 一致），清空 pendingQuestion 避免下次混淆
  pendingQuestion = '';
  bubbleAnswer.innerHTML = `<span style="color:var(--pet-error)">${escapeHtml(err)}</span>`;
  if (bubbleScroll) bubbleScroll.scrollTop = 0;
});

window.petAPI.onShowBubble((msg) => {
  // 入库结果用 drop-hint 轻提示，不占用问答气泡
  if (typeof msg === 'string' && /^(已入库|已存在|失败：)/.test(msg)) {
    setDropHint(msg, true);
    setTimeout(clearDropState, 2000);
    return;
  }
  showBubble();
  bubbleAnswer.innerHTML = markdownToHtml(String(msg));
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
  pathHint.classList.remove('visible');
  textHint.classList.remove('visible');
  currentPath = null;
  currentText = null;
  isAnswerMode = false;
  currentCitations = [];
  answerBuffer = '';
  if (bubbleScroll) bubbleScroll.scrollTop = 0;
  window.petAPI.bubbleVisible(true);
}

function hideBubble() {
  bubble.classList.remove('visible');
  window.petAPI.bubbleVisible(false);
}

function scrollToBottom() {
  if (bubbleScroll) {
    bubbleScroll.scrollTop = bubbleScroll.scrollHeight;
  }
}

function updateScrollHeight() {
  if (bubbleScroll) {
    const h = bubbleScroll.scrollHeight;
    if (bubbleScroll.scrollTop + bubbleScroll.clientHeight < h) {
      bubbleScroll.scrollTop = h;
    }
  }
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
  // 注意：不要在调用前 push user 到 history！
  // 后端 ask_stream 会再 append query 到 messages 末尾，调用前 push 会导致
  // 当前问题在 messages 中出现两次，LLM 看到重复输入可能输出重复内容。
  // 改为暂存 pendingQuestion，在 onAnswerDone 完成后追加 user + assistant。
  pendingQuestion = question;
  trimHistory();

  // UI 切换到答案模式
  bubbleAnswer.innerHTML = '<i>思考中…</i>';
  bubbleCitations.innerHTML = '';
  bubbleCitations.classList.remove('expanded');
  btnCitations.style.display = 'none';
  isAnswerMode = false;
  currentCitations = [];
  answerBuffer = ''; // 显式清空，防止上轮答案残留（onAnswerToken 的清空依赖首个 token 到达）
  // 把当前问题追加到答案区顶部，形成问答时间线（在"思考中…"上方）
  appendQuestionToHistory(question);

  // 输入框保持原位不动（程序化赋值不触发 input 事件，需手动清理路径/文字检测状态）
  bubbleInput.value = '';
  currentPath = null;
  currentText = null;
  pathHint.classList.remove('visible');
  textHint.classList.remove('visible');
  bubbleInput.focus();
  window.petAPI.askStream(question, history);
}

function appendQuestionToHistory(question) {
  // 在答案区顶部追加历史问题记录，形成问答时间线
  const prev = bubbleAnswer.innerHTML.trim();
  const qHtml = `<div class="md-h">问：${escapeHtml(question)}</div>`;
  // 避免重复追加相同问题（如双击触发）
  if (prev.startsWith(qHtml)) return;
  bubbleAnswer.innerHTML = qHtml + prev;
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

function checkPathInput() {
  const value = bubbleInput.value.trim();
  const path = extractFilePath(value);
  if (path) {
    currentPath = path;
    currentText = null;
    const fileName = path.split('/').pop() || path;
    pathHintText.textContent = `检测到文件：${fileName}`;
    pathHint.classList.add('visible');
    textHint.classList.remove('visible');
    return;
  }

  currentPath = null;
  pathHint.classList.remove('visible');

  // 非路径且有一定长度的文字，提供直接入库
  if (value.length >= 10) {
    currentText = value;
    textHint.classList.add('visible');
  } else {
    currentText = null;
    textHint.classList.remove('visible');
  }
}

function ingestCurrentPath() {
  if (!currentPath) return;
  const path = currentPath;
  const fileName = path.split('/').pop() || path;
  bubbleInput.value = '';
  pathHint.classList.remove('visible');
  textHint.classList.remove('visible');
  hideBubble(); // 关闭问答气泡，用 drop-hint 反馈进度
  setDropHint(`正在吃掉 ${fileName}…`, true);
  currentPath = null;
  window.petAPI.ingest(path);
}

function ingestCurrentText() {
  if (!currentText) return;
  const text = currentText;
  bubbleInput.value = '';
  pathHint.classList.remove('visible');
  textHint.classList.remove('visible');
  hideBubble(); // 关闭问答气泡，用 drop-hint 反馈进度
  setDropHint('正在整理文字…', true);
  currentText = null;
  window.petAPI.ingestText(text);
}

// === 事件绑定 ===
img.addEventListener('dblclick', (e) => {
  e.preventDefault();
  e.stopPropagation();
  showBubble();
});

// 输入框内 Shift+Enter 换行；Enter 提交
bubbleInput.addEventListener('keydown', (e) => {
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault();
    submitQuestion(bubbleInput.value);
  } else if (e.key === 'Escape') {
    hideBubble();
  }
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

// 输入框粘贴/输入文件路径时自动识别并提示入库
bubbleInput.addEventListener('input', checkPathInput);

btnIngestPath.addEventListener('click', (e) => {
  e.preventDefault();
  e.stopPropagation();
  ingestCurrentPath();
});

btnIngestText.addEventListener('click', (e) => {
  e.preventDefault();
  e.stopPropagation();
  ingestCurrentText();
});

// 监听粘贴事件：支持剪贴板图片直接入库
bubbleInput.addEventListener('paste', (e) => {
  const items = e.clipboardData && e.clipboardData.items;
  if (!items) return;
  for (const item of items) {
    if (item.type.indexOf('image') === -1) continue;
    const blob = item.getAsFile();
    if (!blob) continue;
    e.preventDefault();
    const reader = new FileReader();
    reader.onload = (event) => {
      const ext = blob.name ? blob.name.split('.').pop() : 'png';
      const fileName = `pasted_image_${Date.now()}.${ext}`;
      hideBubble();
      setDropHint('正在吃掉图片…', true);
      window.petAPI.ingestImage(event.target.result, fileName);
    };
    reader.readAsDataURL(blob);
    break;
  }
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

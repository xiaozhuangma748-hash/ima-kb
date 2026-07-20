// 桌面宠物渲染脚本 — 猫咪 GIF 动画 + 暖色调气泡
// Task 4：实现 CatPet 类与全局函数（供 Python evaluate_js 调用）
//
// 设计要点：
// 1. 用 <img> 元素显示猫咪 GIF，状态切换时改 img.src 触发 GIF 重新播放
// 2. 12 个状态 → cat_<state>.gif 文件名映射硬编码在 JS 中（Python 端无需提供）
// 3. 保留 BubbleManager / SoundManager / 拖拽入库 / 双击问答逻辑
// 4. 全局函数 updateState / setCatGif / updateStateDirect 由 Python 端 evaluate_js 调用
'use strict';

// === CatPet 类（替代 PetRenderer） ===
class CatPet {
  constructor(imgId) {
    this.img = document.getElementById(imgId);
    this.state = 'idle';
  }

  setState(state) {
    this.state = state;
    this.setCatGif(state);
  }

  setCatGif(state) {
    if (this.img) {
      // 改 src 触发 GIF 从头播放
      this.img.src = 'cats/cat_' + state + '.gif';
    }
  }
}

// === Bubble 气泡管理（宠物说话模式） ===
// 设计：
// 1. 气泡自适应宽度（max-content），最大 280px
// 2. 引用溯源默认折叠，点击按钮展开
// 3. 操作栏（引用按钮 + 关闭按钮）
// 4. 3 秒无操作自动收起
// 5. Esc 键 / 点击关闭按钮立即收起
class BubbleManager {
  constructor() {
    this.bubble = document.getElementById('bubble');
    this.citationsDiv = document.getElementById('bubble-citations');
    this.actionBar = document.getElementById('bubble-action-bar');
    this.btnToggleCitations = document.getElementById('btn-toggle-citations');
    this.btnClose = document.getElementById('btn-close-bubble');
    this.isVisible = false;
    this.autoHideTimer = null;
    this.AUTO_HIDE_MS = 8000; // 8 秒无操作自动收起（给用户足够时间看引用）
  }

  show() {
    if (this.bubble) {
      this.bubble.style.display = 'block';
      this.isVisible = true;
      this.resetAutoHideTimer();
    }
  }

  hide() {
    if (this.bubble) {
      this.bubble.style.display = 'none';
      this.isVisible = false;
      this.clearAutoHideTimer();
      // 重置引用区为折叠状态
      if (this.citationsDiv) this.citationsDiv.classList.remove('expanded');
      if (this.actionBar) this.actionBar.classList.remove('visible');
    }
  }

  /** 显示操作栏（有引用时显示引用按钮） */
  showActionBar(hasCitations) {
    if (!this.actionBar) return;
    this.actionBar.classList.add('visible');
    if (this.btnToggleCitations) {
      this.btnToggleCitations.style.display = hasCitations ? 'inline-block' : 'none';
    }
    this.resetAutoHideTimer();
  }

  /** 切换引用区展开/折叠 */
  toggleCitations() {
    if (!this.citationsDiv) return;
    const expanded = this.citationsDiv.classList.toggle('expanded');
    if (this.btnToggleCitations) {
      this.btnToggleCitations.textContent = expanded ? '📎 收起' : '📎 引用';
    }
    this.resetAutoHideTimer();
  }

  /** 重置自动收起定时器 */
  resetAutoHideTimer() {
    this.clearAutoHideTimer();
    this.autoHideTimer = setTimeout(() => {
      this.hide();
    }, this.AUTO_HIDE_MS);
  }

  clearAutoHideTimer() {
    if (this.autoHideTimer) {
      clearTimeout(this.autoHideTimer);
      this.autoHideTimer = null;
    }
  }
}

// === 全局实例 ===
let catPet = null;
let bubbleManager = null;

// 初始化（DOM 加载后）
document.addEventListener('DOMContentLoaded', () => {
  catPet = new CatPet('pet-img');
  bubbleManager = new BubbleManager();
  console.log('[ima-desktop] CatPet & BubbleManager 已初始化');

  // 操作栏按钮事件绑定
  setupBubbleActions();

  // 触发 Python 桥接的初始化（Task 5 实现）
  if (window.pywebview && window.pywebview.api) {
    window.pywebview.api.get_pet_info().then(info => {
      console.log('[ima-desktop] 宠物信息:', info);
    }).catch(err => console.error('[ima-desktop] 获取宠物信息失败:', err));
  }
});

// === 操作栏事件绑定 ===
function setupBubbleActions() {
  // 关闭按钮
  const btnClose = document.getElementById('btn-close-bubble');
  if (btnClose) {
    btnClose.addEventListener('click', (e) => {
      e.stopPropagation();
      if (bubbleManager) bubbleManager.hide();
    });
  }

  // 引用展开/收起按钮
  const btnToggle = document.getElementById('btn-toggle-citations');
  if (btnToggle) {
    btnToggle.addEventListener('click', (e) => {
      e.stopPropagation();
      if (bubbleManager) bubbleManager.toggleCitations();
    });
  }

  // 气泡内任何交互重置自动收起定时器
  const bubble = document.getElementById('bubble');
  if (bubble) {
    bubble.addEventListener('mouseenter', () => {
      if (bubbleManager) bubbleManager.clearAutoHideTimer();
    });
    bubble.addEventListener('mouseleave', () => {
      if (bubbleManager) bubbleManager.resetAutoHideTimer();
    });
  }

  // 全局 Esc 键收起气泡
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape' && bubbleManager && bubbleManager.isVisible) {
      bubbleManager.hide();
    }
  });
}

// === 供 Python evaluate_js 调用的全局函数 ===
function updateState(state, payload) {
  if (!catPet) return;
  catPet.setState(state);
}

// Python 端主动推送 GIF 状态（直接调用 setCatGif）
function setCatGif(state) {
  if (catPet) {
    catPet.setCatGif(state);
    console.log('[ima-desktop] setCatGif:', state);
  }
}

// Python 端主动推送状态变更（与 updateState 等价，保留向后兼容）
function updateStateDirect(state) {
  if (catPet) {
    catPet.setState(state);
    console.log('[ima-desktop] updateStateDirect:', state);
  }
}

function updatePetStyle(style) {
  console.log('[ima-desktop] 切换人格:', style);
  // 切换人格不影响 GIF 显示，仅记录日志
}

function updateBubble(content) {
  // 设置 #bubble-answer 内容；重置引用区和操作栏。
  const answerDiv = document.getElementById('bubble-answer');
  const citsDiv = document.getElementById('bubble-citations');
  if (answerDiv) {
    answerDiv.innerHTML = escapeHtml(content);
  }
  if (citsDiv) {
    citsDiv.innerHTML = '';
    citsDiv.classList.remove('expanded');
  }
  // 隐藏操作栏，等 showCitations 或 showBubble 决定是否显示
  if (bubbleManager && bubbleManager.actionBar) {
    bubbleManager.actionBar.classList.remove('visible');
  }
}

function showBubble(content) {
  if (bubbleManager) {
    bubbleManager.show();
    updateBubble(content);
    // 显示操作栏（无引用时只显示关闭按钮）
    bubbleManager.showActionBar(false);
  }
}

function hideBubble() {
  if (bubbleManager) bubbleManager.hide();
}

function appendAnswer(chunk) {
  // 将 token 追加到 #bubble-answer，确保气泡可见。
  const answerDiv = document.getElementById('bubble-answer');
  if (!answerDiv) return;
  answerDiv.innerHTML += escapeHtml(chunk);
  if (bubbleManager && !bubbleManager.isVisible) {
    bubbleManager.show();
  } else if (bubbleManager) {
    bubbleManager.resetAutoHideTimer();
  }
}

function showCitations(citations) {
  const citsDiv = document.getElementById('bubble-citations');
  if (!citsDiv || !citations || citations.length === 0) return;

  let html = '<div class="citations"><b>引用溯源</b><ul>';
  citations.forEach(c => {
    const safeTitle = escapeHtml(c.title || '');
    html += `<li><a href="#" data-doc-id="${escapeHtml(c.doc_id || '')}" onclick="window.pywebview.api.show_doc('${escapeHtml(c.doc_id || '')}'); return false;">[${escapeHtml(c.marker || '')}] ${safeTitle} §${escapeHtml(c.paragraph_num || '')}</a></li>`;
  });
  html += '</ul></div>';
  citsDiv.innerHTML = html;

  // 显示操作栏（有引用时显示引用按钮）
  if (bubbleManager) {
    bubbleManager.showActionBar(true);
  }
}

function setSoundEnabled(enabled) {
  // 占位实现，SoundManager 初始化后会被重写
  console.log('[ima-desktop] 音效开关:', enabled);
}

console.log('[ima-desktop] pet.js 已加载');

// === Task 1: 拖拽入库（事件监听在 #pet-img 上） ===
function setupDragAndDrop() {
  const img = document.getElementById('pet-img');
  if (!img) return;

  img.addEventListener('dragover', (e) => {
    e.preventDefault();
    img.classList.add('drag-over');
  });

  img.addEventListener('dragleave', (e) => {
    e.preventDefault();
    img.classList.remove('drag-over');
  });

  img.addEventListener('drop', async (e) => {
    e.preventDefault();
    img.classList.remove('drag-over');

    let filePath = null;
    let pathSource = 'unknown';

    // 策略 1: text/uri-list（macOS Finder 拖拽最可靠的方式，返回 file:///完整路径）
    const uriList = e.dataTransfer.getData('text/uri-list');
    if (uriList) {
      const lines = uriList.split('\n')
        .map((s) => s.trim())
        .filter((s) => s && !s.startsWith('#'));
      if (lines.length > 0 && lines[0].startsWith('file://')) {
        filePath = lines[0];
        pathSource = 'uri-list';
      }
    }

    // 策略 2: _filePath 属性（pywebview WebKit 有时会设置）
    if (!filePath && e.dataTransfer._filePath) {
      filePath = e.dataTransfer._filePath;
      pathSource = '_filePath';
    }

    // 策略 3: dataTransfer.files（某些环境会给 file.path 完整路径）
    if (!filePath && e.dataTransfer.files && e.dataTransfer.files.length > 0) {
      const file = e.dataTransfer.files[0];
      if (file.path) {
        filePath = file.path;
        pathSource = 'file.path';
      } else if (file.name && file.name.includes('/')) {
        // 某些环境 file.name 就是完整路径
        filePath = file.name;
        pathSource = 'file.name(含路径)';
      }
    }

    if (!filePath) {
      console.warn('[ima-desktop] 拖拽未获取到文件路径');
      console.warn('[ima-desktop] dataTransfer 内容:', {
        types: Array.from(e.dataTransfer.types || []),
        uriList: uriList ? uriList.substring(0, 100) : null,
        filesCount: e.dataTransfer.files ? e.dataTransfer.files.length : 0,
      });
      if (bubbleManager) {
        bubbleManager.show();
        const answerDiv = document.getElementById('bubble-answer');
        if (answerDiv) {
          answerDiv.innerHTML = '<span style="color:red">无法获取文件路径，请拖入 Finder 中的文件</span>';
        }
      }
      return;
    }

    console.log('[ima-desktop] 拖拽文件路径:', filePath, '(来源:', pathSource + ')');

    if (window.pywebview && window.pywebview.api && window.pywebview.api.ingest) {
      try {
        const result = await window.pywebview.api.ingest(filePath);
        console.log('[ima-desktop] 入库结果:', result);
      } catch (err) {
        console.error('[ima-desktop] 拖拽入库失败:', err);
        if (bubbleManager) {
          bubbleManager.show();
          const answerDiv = document.getElementById('bubble-answer');
          if (answerDiv) {
            answerDiv.innerHTML = `<span style="color:red">拖拽入库失败: ${escapeHtml(err.message || err)}</span>`;
          }
        }
      }
    } else {
      console.warn('[ima-desktop] pywebview api.ingest 不可用');
    }
  });
}

document.addEventListener('DOMContentLoaded', () => {
  setupDragAndDrop();
});

// === Task 7: 快速问答气泡增强（双击 #pet-img 触发） ===

function setupQuickAsk() {
  const img = document.getElementById('pet-img');
  if (!img) return;

  img.addEventListener('dblclick', (e) => {
    e.preventDefault();
    showQuickAskBubble();
  });
}

function showQuickAskBubble() {
  if (!bubbleManager) return;

  // 恢复 #bubble 子结构，避免 showBubble() 等操作破坏输入区/答案区/引用区
  const inputArea = document.getElementById('bubble-input-area');
  const answerDiv = document.getElementById('bubble-answer');
  const citsDiv = document.getElementById('bubble-citations');
  if (inputArea) {
    inputArea.innerHTML = '<input type="text" id="bubble-input" placeholder="问点什么？" autocomplete="off" autofocus>';
  }
  if (answerDiv) {
    answerDiv.innerHTML = '';
  }
  if (citsDiv) {
    citsDiv.innerHTML = '';
  }

  bubbleManager.show();

  // 聚焦输入框并绑定键盘事件
  setTimeout(() => {
    const input = document.getElementById('bubble-input');
    if (input) {
      input.focus();
      input.addEventListener('keydown', handleQuickAskKeydown);
    }
  }, 50);
}

function handleQuickAskKeydown(e) {
  const input = document.getElementById('bubble-input');
  if (e.key === 'Enter') {
    e.preventDefault();
    if (input) submitQuickAsk(input.value);
  } else if (e.key === 'Escape') {
    if (bubbleManager) bubbleManager.hide();
  }
}

async function submitQuickAsk(question) {
  if (!question.trim()) return;

  // 替换输入区为问题显示
  const answerDiv = document.getElementById('bubble-answer');
  const inputArea = document.getElementById('bubble-input-area');
  if (inputArea) {
    inputArea.innerHTML = `<b>问: ${escapeHtml(question)}</b>`;
  }
  if (answerDiv) {
    answerDiv.innerHTML = '<i>思考中...</i>';
  }

  if (!window.pywebview || !window.pywebview.api) return;

  // 优先调用流式接口；pywebview 对生成器支持有限，
  // Python 端通常通过 evaluate_js("appendAnswer(chunk)") 推送 token。
  if (window.pywebview.api.ask_stream) {
    try {
      const result = await window.pywebview.api.ask_stream(question);
      // 若 ask_stream 返回可迭代对象，消费它
      if (result && typeof result[Symbol.iterator] === 'function' && typeof result !== 'string') {
        let firstToken = true;
        for (const chunk of result) {
          if (firstToken && answerDiv) {
            answerDiv.innerHTML = '';
            firstToken = false;
          }
          appendAnswer(chunk);
        }
      } else if (typeof result === 'string' && answerDiv) {
        // 返回字符串时直接展示
        answerDiv.innerHTML = escapeHtml(result);
      }
      // result 为 undefined/null 时，token 已通过 evaluate_js 推送，无需额外处理
    } catch (err) {
      // 流式失败则降级到同步 ask
      await fallbackAsk(question);
    }
  } else {
    await fallbackAsk(question);
  }
}

async function fallbackAsk(question) {
  // 同步问答降级：整段返回答案
  const answerDiv = document.getElementById('bubble-answer');
  if (!window.pywebview || !window.pywebview.api || !window.pywebview.api.ask) return;
  try {
    const result = await window.pywebview.api.ask(question);
    if (answerDiv) {
      answerDiv.innerHTML = escapeHtml(result);
    }
  } catch (err) {
    if (answerDiv) {
      answerDiv.innerHTML = `<span style="color:red">出错: ${escapeHtml(err.message || err)}</span>`;
    }
  }
}

function escapeHtml(text) {
  const div = document.createElement('div');
  div.textContent = text;
  return div.innerHTML;
}

// 在 DOMContentLoaded 中调用 setupQuickAsk
document.addEventListener('DOMContentLoaded', () => {
  setupQuickAsk();
});

// === Task 10: 音效管理（HTML5 Audio） ===
// 设计要点：
// 1. Python 端通过 evaluate_js("playSound('complete')") 触发 JS 播放
// 2. 10 秒冷却避免噪音（与 Python 端 SoundManager.COOLDOWN_SECONDS 一致）
// 3. 勿扰模式静音自动触发，手动触发仍允许
// 4. 音效开关关闭时立即停止所有正在播放的音频

class SoundManager {
  constructor() {
    this.enabled = true;
    this.dnd = false;
    this.lastPlayTime = {};    // name -> timestamp (ms)
    this.cooldownMs = 10000;   // 10 秒冷却
    this.audioCache = {};      // name -> Audio 对象
  }

  setEnabled(enabled) {
    this.enabled = enabled;
    if (!enabled) {
      // 立即停止所有正在播放的音效
      Object.values(this.audioCache).forEach(audio => {
        try { audio.pause(); } catch (e) { /* 忽略 */ }
      });
    }
  }

  setDnd(dnd) {
    this.dnd = dnd;
  }

  canPlay(name, isManual = false) {
    if (!this.enabled) return false;
    if (this.dnd && !isManual) return false;
    const now = Date.now();
    const last = this.lastPlayTime[name] || 0;
    if (now - last < this.cooldownMs) return false;
    return true;
  }

  play(name, isManual = false) {
    if (!this.canPlay(name, isManual)) return false;

    // 获取或缓存 Audio 对象
    if (!this.audioCache[name]) {
      this.audioCache[name] = new Audio(`sounds/${name}.wav`);
    }

    const audio = this.audioCache[name];
    try {
      audio.currentTime = 0;  // 从头播放
      audio.play().catch(err => {
        console.warn(`[ima-desktop] 音效播放失败 ${name}:`, err);
      });
      this.lastPlayTime[name] = Date.now();
      return true;
    } catch (err) {
      console.warn(`[ima-desktop] 音效播放异常 ${name}:`, err);
      return false;
    }
  }

  // 便捷方法（与 Python 端 SOUND_* 常量对应）
  playComplete(isManual = false) { return this.play('complete', isManual); }
  playIngest(isManual = false) { return this.play('ingest', isManual); }
  playError(isManual = false) { return this.play('error', isManual); }
  playConfirm(isManual = false) { return this.play('confirm', isManual); }
}

// 全局实例
let soundManager = null;

document.addEventListener('DOMContentLoaded', () => {
  soundManager = new SoundManager();
  console.log('[ima-desktop] SoundManager 已初始化');
});

// 供 Python evaluate_js 调用的全局函数
function playSound(name, isManual = false) {
  if (soundManager) {
    return soundManager.play(name, isManual);
  }
  return false;
}

// 重写 setSoundEnabled 占位函数（JS 后定义覆盖前定义）
function setSoundEnabled(enabled) {
  if (soundManager) {
    soundManager.setEnabled(enabled);
    console.log('[ima-desktop] 音效开关:', enabled);
  }
}

function setDndMode(dnd) {
  if (soundManager) {
    soundManager.setDnd(dnd);
  }
}

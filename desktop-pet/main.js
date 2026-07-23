// main.js — Electron 主进程：透明桌宠窗体 + Python 后端驱动 + 状态机 + 托盘
const {
  app, BrowserWindow, Tray, Menu, ipcMain, screen, powerMonitor,
  nativeImage, dialog,
} = require('electron');
const net = require('net');
const path = require('path');
const fs = require('fs');
const { spawn } = require('child_process');
const { loadSettings } = require('./src/settings');
const { StateMachine, STATES } = require('./src/state_machine');

const gotLock = app.requestSingleInstanceLock();
if (!gotLock) { app.quit(); return; }

const SOCKET_PATH = '/tmp/ima-desktop-pet.sock';
const BRIDGE_MODULE = 'core.desktop.electron_bridge';

let win = null;
let tray = null;
let settings = null;
let fsm = null;
let idleCheckTimer = null;
let pythonProcess = null;
let dnd = false;
let dragState = { active: false, offsetX: 0, offsetY: 0 };
let bubbleVisible = false; // 气泡是否展开

// 窗口尺寸常量（原版：260×360，上方透明区留给气泡，下方显示宠物）
const WIN_W = 260;
const WIN_H = 360;

const IDLE_THRESHOLD_SEC = 300; // 5 分钟无操作 → sleeping

function resolveStateGif(state) {
  return path.join(__dirname, 'assets', `cat_${state}.gif`);
}

// === Python 后端管理 ===
function findPythonExecutable() {
  const candidates = [
    path.join(__dirname, '..', '.venv', 'bin', 'python'),
    path.join(__dirname, '..', '.venv', 'Scripts', 'python.exe'),
    '/usr/bin/python3',
    '/usr/local/bin/python3',
    'python3',
    'python',
  ];
  for (const c of candidates) {
    if (fs.existsSync(c)) return c;
  }
  return null;
}

function startPythonBridge() {
  const python = findPythonExecutable();
  if (!python) {
    dialog.showErrorBox('启动失败', '找不到 Python 解释器，请确认 .venv 存在');
    app.quit();
    return;
  }
  const projectRoot = path.join(__dirname, '..');
  pythonProcess = spawn(python, ['-m', BRIDGE_MODULE], {
    cwd: projectRoot,
    stdio: ['ignore', 'pipe', 'pipe'],
    detached: false,
  });
  pythonProcess.stdout.on('data', (d) => {
    const lines = d.toString().trim().split('\n');
    for (const line of lines) {
      if (!line) continue;
      try {
        const msg = JSON.parse(line);
        if (msg.type === 'set_state') {
          setState(msg.state, 'external');
        } else {
          console.log('[python]', line);
        }
      } catch (e) {
        console.log('[python]', line);
      }
    }
  });
  pythonProcess.stderr.on('data', (d) => console.error('[python]', d.toString().trim()));
  pythonProcess.on('exit', (code) => {
    console.log(`Python 后端已退出 (code=${code})`);
    pythonProcess = null;
  });
}

function waitForSocket(timeoutMs = 30000) {
  return new Promise((resolve, reject) => {
    const start = Date.now();
    const tryConnect = () => {
      const client = net.createConnection(SOCKET_PATH, () => {
        // 发送一个 ping 再关闭，避免 server 端 recv 空连接超时
        client.write(JSON.stringify({ action: 'ping' }) + '\n');
        client.end();
        resolve();
      });
      client.on('error', () => {
        if (Date.now() - start > timeoutMs) {
          reject(new Error('等待 Python 后端超时'));
        } else {
          setTimeout(tryConnect, 200);
        }
      });
    };
    tryConnect();
  });
}

function sendToPython(request, options = {}) {
  const { timeoutMs = 180000, onEvent = null } = options;
  return new Promise((resolve, reject) => {
    if (!fs.existsSync(SOCKET_PATH)) {
      reject(new Error('Python 后端未运行'));
      return;
    }
    const client = net.createConnection(SOCKET_PATH);
    let buf = '';
    const responses = [];
    let timeoutId = null;
    let settled = false;

    client.setEncoding('utf8');
    client.on('connect', () => {
      client.write(JSON.stringify(request) + '\n');
      // 半关闭写端，让 Python 后端知道请求已发送完，处理完即可关闭连接
      client.end();
    });
    client.on('data', (data) => {
      buf += data;
      let idx;
      while ((idx = buf.indexOf('\n')) !== -1) {
        const line = buf.slice(0, idx);
        buf = buf.slice(idx + 1);
        if (line.trim()) {
          try {
            const ev = JSON.parse(line);
            responses.push(ev);
            if (onEvent) onEvent(ev);
          } catch (e) {
            console.error('解析 Python 响应失败:', line);
          }
        }
      }
    });
    client.on('end', () => {
      if (settled) return;
      settled = true;
      if (timeoutId) clearTimeout(timeoutId);
      resolve(responses);
    });
    client.on('error', (err) => {
      if (settled) return;
      settled = true;
      if (timeoutId) clearTimeout(timeoutId);
      reject(err);
    });

    timeoutId = setTimeout(() => {
      if (settled) return;
      settled = true;
      client.destroy();
      reject(new Error('请求 Python 后端超时'));
    }, timeoutMs);
  });
}

// === 窗口 ===
function createWindow() {
  const { width: screenW, height: screenH } = screen.getPrimaryDisplay().workAreaSize;
  const saved = settings.get('position');
  // 整体等比 75% 缩放：上方透明区留给气泡，下方显示宠物
  const x = saved ? saved[0] : Math.round(screenW / 2 - WIN_W / 2);
  const y = saved ? saved[1] : screenH - WIN_H - 40;

  win = new BrowserWindow({
    width: WIN_W,
    height: WIN_H,
    x,
    y,
    frame: false,
    transparent: true,
    alwaysOnTop: true,
    resizable: false,
    skipTaskbar: true,
    hasShadow: false,
    focusable: true,
    acceptFirstMouse: true,
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
    },
  });

  win.setAlwaysOnTop(true, 'screen-saver');
  win.setVisibleOnAllWorkspaces(true, { visibleOnFullScreen: true });
  win.loadFile(path.join(__dirname, 'renderer', 'index.html'));

  win.once('ready-to-show', () => {
    win.show();
    win.focus();
  });

  // 把 renderer 的 console.log 重定向到主进程终端，方便调试
  win.webContents.on('console-message', (event, level, message) => {
    const prefix = '[renderer]';
    if (level === 3) console.error(prefix, message);
    else console.log(prefix, message);
  });

  // 兜底：macOS 上拖文件到透明窗口可能触发导航而非 DnD
  win.webContents.on('will-navigate', (event, url) => {
    if (url.startsWith('file://')) {
      event.preventDefault();
      const filePath = decodeURIComponent(url.slice(7));
      console.log('[main] will-navigate 拦截到文件:', filePath);
      handleIngest(filePath);
    }
  });

  win.on('moved', () => {
    if (!win) return;
    settings.set('position', win.getPosition());
  });
  win.on('closed', () => { win = null; });
}

// === 状态机 ===
function setState(state, source = 'external') {
  if (!fsm.transition(state, source)) return;
  if (win && !win.isDestroyed()) {
    win.webContents.send('state-changed', { state, gif: resolveStateGif(state) });
  }
  rebuildTray();
}

function stateLabel(s) {
  const map = {
    idle: '待机', listening: '倾听', thinking: '思考', retrieving: '检索',
    ranking: '排名', answering: '回答', celebrating: '庆祝', error: '报错',
    sleeping: '睡眠', ingesting: '入库', analyzing: '分析', notifying: '提醒',
  };
  return map[s] || s;
}

// === 托盘 ===
function buildTrayMenu() {
  const stateItems = STATES.map((s) => ({
    label: stateLabel(s),
    type: 'radio',
    checked: fsm.current === s,
    click: () => setState(s, 'manual'),
  }));

  return Menu.buildFromTemplate([
    { label: `当前：${stateLabel(fsm.current)}`, enabled: false },
    { type: 'separator' },
    ...stateItems,
    { type: 'separator' },
    {
      label: '免打扰（保持睡眠）',
      type: 'checkbox',
      checked: dnd,
      click: (item) => {
        dnd = item.checked;
        if (dnd) setState('sleeping', 'dnd');
        else setState('idle', 'dnd-off');
        rebuildTray();
      },
    },
    {
      label: '开机自启',
      type: 'checkbox',
      checked: settings.get('autoLaunch') || false,
      click: (item) => {
        settings.set('autoLaunch', item.checked);
        app.setLoginItemSettings({ openAtLogin: item.checked });
      },
    },
    { type: 'separator' },
    { label: '退出', click: () => app.quit() },
  ]);
}

function rebuildTray() {
  if (!tray) return;
  tray.setContextMenu(buildTrayMenu());
  tray.setToolTip(`IMA 宠物 · ${stateLabel(fsm.current)}`);
}

function startIdleMonitor() {
  idleCheckTimer = setInterval(() => {
    const idleSec = powerMonitor.getSystemIdleTime();
    if (dnd) return;
    if (idleSec >= IDLE_THRESHOLD_SEC && fsm.current !== 'sleeping') {
      setState('sleeping', 'idle-auto');
    } else if (idleSec < 5 && fsm.current === 'sleeping') {
      setState('idle', 'wake-auto');
    }
  }, 3000);
}

// === IPC: renderer → main ===
ipcMain.handle('ask-stream', async (event, question, history) => {
  if (!question.trim()) return;
  setState('listening', 'external');
  let gotDone = false;
  let gotError = false;
  try {
    await sendToPython({ action: 'ask_stream', question, history }, {
      onEvent: (r) => {
        console.log('[main] onEvent:', r.type, r.type === 'token' ? 'chunk_len=' + (r.chunk ? r.chunk.length : 0) : '');
        if (!win || win.isDestroyed()) return;
        if (r.type === 'stage') {
          const stageMap = { 检索: 'retrieving', 重排: 'ranking', 缓存: 'thinking' };
          if (stageMap[r.stage]) setState(stageMap[r.stage], 'external');
          // 转发阶段信息给渲染进程，用于气泡状态提示
          win.webContents.send('answer-stage', { stage: r.stage, count: r.count || 0 });
        } else if (r.type === 'token') {
          setState('answering', 'external');
          win.webContents.send('answer-token', r.chunk);
        } else if (r.type === 'done') {
          gotDone = true;
          setState('celebrating', 'external');
          setTimeout(() => setState('idle', 'manual'), 2500);
          win.webContents.send('answer-done', r.citations || []);
        } else if (r.type === 'error') {
          gotError = true;
          setState('error', 'external');
          win.webContents.send('answer-error', r.error);
        }
      },
    });
    // 兜底：后端流结束但未发送 done/error，强制回 idle（manual 优先级可覆盖任何状态）
    if (!gotDone && !gotError) {
      console.warn('ask-stream 结束但未收到 done/error，强制回 idle');
      setState('idle', 'manual');
      if (win && !win.isDestroyed()) {
        win.webContents.send('answer-error', '回复异常结束');
      }
    }
  } catch (err) {
    console.error('ask-stream 失败:', err);
    setState('error', 'external');
    if (win && !win.isDestroyed()) win.webContents.send('answer-error', err.message);
  }
});

async function handleIngest(filePath) {
  setState('ingesting', 'manual');
  try {
    const responses = await sendToPython({ action: 'ingest', file_path: filePath });
    const result = responses[0]?.data || {};
    let msg;
    // already_exists 视为已存在提示，不显示为失败
    if (result.success || result.error === 'already_exists') {
      msg = result.error === 'already_exists' ? `已存在：${result.file_name}` : `已入库：${result.file_name}`;
      setState('celebrating', 'external');
    } else {
      msg = `失败：${result.error || '未知错误'}`;
      setState('error', 'external');
    }
    if (win && !win.isDestroyed()) win.webContents.send('show-bubble', msg);
    // 兜底：确保入库结束后状态回 idle（manual 可覆盖 ingesting 的 manual 优先级）
    setTimeout(() => setState('idle', 'manual'), 2500);
  } catch (err) {
    console.error('ingest 失败:', err);
    setState('error', 'external');
    if (win && !win.isDestroyed()) win.webContents.send('show-bubble', `失败：${err.message}`);
    setTimeout(() => setState('idle', 'manual'), 2500);
  }
}

ipcMain.handle('ingest', async (event, filePath) => {
  await handleIngest(filePath);
});

ipcMain.handle('ingest-text', async (event, text) => {
  if (!text || !text.trim()) return;
  const uploadsDir = path.join(__dirname, '..', 'storage', 'uploads');
  fs.mkdirSync(uploadsDir, { recursive: true });
  const fileName = `pasted_text_${Date.now()}.md`;
  const filePath = path.join(uploadsDir, fileName);
  fs.writeFileSync(filePath, text.trim(), 'utf8');
  await handleIngest(filePath);
});

ipcMain.handle('ingest-image', async (event, dataUrl, fileName) => {
  if (!dataUrl || !fileName) return;
  const uploadsDir = path.join(__dirname, '..', 'storage', 'uploads');
  fs.mkdirSync(uploadsDir, { recursive: true });
  const base64 = dataUrl.replace(/^data:image\/\w+;base64,/, '');
  const buffer = Buffer.from(base64, 'base64');
  const filePath = path.join(uploadsDir, fileName);
  fs.writeFileSync(filePath, buffer);
  await handleIngest(filePath);
});

ipcMain.handle('show-doc', async (event, docId) => {
  try {
    await sendToPython({ action: 'show_doc', doc_id: docId });
  } catch (err) {
    console.error('show-doc 失败:', err);
  }
});

ipcMain.on('drag-start', (event, { screenX, screenY }) => {
  if (!win) return;
  const [x, y] = win.getPosition();
  dragState.active = true;
  dragState.offsetX = screenX - x;
  dragState.offsetY = screenY - y;
});

ipcMain.on('drag-delta', (event, { dx, dy }) => {
  if (!win || !dragState.active) return;
  const [x, y] = win.getPosition();
  win.setPosition(Math.round(x + dx), Math.round(y + dy));
});

ipcMain.on('drag-end', () => {
  dragState.active = false;
});

ipcMain.on('bubble-visible', (event, visible) => {
  // 原版：气泡显示时保持可交互；隐藏后仍允许拖动
  // 不调整窗口尺寸，避免宠物位置跳变
  if (win) {
    // macOS 上 focusable 动态切换可能闪烁，暂不处理
  }
});

// === App 生命周期 ===
app.whenReady().then(async () => {
  settings = loadSettings(app.getPath('userData'));
  fsm = new StateMachine('idle');
  fsm.onAutoReturn((state) => {
    if (win && !win.isDestroyed()) {
      win.webContents.send('state-changed', { state, gif: resolveStateGif(state) });
    }
    rebuildTray();
  });

  startPythonBridge();
  try {
    await waitForSocket();
  } catch (e) {
    dialog.showErrorBox('后端启动失败', e.message);
    app.quit();
    return;
  }

  createWindow();

  // 托盘图标
  let icon = nativeImage.createFromPath(resolveStateGif('idle'));
  icon = icon.resize({ width: 18, height: 18 });
  tray = new Tray(icon);
  rebuildTray();

  startIdleMonitor();
  try {
    app.setLoginItemSettings({ openAtLogin: settings.get('autoLaunch') || false });
  } catch (e) {
    console.warn('设置开机自启失败（权限不足）:', e.message);
  }

  // 拉取宠物信息并推给前端
  try {
    const responses = await sendToPython({ action: 'get_pet_info' });
    if (responses[0]?.success && win && !win.isDestroyed()) {
      win.webContents.send('pet-info', responses[0].data);
    }
  } catch (e) {
    console.error('获取宠物信息失败:', e);
  }

  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) createWindow();
  });
});

app.on('window-all-closed', () => {
  // 桌宠常驻托盘，关窗不退出；显式退出走托盘菜单
});

app.on('before-quit', () => {
  if (idleCheckTimer) clearInterval(idleCheckTimer);
  if (pythonProcess) {
    pythonProcess.kill();
    pythonProcess = null;
  }
  if (settings) settings.flush();
});

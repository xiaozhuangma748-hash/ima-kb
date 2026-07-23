// preload.js — Electron 渲染进程与主进程的安全桥
const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('petAPI', {
  // 主进程 → 渲染进程（订阅）
  onStateChanged: (cb) => ipcRenderer.on('state-changed', (e, data) => cb(data)),
  onPetInfo: (cb) => ipcRenderer.on('pet-info', (e, data) => cb(data)),
  onAnswerToken: (cb) => ipcRenderer.on('answer-token', (e, data) => cb(data)),
  onAnswerStage: (cb) => ipcRenderer.on('answer-stage', (e, data) => cb(data)),
  onAnswerDone: (cb) => ipcRenderer.on('answer-done', (e, data) => cb(data)),
  onAnswerError: (cb) => ipcRenderer.on('answer-error', (e, data) => cb(data)),
  onShowBubble: (cb) => ipcRenderer.on('show-bubble', (e, data) => cb(data)),

  // 渲染进程 → 主进程（调用）
  askStream: (question, history) => ipcRenderer.invoke('ask-stream', question, history),
  ingest: (filePath) => ipcRenderer.invoke('ingest', filePath),
  ingestText: (text) => ipcRenderer.invoke('ingest-text', text),
  ingestImage: (dataUrl, fileName) => ipcRenderer.invoke('ingest-image', dataUrl, fileName),
  showDoc: (docId) => ipcRenderer.invoke('show-doc', docId),
  dragStart: (screenX, screenY) => ipcRenderer.send('drag-start', { screenX, screenY }),
  dragDelta: (dx, dy) => ipcRenderer.send('drag-delta', { dx, dy }),
  dragEnd: () => ipcRenderer.send('drag-end'),
  bubbleVisible: (visible) => ipcRenderer.send('bubble-visible', visible),
});

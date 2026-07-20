// src/settings.js — 配置持久化（JSON 原子写入）
const fs = require('fs');
const path = require('path');

class Settings {
  constructor(userDataDir) {
    this.file = path.join(userDataDir, 'desktop-pet-settings.json');
    this.data = {};
    try {
      if (fs.existsSync(this.file)) {
        this.data = JSON.parse(fs.readFileSync(this.file, 'utf8'));
      }
    } catch (e) {
      this.data = {};
    }
    this._flushTimer = null;
  }

  get(key) { return this.data[key]; }

  set(key, value) {
    this.data[key] = value;
    // 位置等高频写入做 500ms 防抖
    if (this._flushTimer) clearTimeout(this._flushTimer);
    this._flushTimer = setTimeout(() => this.flush(), 500);
  }

  flush() {
    try {
      const tmp = this.file + '.tmp';
      fs.writeFileSync(tmp, JSON.stringify(this.data, null, 2));
      fs.renameSync(tmp, this.file);
    } catch (e) { /* 静默 */ }
  }
}

let instance = null;
function loadSettings(userDataDir) {
  if (!instance) instance = new Settings(userDataDir);
  return instance;
}

module.exports = { loadSettings };

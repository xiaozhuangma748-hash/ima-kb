// src/state_machine.js — 状态机：12 状态 + 优先级 + 最小驻留时长
const STATES = [
  'idle', 'listening', 'thinking', 'retrieving', 'ranking', 'answering',
  'celebrating', 'error', 'sleeping', 'ingesting', 'analyzing', 'notifying',
];

// 事件态播放完后自动回到 idle 的最短驻留（毫秒）
const EVENT_MIN_DWELL = {
  celebrating: 2500,
  error: 2500,
  notifying: 2000,
  answering: 0, // 由外部决定何时结束
};

// 手动切换 > 外部事件 > 自动（闲置/唤醒）
const SOURCE_PRIORITY = { manual: 3, external: 2, 'dnd': 3, 'dnd-off': 3, 'idle-auto': 1, 'wake-auto': 1, auto: 1 };

class StateMachine {
  constructor(initial = 'idle') {
    this.current = initial;
    this.lastSource = 'auto';
    this.enteredAt = Date.now();
    this._dwellTimer = null;
    this._onAutoReturn = null;
  }

  onAutoReturn(cb) { this._onAutoReturn = cb; }

  canTransition(next, source) {
    if (!STATES.includes(next)) return false;
    if (next === this.current) return false;
    const curP = SOURCE_PRIORITY[this.lastSource] || 0;
    const newP = SOURCE_PRIORITY[source] || 0;
    // 低优先级不能打断高优先级（例如 idle-auto 不能打断 manual 设置的状态）
    if (newP < curP) return false;
    return true;
  }

  transition(next, source = 'auto') {
    if (!this.canTransition(next, source)) return false;
    if (this._dwellTimer) { clearTimeout(this._dwellTimer); this._dwellTimer = null; }
    this.current = next;
    this.lastSource = source;
    this.enteredAt = Date.now();

    const dwell = EVENT_MIN_DWELL[next];
    if (dwell !== undefined && dwell > 0) {
      this._dwellTimer = setTimeout(() => {
        this.current = 'idle';
        this.lastSource = 'auto';
        if (this._onAutoReturn) this._onAutoReturn('idle');
      }, dwell);
    }
    return true;
  }
}

module.exports = { StateMachine, STATES };

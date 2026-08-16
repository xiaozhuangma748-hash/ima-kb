// 两栏列宽求解：侧栏（折叠 56px rail / 展开取拖拽偏好）+ 中间自适应。
// 中间栏保底 CENTER_MIN；不够时侧栏压缩到下限，再不够直接占满。

export const CENTER_MIN = 640;
export const SIDEBAR_MIN = 264;
export const SIDEBAR_MAX = 420;
export const SIDEBAR_DEFAULT = 280;
export const SIDEBAR_COLLAPSED = 56;
export const SIDEBAR_AUTO_COLLAPSE = 1024;

export function clampWidth(px, min, max) {
  return Math.min(max, Math.max(min, Math.round(px)));
}

// sidebar: 0 = closed(折叠)。
export function computeColumns(viewport, sidebar) {
  const s = sidebar === 0 ? SIDEBAR_COLLAPSED : clampWidth(sidebar, SIDEBAR_MIN, SIDEBAR_MAX);
  if (s + CENTER_MIN <= viewport) {
    return { sidebar: s, center: viewport - s };
  }
  const s1 = Math.max(SIDEBAR_COLLAPSED, Math.min(s, viewport - CENTER_MIN));
  return { sidebar: s1, center: Math.max(0, viewport - s1) };
}
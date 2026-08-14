// 三栏让步链列宽求解（移植自 DeepSeek Harness AppFrame/columns.ts）
// 中间栏保底 CENTER_MIN；不够则压缩 details，再不够自动关闭 details。
// 侧栏不妥协：折叠态 56px rail，展开态取拖拽偏好。

export const CENTER_MIN = 640;
export const SIDEBAR_MIN = 264;
export const SIDEBAR_MAX = 420;
export const SIDEBAR_DEFAULT = 280;
export const SIDEBAR_COLLAPSED = 56;
export const SIDEBAR_AUTO_COLLAPSE = 1024;
export const DETAILS_MIN = 300;
export const DETAILS_MAX = 520;
export const DETAILS_DEFAULT = 360;

export function clampWidth(px, min, max) {
  return Math.min(max, Math.max(min, Math.round(px)));
}

// sidebar: 0 = closed(折叠)。details: 0 = closed。
export function computeColumns(viewport, sidebar, details) {
  const s = sidebar === 0 ? SIDEBAR_COLLAPSED : clampWidth(sidebar, SIDEBAR_MIN, SIDEBAR_MAX);
  const d0 = details === 0 ? 0 : clampWidth(details, DETAILS_MIN, DETAILS_MAX);

  if (s + d0 + CENTER_MIN <= viewport) {
    return { sidebar: s, center: viewport - s - d0, details: d0 };
  }
  const d1 = d0 === 0 ? 0 : Math.max(DETAILS_MIN, viewport - s - CENTER_MIN);
  if (s + d1 + CENTER_MIN <= viewport) {
    return { sidebar: s, center: CENTER_MIN, details: d1 };
  }
  return { sidebar: s, center: Math.max(0, viewport - s), details: 0 };
}
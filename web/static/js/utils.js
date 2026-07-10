// 公共工具函数

export function escapeHtml(str) {
  const d = document.createElement('div');
  d.textContent = str;
  return d.innerHTML;
}

// 全局错误提示：在指定容器顶部插入错误提示，5 秒后自动移除
export function showError(containerId, message) {
  const container = document.getElementById(containerId);
  if (container) {
    const errorDiv = document.createElement('div');
    errorDiv.style.cssText = 'color:var(--accent-red);padding:12px;background:rgba(239,68,68,0.1);border-radius:var(--radius);margin:8px 0';
    errorDiv.textContent = '请求失败: ' + message;
    container.prepend(errorDiv);
    setTimeout(() => errorDiv.remove(), 5000);
  }
}

export function formatSize(bytes) {
  if (bytes < 1024) return bytes + ' B';
  if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB';
  return (bytes / (1024 * 1024)).toFixed(1) + ' MB';
}

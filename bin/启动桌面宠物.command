#!/bin/zsh
# macOS 双击启动桌面宠物（Electron 版）
cd "$(dirname "$0")"
unset ELECTRON_RUN_AS_NODE 2>/dev/null
unset NODE_OPTIONS 2>/dev/null

if ! command -v node &>/dev/null; then
  osascript -e 'display alert "错误" message "未找到 Node.js，请先安装 Node.js 18+"'
  exit 1
fi

if [ ! -d "./desktop-pet/node_modules" ]; then
  echo "正在安装 Electron 依赖..."
  (cd desktop-pet && npm install)
  if [ $? -ne 0 ]; then
    osascript -e 'display alert "错误" message "Electron 依赖安装失败"'
    exit 1
  fi
fi

echo "🐱 启动 IMA 桌面宠物 (Electron)..."
echo "   按 Ctrl+C 退出"
echo ""

cd desktop-pet
exec npm start

#!/bin/zsh
# IMA 桌面宠物依赖安装脚本（零侵入：仅安装到项目 .venv）
cd "$(dirname "$0")"

if [ ! -d "./.venv" ]; then
  echo "未检测到项目虚拟环境 .venv，请先运行 install.sh 安装知识库本体"
  exit 1
fi

echo "安装桌面宠物依赖到 .venv ..."
./.venv/bin/pip install -r requirements-desktop.txt

echo ""
echo "安装完成。启动桌面宠物："
echo "  ./ima-desktop"
echo ""
echo "首次使用请确保已在 REPL 中执行 /pet adopt 领养宠物。"

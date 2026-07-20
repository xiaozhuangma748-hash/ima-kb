#!/bin/zsh
# 双击此文件即可在 macOS 真机启动桌面宠物（不受 WorkBuddy 沙箱限制）
cd "$(dirname "$0")"
unset NODE_OPTIONS
unset ELECTRON_RUN_AS_NODE
exec ./node_modules/.bin/electron .

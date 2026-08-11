# IMA-KB 桌面宠物（Electron 版）

参照 [clawd-on-desk](https://github.com/rullerzhou-afk/clawd-on-desk) 的 Electron 架构，配套 Python 知识库后端（`core/desktop/electron_bridge.py`）实现的桌面宠物。通过 Unix domain socket 与 Python 后端双向通信，可驱动 RAG 问答、入库、命令执行等所有知识库功能。

## 快速启动

**前置条件**：项目根目录已运行 `./bin/install.sh` 完成 Python 环境安装，且已通过 `ima` 命令领养宠物（`/pet adopt <名字>`）。

**方式一（推荐，真机双击）**：双击项目根目录的 `bin/启动桌面宠物.command`
（如遇"无法打开"，右键 → 打开 → 打开）

**方式二（命令行）**：
```bash
./bin/ima-desktop
```

脚本会自动检查 Node.js 18+ 和 `desktop-pet/node_modules`，缺失时自动 `npm install`。

## 架构

```
┌─────────────────────────────┐
│   Electron 主进程 (main.js)  │  透明窗体 + 托盘 + 状态机 + IPC
├─────────────────────────────┤
│   Unix socket 双向通信       │  /tmp/ima-desktop-pet.sock
├─────────────────────────────┤
│   Python 后端                │  core/desktop/electron_bridge.py
│   - PetAdministrator         │  宠物管理员（人格风格 + RAG）
│   - IpcServer                │  处理 ask_stream/ingest/exec_cli_command 等
└─────────────────────────────┘
```

**通信协议**：主进程通过 `net.createConnection` 发送 JSON 行请求，后端流式返回多行 JSON 事件（`stage` / `token` / `done` / `error`）。

## 功能

| 功能 | 说明 |
|---|---|
| 12 状态动画 | idle/listening/thinking/retrieving/ranking/answering/celebrating/error/sleeping/ingesting/analyzing/notifying |
| 透明置顶窗体 | 无边框、始终置顶、所有工作区可见 |
| 拖拽移动 | 按住宠物拖动，松手记住位置 |
| 位置记忆 | 重启后恢复上次位置（`~/Library/Application Support/ima-kb-desktop-pet/desktop-pet-settings.json`） |
| 闲置睡眠 | 5 分钟无键鼠操作 → 自动 sleeping；活动后唤醒回 idle |
| 托盘菜单 | 菜单栏图标：手动切任意状态 / 免打扰 / 开机自启 / 退出 |
| 免打扰 | 锁定 sleeping，不被自动唤醒 |
| 开机自启 | 托盘勾选后生效 |
| 气泡问答 | 点击宠物弹出气泡，支持流式输出、Markdown 渲染、引用溯源、阶段提示 |
| 拖拽入库 | 拖文件到宠物身上自动入库（PDF/Word/Excel/PPT/图片...） |
| 命令面板 | 气泡输入框支持 `/` 命令（如 `/pet`、`/search`、`/ingest`） |
| 未读徽章 | 气泡关闭时后端完成输出，徽章提示有新内容 |

## 状态机

- 常驻态：`idle`（默认）、`sleeping`
- 工作态（对应知识库 RAG 流水线）：`listening → thinking → retrieving → ranking → answering`
- 事件态：`celebrating`/`error`/`notifying` 播 2-2.5s 后自动回 idle；`ingesting`/`analyzing` 由外部控制
- 优先级：手动切换 > 外部事件 > 自动（闲置/唤醒）

## 项目结构

```
desktop-pet/
├── main.js                  # 主进程：窗体+托盘+闲置检测+IPC+Python 后端管理
├── preload.js               # 安全桥
├── renderer/
│   ├── index.html           # 透明窗体 + 气泡 + GIF + 命令面板
│   └── renderer.js          # 拖拽 + 状态切换 + 流式渲染 + 鼠标穿透
├── src/
│   ├── state_machine.js     # 12 状态状态机
│   └── settings.js          # 配置持久化（防抖+原子写入）
├── assets/                  # 12 个像素猫 GIF
├── 启动桌面宠物.command      # macOS 双击启动器
└── package.json
```

Python 后端模块（位于项目根目录的 `core/desktop/`）：

- `electron_bridge.py` — Electron 模式入口，初始化 PetAdministrator + IpcServer
- `ipc.py` — Unix socket 服务端，定义协议
- `pet_wrapper.py` / `tray_runner.py` — 其他启动模式（pywebview / 系统托盘）

## 打包成 .app（可选）

```bash
cd desktop-pet
npm run dist   # electron-builder，需先 npm i -D electron-builder
```

## 依赖

- Node.js 18+（推荐 20.x 或 22.x）
- Electron ^33（`npm install` 自动安装；国内慢可设 `ELECTRON_MIRROR=https://npmmirror.com/mirrors/electron/`）
- 项目根目录已安装的 Python `.venv`（含 PetAdministrator 依赖）

## 调试

启动后 Electron 主进程的 `console.log` 输出到启动它的终端；Python 后端的日志通过 `[python]` 前缀转发到同一终端。Renderer 进程的 `console.log` 也会以 `[renderer]` 前缀转发。

常见问题：

- **"后端启动失败"对话框**：通常是 `.venv` 缺失或 `core.desktop.electron_bridge` 模块导入失败，到项目根目录跑 `./bin/install.sh` 修复
- **socket 文件残留**：手动 `rm /tmp/ima-desktop-pet.sock` 后重启
- **宠物不显示**：检查托盘菜单是否在"免打扰"状态
